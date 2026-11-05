"""Shared fixtures for migration tests: a mongomock database wired into the
bundle service and the migrate routes, a fake S3 store, and a recorder for the
dashboard version captures an import makes."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

COLLECTIONS = {
    "projects_collection": "projects",
    "files_collection": "files",
    "deltatables_collection": "deltatables",
    "runs_collection": "runs",
    "dashboards_collection": "dashboards",
    "multiqc_collection": "multiqc",
    "jbrowse_collection": "jbrowse",
    "data_collections_collection": "data_collections",
    "users_collection": "users",
    "branding_assets_collection": "branding_assets",
    "comment_threads_collection": "comment_threads",
}


class FakeS3:
    """Just enough of a boto3 S3 client for bundle export/import."""

    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, bytes]] = {}

    def put(self, bucket: str, key: str, body: bytes) -> None:
        self.buckets.setdefault(bucket, {})[key] = body

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        store = self

        class _P:
            def paginate(self, Bucket: str, Prefix: str = ""):
                objs = store.buckets.get(Bucket, {})
                yield {
                    "Contents": [
                        {"Key": k, "Size": len(v), "ETag": f'"etag-{len(v)}-{k}"'}
                        for k, v in sorted(objs.items())
                        if k.startswith(Prefix)
                    ]
                }

        return _P()

    def get_object(self, Bucket: str, Key: str):
        return {"Body": io.BytesIO(self.buckets[Bucket][Key])}

    def upload_fileobj(self, fileobj, bucket: str, key: str, ExtraArgs: dict | None = None):
        self.put(bucket, key, fileobj.read())


def make_db():
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    return SimpleNamespace(**{attr: database[name] for attr, name in COLLECTIONS.items()})


@pytest.fixture
def captures(monkeypatch):
    """Every version capture an import asks for, as (family_id, kind, label)."""
    from depictio.api.v1.endpoints.dashboards_endpoints import versioning

    calls: list[tuple[str, str, str | None]] = []

    def fake(dashboard_id, **kwargs):
        calls.append((str(dashboard_id), kwargs.get("kind"), kwargs.get("label")))
        return None

    monkeypatch.setattr(versioning, "capture_quietly", fake)
    return calls


@pytest.fixture
def target_db():
    """The importing instance's database, wired into the service and routes."""
    from depictio.api.v1.endpoints.migrate_endpoints import routes
    from depictio.api.v1.services import project_bundle

    db = make_db()
    patches = [patch.object(project_bundle, "_db", lambda: db)]
    for attr in COLLECTIONS:
        if hasattr(routes, attr):
            patches.append(patch.object(routes, attr, getattr(db, attr)))
    for p in patches:
        p.start()
    yield db
    for p in reversed(patches):
        p.stop()


def seed_source_project(db, *, bucket: str = "src-bucket") -> dict[str, Any]:
    """A small project: one workflow, one table DC with a delta table, one
    MultiQC DC, a two-tab dashboard family, a run and a file record."""
    owner_id = ObjectId()
    pid, wf_id, table_dc, mqc_dc = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    main_dash, child_dash = ObjectId(), ObjectId()
    db.users_collection.insert_one({"_id": owner_id, "email": "author@source.org"})
    project = {
        "_id": pid,
        "name": "Iris published",
        "is_public": True,
        "registration_time": "2026-01-01 10:00:00",
        "permissions": {
            "owners": [{"_id": owner_id, "email": "author@source.org"}],
            "editors": [{"_id": ObjectId(), "email": "editor@source.org"}],
            "viewers": ["*"],
        },
        "provenance": {"created_with_version": "1.20.0", "imported_from": []},
        "workflows": [
            {
                "_id": wf_id,
                "name": "wf",
                "engine": {"name": "python"},
                "data_collections": [
                    {
                        "_id": table_dc,
                        "data_collection_tag": "iris",
                        "config": {
                            "type": "table",
                            "source": "joined",
                            "dc_specific_properties": {"format": "csv"},
                        },
                    },
                    {
                        "_id": mqc_dc,
                        "data_collection_tag": "mqc",
                        "config": {
                            "type": "multiqc",
                            "source": "joined",
                            "dc_specific_properties": {},
                        },
                    },
                ],
            }
        ],
    }
    db.projects_collection.insert_one(project)
    db.deltatables_collection.insert_one(
        {
            "_id": ObjectId(),
            "data_collection_id": table_dc,
            "delta_table_location": f"s3://{bucket}/{table_dc}",
            "aggregation": [
                {
                    "aggregation_time": __import__("datetime").datetime(2026, 1, 2, 3, 4, 5),
                    "aggregation_version": 1,
                }
            ],
        }
    )
    db.multiqc_collection.insert_one(
        {
            "_id": ObjectId(),
            "data_collection_id": str(mqc_dc),
            "s3_location": f"s3://{bucket}/{mqc_dc}/abc/multiqc.parquet",
        }
    )
    db.files_collection.insert_one(
        {"_id": ObjectId(), "data_collection_id": table_dc, "file_location": "/x"}
    )
    db.runs_collection.insert_one({"_id": ObjectId(), "workflow_id": wf_id, "run_tag": "r1"})
    db.dashboards_collection.insert_many(
        [
            {
                "_id": main_dash,
                "dashboard_id": main_dash,
                "project_id": pid,
                "title": "Main",
                "is_main_tab": True,
                "is_public": True,
                "permissions": project["permissions"],
                "stored_metadata": [{"index": "c1", "dc_id": table_dc}],
            },
            {
                "_id": child_dash,
                "dashboard_id": child_dash,
                "project_id": pid,
                "title": "Child",
                "is_main_tab": False,
                "parent_dashboard_id": main_dash,
                "permissions": project["permissions"],
            },
        ]
    )
    return {
        "project_id": pid,
        "workflow_id": wf_id,
        "table_dc": table_dc,
        "mqc_dc": mqc_dc,
        "main_dash": main_dash,
        "child_dash": child_dash,
        "owner_id": owner_id,
        "bucket": bucket,
    }
