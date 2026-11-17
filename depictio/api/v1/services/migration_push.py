"""Build a project bundle and push it to a paired instance (#1303).

``build_project_bundle_file`` is the one place a bundle is made: the
``/migrate/export-project`` download and the server-to-server push both call
it, so they cannot drift apart. ``run_push`` is the background job behind
``POST /migrate/push``.

The migrate routes module holds the S3 helpers (and the tests patch them
there), so they are looked up on it at call time, not imported: importing it
at module level would be circular.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from bson import ObjectId

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.projects_endpoints.provenance import instance_label
from depictio.api.v1.services import project_bundle
from depictio.models.models.migration import TransferMode
from depictio.models.timestamps import TIMESTAMP_FORMAT, utc_now, utc_now_str
from depictio.version import get_version


class BundleListingError(Exception):
    """The project's S3 objects could not be listed."""


@dataclass
class BuiltBundle:
    path: str
    sha256: str
    size: int
    metadata: dict[str, Any]
    s3_object_count: int = 0
    s3_bytes: int = 0
    manifest: list[dict[str, Any]] = field(default_factory=list)


def _routes():
    from depictio.api.v1.endpoints.migrate_endpoints import routes

    return routes


def list_project_objects(scope: project_bundle.ProjectScope) -> tuple[list[str], list[Any]]:
    """The S3 paths of a project and every object under them."""
    routes = _routes()
    paths = routes._collect_s3_locations_for_project(scope.dc_ids, settings.s3.bucket)
    if not paths:
        return paths, []
    try:
        objects = project_bundle.list_s3_objects(
            paths, settings.s3.bucket, routes._instance_s3_client()
        )
    except (ClientError, BotoCoreError) as exc:
        logger.error("migrate: listing S3 failed: %s", exc)
        raise BundleListingError("Could not list the project's data") from exc
    return paths, objects


def _sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _public_url() -> str | None:
    """This instance's public viewer URL, for the receiving admin to read."""
    return str(getattr(settings.viewer, "external_url", "") or "").rstrip("/") or None


