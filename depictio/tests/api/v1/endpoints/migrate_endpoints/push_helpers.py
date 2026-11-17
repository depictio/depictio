"""Shared pieces of the inbound-push tests: a fake S3 that can copy and delete, a
configured target instance, and a way to run the route functions and the
background import directly (no HTTP server)."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from types import SimpleNamespace
from typing import Any

from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import BackgroundTasks, UploadFile

from depictio.api.v1.configs.settings_models import MigrationInboundSource
from depictio.api.v1.endpoints.migrate_endpoints import inbound_routes, requests_routes
from depictio.api.v1.services import project_bundle

from .conftest import FakeS3

KEY = "k" * 40
OTHER_KEY = "o" * 40
SOURCE = "lab"


class MigS3(FakeS3):
    """FakeS3 plus what the push needs: head, server-side copy, delete."""

    def __init__(self) -> None:
        super().__init__()
        self.copy_log: list[str] = []

    @staticmethod
    def etag_of(key: str, body: bytes) -> str:
        return f"etag-{len(body)}-{key}"

    def head_object(self, Bucket: str, Key: str):
        if Key not in self.buckets.get(Bucket, {}):
            raise ClientError({"Error": {"Code": "404", "Message": "nope"}}, "HeadObject")
        return {}

    def copy_object(self, Bucket, Key, CopySource, CopySourceIfMatch=None):
        body = self.buckets[CopySource["Bucket"]][CopySource["Key"]]
        if CopySourceIfMatch and CopySourceIfMatch != self.etag_of(Key, body):
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "etag"}}, "CopyObject"
            )
        self.put(Bucket, Key, body)
        self.copy_log.append(Key)

    def delete_object(self, Bucket, Key):
        self.buckets.get(Bucket, {}).pop(Key, None)


def configure_target(monkeypatch, target_db, s3, **source_opts) -> SimpleNamespace:
    """Make this process the target of a push from the source ``lab``."""
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions as dash_core
    from depictio.api.v1.endpoints.migrate_endpoints import routes
    from depictio.api.v1.services import migration_import

    source = MigrationInboundSource(name=SOURCE, pairing_key=KEY, **source_opts)
    monkeypatch.setattr(settings.migration, "inbound_enabled", True)
    monkeypatch.setattr(settings.migration, "inbound_sources", [source])
    monkeypatch.setattr(settings.s3, "bucket", "tgt-bucket")
    # ``endpoint_url`` is a derived property, so it is replaced on the class.
    monkeypatch.setattr(type(settings.s3), "endpoint_url", property(lambda self: "http://s3:9000"))

    target_db.migration_requests_collection = target_db.projects_collection.database[
        "migration_requests"
    ]
    monkeypatch.setattr(migration_import, "_db", lambda: target_db)
    monkeypatch.setattr(routes, "_instance_s3_client", lambda: s3)
    monkeypatch.setattr(inbound_routes, "_instance_s3_client", lambda: s3)
    monkeypatch.setattr(dash_core, "dashboards_collection", target_db.dashboards_collection)
    monkeypatch.setattr(project_bundle, "default_invalidate", lambda dc_id: None)
    return SimpleNamespace(source=source, db=target_db, s3=s3)


def manifest_zip(payload: bytes, s3: MigS3, bucket: str = "src-bucket") -> bytes:
    """An inline bundle turned into a server-side-copy one: manifest, no data."""
    out = io.BytesIO()
    manifest = []
    meta: dict = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            if info.filename.startswith(project_bundle.S3_DATA_PREFIX):
                key = info.filename[len(project_bundle.S3_DATA_PREFIX) :]
                body = s3.buckets[bucket][key]
                manifest.append({"key": key, "size": len(body), "etag": s3.etag_of(key, body)})
                continue
            if info.filename == "s3_metadata.json":
                meta = json.loads(src.read(info.filename))
                continue
            dst.writestr(info, src.read(info.filename))
        dst.writestr("s3_metadata.json", json.dumps({**meta, "manifest": manifest}))
    return out.getvalue()


def push(payload: bytes, source, *, sha=None, mode="inline", email="author@source.org", **kw):
    """Call the inbound upload route as the paired source would."""
    import hashlib

    return asyncio.run(
        inbound_routes.inbound_create_request(
            file=UploadFile(file=io.BytesIO(payload), filename="bundle.zip"),
            sha256=sha or hashlib.sha256(payload).hexdigest(),
            transfer_mode=mode,
            requester_email=email,
            requester_name=kw.get("name", "Ann Author"),
            source_user_id=kw.get("source_user_id"),
            message=kw.get("message"),
            source=source,
        )
    )


def admin(email="admin@target.org") -> Any:
    return SimpleNamespace(id=ObjectId(), email=email, is_admin=True)


def approve(request_id: str, user, *, lock=None, make_public=False) -> dict:
    """Approve through the route, then run the queued background import."""
    tasks = BackgroundTasks()
    out = asyncio.run(
        requests_routes.approve_request(
            request_id,
            tasks,
            requests_routes.ApproveBody(lock=lock, make_public=make_public),
            current_user=user,
        )
    )
    for task in tasks.tasks:
        task.func(*task.args, **task.kwargs)
    return out


def build_world(monkeypatch, target_db, **source_opts) -> SimpleNamespace:
    """A source project exported to a ZIP, and this process configured as the target.

    One fake S3 stands for the shared endpoint: ``src-bucket`` holds the
    source's data, ``tgt-bucket`` is where the target writes.
    """
    from .conftest import make_db, seed_source_project
    from .test_bundle_roundtrip import _export_zip

    src_db = make_db()
    ids = seed_source_project(src_db)
    s3 = MigS3()
    s3.put("src-bucket", f"{ids['table_dc']}/part-0.parquet", b"rows")
    s3.put("src-bucket", f"{ids['table_dc']}/_delta_log/00000.json", b"{}")
    s3.put("src-bucket", f"{ids['mqc_dc']}/abc/multiqc.parquet", b"mqc")
    payload = _export_zip((src_db, ids, s3), monkeypatch)
    target = configure_target(monkeypatch, target_db, s3, **source_opts)
    return SimpleNamespace(
        ids=ids, s3=s3, payload=payload, source=target.source, db=target_db, src_db=src_db
    )