def build_project_bundle_file(
    project: dict[str, Any],
    *,
    mode: str = "all",
    include_data: bool = True,
    transfer_mode: TransferMode = "inline",
    dry_run: bool = False,
    target_s3_config: dict | None = None,
) -> BuiltBundle:
    """Write the project's bundle ZIP to a temp file and describe it.

    ``inline`` carries the objects in ``s3_data/``. ``server_side_copy`` carries
    only a manifest (key, size, etag): the target copies from the shared S3.
    ``target_s3_config`` is the CLI's direct S3-to-S3 copy (``export_project``
    only). Raises ``project_bundle.BundleTooLarge`` and ``BundleListingError``;
    the caller owns the returned file and must delete it.
    """
    routes = _routes()
    scope = project_bundle.resolve_project_scope(project)
    data = project_bundle.collect_bundle_docs(project, scope, mode)  # type: ignore[arg-type]
    logger.info(
        "migrate export: project=%s workflow_ids=%d dc_ids=%d",
        str(scope.project_id),
        len(scope.workflow_ids),
        len(scope.dc_ids),
    )

    bucket = settings.s3.bucket
    s3_metadata: dict[str, Any] = {}
    s3_objects: list[project_bundle.S3ObjectRef] = []
    s3_client: Any = None
    listed: list[project_bundle.S3ObjectRef] = []
    if include_data and mode in ("all", "files"):
        s3_paths = routes._collect_s3_locations_for_project(scope.dc_ids, bucket)
        logger.info("Migrate: found %d S3 locations for project", len(s3_paths))

        if target_s3_config:
            # SSRF / exfiltration guard before any boto3 client is built.
            routes._validate_target_s3_endpoint(target_s3_config)
            source_config = {
                "bucket": bucket,
                "endpoint_url": settings.s3.endpoint_url,
                "aws_access_key_id": settings.s3.aws_access_key_id,
                "aws_secret_access_key": settings.s3.aws_secret_access_key,
                "region_name": "us-east-1",
            }
            logger.info("Migrate: copying %d S3 locations to target", len(s3_paths))
            s3_metadata = routes._copy_s3_locations(
                s3_paths, source_config, target_s3_config, dry_run=dry_run
            )
            s3_metadata["paths"] = s3_paths
        elif transfer_mode == "server_side_copy":
            if s3_paths and not dry_run:
                try:
                    listed = project_bundle.list_s3_objects(
                        s3_paths, bucket, routes._instance_s3_client()
                    )
                except (ClientError, BotoCoreError) as exc:
                    logger.error("migrate export: listing S3 failed: %s", exc)
                    raise BundleListingError("Could not list the project's data") from exc
            s3_metadata = {
                "paths": s3_paths,
                "transfer_mode": "server_side_copy",
                "source_bucket": bucket,
                "manifest": [{"key": o.key, "size": o.size, "etag": o.etag} for o in listed],
            }
        else:
            # Objects are bundled directly into the ZIP below.
            s3_metadata = {"paths": s3_paths, "bundled_in_zip": True, "dry_run": dry_run}
            if s3_paths and not dry_run:
                s3_client = routes._instance_s3_client()
                try:
                    s3_objects = project_bundle.list_s3_objects(s3_paths, bucket, s3_client)
                except (ClientError, BotoCoreError) as exc:
                    logger.error("migrate export: listing S3 failed: %s", exc)
                    raise BundleListingError("Could not list the project's data") from exc
            listed = s3_objects

    metadata = project_bundle.build_bundle_metadata(
        project,
        scope,
        mode,  # type: ignore[arg-type]
        data,
        dry_run=dry_run,
        source_instance=instance_label(),
        depictio_version=get_version(),
        s3_bucket=bucket,
        s3_endpoint=routes._normalize_endpoint(settings.s3.endpoint_url or ""),
        exported_at=utc_now_str(),
        source_url=_public_url(),
    )

    spool_dir = routes._migration_setting("spool_dir", None)
    if spool_dir:
        os.makedirs(spool_dir, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="depictio-export-", suffix=".zip", dir=spool_dir)
    try:
        with os.fdopen(fd, "wb") as fp:
            written = project_bundle.write_bundle_zip(
                fp,
                metadata,
                data,
                s3_metadata=s3_metadata,
                s3_objects=s3_objects,
                s3_client=s3_client,
                bucket=bucket,
                max_bytes=int(
                    routes._migration_setting("max_bundle_bytes", routes.DEFAULT_MAX_BUNDLE_BYTES)
                ),
            )
        sha256 = _sha256_of(path)
        size = os.path.getsize(path)
    except BaseException:
        os.unlink(path)
        raise
    if s3_objects:
        logger.info("Migrate: bundled %s S3 files into ZIP", written.get("bundled_files"))
    return BuiltBundle(
        path=path,
        sha256=sha256,
        size=size,
        metadata=metadata,
        s3_object_count=len(listed),
        s3_bytes=sum(o.size for o in listed),
        manifest=[{"key": o.key, "size": o.size, "etag": o.etag} for o in listed],
    )


# ---------------------------------------------------------------------------
# Background push job
# ---------------------------------------------------------------------------


INTERRUPTED = "interrupted by a restart"


def _set_push(push_id: ObjectId, **fields: Any) -> None:
    from depictio.api.v1.db import migration_pushes_collection

    fields["updated_at"] = utc_now_str()
    if fields.get("status") in ("submitted", "failed"):
        fields["in_flight"] = False
    migration_pushes_collection.update_one({"_id": push_id}, {"$set": fields})


def recover_interrupted_pushes(now: Any = None) -> int:
    """Pushes left ``building``/``uploading`` by a restart become ``failed``.

    Run at API startup: the job lived in the process that died. Only pushes
    whose last update is older than ``interrupted_after_minutes`` are touched,
    so another replica's running push is left alone.
    """
    from depictio.api.v1.db import migration_pushes_collection

    now = now or utc_now()
    cutoff = (now - timedelta(minutes=settings.migration.interrupted_after_minutes)).strftime(
        TIMESTAMP_FORMAT
    )
    result = migration_pushes_collection.update_many(
        {"status": {"$in": ["building", "uploading"]}, "updated_at": {"$lt": cutoff}},
        {
            "$set": {
                "status": "failed",
                "error": INTERRUPTED,
                "in_flight": False,
                "updated_at": utc_now_str(),
            }
        },
    )
    if result.modified_count:
        logger.warning("migrate: %d push(es) %s", result.modified_count, INTERRUPTED)
    return int(result.modified_count)


def _push_target(push: dict[str, Any], credential: str | None) -> Any:
    from depictio.api.v1.endpoints.migrate_endpoints.push_routes import ADHOC, adhoc_target
    from depictio.api.v1.endpoints.migrate_endpoints.targets_routes import resolve_target

    if push.get("target_id") == ADHOC:
        if not credential or not push.get("target_url"):
            raise RuntimeError("The invite code is no longer available; retry the push")
        return adhoc_target(push["target_url"], credential)
    return resolve_target(push["target_id"])


def run_push(push_id: str, credential: str | None = None) -> None:
    """Build the bundle, send it to the target, record the outcome.

    Runs in the FastAPI background thread pool. ``credential`` is the invite
    code of an ad-hoc destination, held in memory only. Every failure ends as
    ``status: failed`` with a short message (never a key or code), and the
    temp bundle is always removed.
    """
    from fastapi import HTTPException

    from depictio.api.v1.crypto import encrypt_secret
    from depictio.api.v1.db import migration_pushes_collection, projects_collection
    from depictio.api.v1.services.outbound_http import RemoteError, TargetClient

    oid = ObjectId(push_id)
    push = migration_pushes_collection.find_one({"_id": oid})
    if not push:
        logger.error("migrate push: %s vanished before it ran", push_id)
        return
    path: str | None = None
    try:
        project = projects_collection.find_one({"_id": ObjectId(push["project_id"])})
        if not project:
            raise RuntimeError("Project no longer exists")
        target = _push_target(push, credential)
        built = build_project_bundle_file(
            project, mode="all", transfer_mode=push.get("transfer_mode", "inline")
        )
        path = built.path
        _set_push(oid, status="uploading", bundle_bytes=built.size, bundle_sha256=built.sha256)
        with TargetClient(target) as client:
            answer = client.submit(
                path,
                {
                    "sha256": built.sha256,
                    "transfer_mode": push.get("transfer_mode", "inline"),
                    "requester_email": push.get("requested_by_email"),
                    "requester_name": push.get("requested_by_name")
                    or (push.get("requested_by_email") or "").split("@")[0]
                    or None,
                    "source_user_id": push.get("requested_by_id"),
                    "message": push.get("message"),
                },
            )
        extra: dict[str, Any] = {}
        if answer.get("status_token"):
            # Reads this one request's status, nothing else; sealed like a key.
            extra["status_token_enc"] = encrypt_secret(str(answer["status_token"]))
        _set_push(
            oid,
            status="submitted",
            remote_request_id=str(answer.get("request_id")),
            remote_status=answer.get("status"),
            error=None,
            **extra,
        )
    except RemoteError as exc:
        logger.warning("migrate push %s failed: %s", push_id, exc)
        _set_push(oid, status="failed", error=f"Target refused ({exc.status_code}): {exc.detail}")
    except project_bundle.BundleTooLarge as exc:
        _set_push(oid, status="failed", error=str(exc))
    except HTTPException as exc:  # an ad-hoc destination no longer allowed
        _set_push(oid, status="failed", error=str(exc.detail))
    except Exception as exc:  # noqa: BLE001 - recorded, not raised: nobody awaits a background job
        logger.exception("migrate push %s failed", push_id)
        _set_push(oid, status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
    finally:
        if path and os.path.exists(path):
            os.unlink(path)
