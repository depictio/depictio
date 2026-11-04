"""Target side of a server-to-server push: validate a staged bundle and import it (#1303).

An inbound request parks its bundle in S3 (``staging_prefix``) until an admin
decides. Approval hands the request to :func:`run_migration_import`, a plain
synchronous function run by FastAPI ``BackgroundTasks`` (thread pool). It
records its own outcome in the request document, so a client polls state rather
than holding a connection open.

The order matters and is the whole safety argument: data first, documents last.
A request whose data cannot be written never touches Mongo, so a failed import
leaves no project that lists collections it cannot read.
"""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from bson import ObjectId

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.configs.settings_models import MigrationInboundSource
from depictio.api.v1.services import project_bundle
from depictio.models.models.migration import ImportHop, MigrationResult, PublishedLock
from depictio.models.timestamps import TIMESTAMP_FORMAT, utc_now, utc_now_str
from depictio.version import get_version

_CHUNK = 1024 * 1024


def _db():
    """The live collections, imported late so tests can patch this one place."""
    from depictio.api.v1 import db

    return db


class ImportFailed(Exception):
    """A request that cannot be imported; the message is shown to the admin."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def staging_object_key(request_id: str) -> str:
    """Where a request's bundle waits: one object per request under the staging prefix."""
    return f"{settings.migration.staging_prefix}/{request_id}/bundle.zip"


def staging_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def parse_staging_uri(uri: str | None) -> tuple[str, str] | None:
    """(bucket, key) of a stored ``staging_key``, or None when it is not one."""
    if not uri or not uri.startswith("s3://"):
        return None
    parts = urlsplit(uri)
    key = parts.path.lstrip("/")
    return (parts.netloc, key) if parts.netloc and key else None


def _s3_client() -> Any:
    from depictio.api.v1.endpoints.migrate_endpoints import routes

    return routes._instance_s3_client()


def delete_staged_bundle(request_doc: dict[str, Any], client: Any = None) -> None:
    """Remove a request's staged bundle. Best effort: a leftover is swept by expiry."""
    parsed = parse_staging_uri(request_doc.get("staging_key"))
    if parsed is None:
        return
    bucket, key = parsed
    # Never delete outside the staging prefix, whatever the document says.
    if not key.startswith(f"{settings.migration.staging_prefix}/"):
        logger.warning("migration: refusing to delete %s outside the staging prefix", key)
        return
    try:
        (client or _s3_client()).delete_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001 — a missing object is not worth failing a decision
        logger.warning("migration: could not delete staged bundle %s: %s", key, exc)


def source_by_name(name: str | None) -> MigrationInboundSource | None:
    for source in settings.migration.inbound_sources:
        if source.name == name:
            return source
    return None


def find_user_by_email(email: str | None) -> dict[str, Any] | None:
    """The account with this email, case-insensitively (emails differ in case across IdPs)."""
    if not email or not email.strip():
        return None
    return _db().users_collection.find_one(
        {"email": {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}}
    )


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _manifest_sort_key(ref: project_bundle.S3ObjectRef) -> tuple[bool, str]:
    """``_delta_log`` last, the rule ``list_s3_objects`` uses for the same reason."""
    return ("/_delta_log/" in f"/{ref.key}", ref.key)


def hash_and_size(fileobj: Any) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    fileobj.seek(0)
    for chunk in iter(lambda: fileobj.read(_CHUNK), b""):
        digest.update(chunk)
        size += len(chunk)
    fileobj.seek(0)
    return digest.hexdigest(), size


# ---------------------------------------------------------------------------
# Validation shared by upload, revalidate and the import job
# ---------------------------------------------------------------------------


def validate_opened_bundle(
    opened: project_bundle.OpenedBundle,
    *,
    source_name: str,
    transfer_mode: str,
) -> project_bundle.BundleReport:
    """Strict validation of an opened push bundle, including its transfer mode.

    A ``server_side_copy`` bundle holds a manifest instead of data; its objects
    come from a bucket on this instance's own S3 endpoint, so that bucket must
    be one the source is allowed to read from (and not this instance's own).
    """
    if transfer_mode == "server_side_copy":
        manifest = project_bundle.manifest_from_s3_metadata(opened.s3_metadata)
        keys = [ref.key for ref in manifest]
    else:
        manifest = []
        keys = [key for _, key in opened.s3_entries]
    report = project_bundle.validate_bundle(
        opened.metadata, opened.data, keys, strict=True, source_instance=source_name
    )
    if not report.project_id and not report.errors:
        report.errors.append("a pushed bundle must contain exactly one project")
    if transfer_mode == "server_side_copy":
        source = source_by_name(source_name)
        bucket = project_bundle._source_bucket(opened.metadata, opened.data)
        allowed = list(source.allowed_source_buckets) if source else []
        if not bucket or bucket not in allowed or bucket == settings.s3.bucket:
            report.errors.append(
                f"source bucket {bucket!r} is not one this source may copy from on this instance"
            )
        if any(not ref.etag for ref in manifest):
            report.errors.append("the manifest has objects without an etag")
        if opened.s3_entries:
            report.warnings.append("bundle carries data files that a server-side copy ignores")
        report.s3_bytes = sum(ref.size for ref in manifest)
    else:
        report.s3_bytes = opened.total_s3_bytes
    return report


def bundle_dc_ids(opened: project_bundle.OpenedBundle) -> list[str]:
    """Data collection ids of the bundled project (what the orphan sweep must spare)."""
    projects = opened.data.get("projects") or []
    if len(projects) != 1:
        return []
    try:
        return sorted(project_bundle.resolve_project_scope(projects[0]).dc_id_strs)
    except ValueError:
        return []


# ---------------------------------------------------------------------------
# The import job
# ---------------------------------------------------------------------------


def _set_request(request_id: ObjectId, **fields: Any) -> None:
    fields["updated_at"] = utc_now_str()
    _db().migration_requests_collection.update_one({"_id": request_id}, {"$set": fields})


def _fail(request_id: ObjectId, request_doc: dict[str, Any], message: str) -> None:
    logger.error("migration import %s failed: %s", request_id, message)
    result = MigrationResult(error=message).model_dump()
    _set_request(request_id, status="failed", result=result)
    delete_staged_bundle(request_doc)


def _download_staged(request_doc: dict[str, Any], spool: Any, client: Any) -> None:
    parsed = parse_staging_uri(request_doc.get("staging_key"))
    if parsed is None:
        raise ImportFailed("the request has no staged bundle")
    bucket, key = parsed
    try:
        body = client.get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as exc:  # noqa: BLE001
        raise ImportFailed(f"could not read the staged bundle: {exc}") from exc
    for chunk in iter(lambda: body.read(_CHUNK), b""):
        spool.write(chunk)
    spool.flush()
    spool.seek(0)


def _copy_server_side(
    manifest: list[project_bundle.S3ObjectRef], source_bucket: str, client: Any
) -> int:
    """CopyObject every manifest entry from the source bucket, ``_delta_log`` last.

    ``CopySourceIfMatch`` pins each object to the etag the source recorded, so
    an object rewritten since the bundle was built fails the copy instead of
    silently importing different data.
    """
    target_bucket = settings.s3.bucket
    copied = 0
    for ref in sorted(manifest, key=_manifest_sort_key):
        try:
            client.copy_object(
                Bucket=target_bucket,
                Key=ref.key,
                CopySource={"Bucket": source_bucket, "Key": ref.key},
                CopySourceIfMatch=ref.etag,
            )
        except Exception as exc:  # noqa: BLE001 — ClientError (412, 403, 404) or transport
            raise ImportFailed(f"copying {ref.key} from {source_bucket} failed: {exc}") from exc
        copied += 1
    return copied


def _import(
    request_id: ObjectId, request_doc: dict[str, Any], approver: Any, lock: bool, make_public: bool
) -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import (
        cascade_project_visibility,
    )

    db = _db()
    client = _s3_client()
    source_name = request_doc["source_name"]
    transfer_mode = request_doc.get("transfer_mode", "inline")

    with project_bundle.spool_file(settings.migration.spool_dir) as spool:
        _download_staged(request_doc, spool, client)
        sha, _ = hash_and_size(spool)
        if request_doc.get("bundle_sha256") and sha != request_doc["bundle_sha256"]:
            raise ImportFailed("the staged bundle does not match the checksum it was uploaded with")
        try:
            opened = project_bundle.open_bundle_zip(spool)
        except project_bundle.BundleError as exc:
            raise ImportFailed(f"the staged bundle cannot be read: {exc}") from exc
        try:
            report = validate_opened_bundle(
                opened, source_name=source_name, transfer_mode=transfer_mode
            )
            _set_request(request_id, report=report.model_dump())
            if report.errors:
                raise ImportFailed("bundle no longer validates: " + "; ".join(report.errors[:5]))

            # Owner: the requester when they have an account here, else the
            # approving admin until the requester's email signs in.
            requester_email = (request_doc.get("requester") or {}).get("email")
            requester = find_user_by_email(requester_email)
            approver_id = ObjectId(str(_get(approver, "id")))
            owner_id = requester["_id"] if requester else approver_id
            pending_owner_email = (
                None if requester or not requester_email else requester_email.strip().lower()
            )

            # Data first, documents last (see module docstring).
            if transfer_mode == "server_side_copy":
                source_bucket = project_bundle._source_bucket(opened.metadata, opened.data)
                manifest = project_bundle.manifest_from_s3_metadata(opened.s3_metadata)
                s3_objects = _copy_server_side(manifest, str(source_bucket), client)
            else:
                s3_objects, failures = (0, [])
                if opened.s3_entries:
                    s3_objects, failures = project_bundle.restore_s3_entries(
                        opened, client, settings.s3.bucket
                    )
                if failures:
                    raise ImportFailed(
                        f"only {s3_objects} of {len(opened.s3_entries)} data files could be "
                        f"written to object storage; first error: {failures[0]}"
                    )

            existing = (
                db.projects_collection.find_one({"_id": ObjectId(report.project_id)})
                if report.project_id
                else None
            )
            hop = ImportHop(
                source_instance=source_name,
                source_depictio_version=opened.metadata.get("depictio_version"),
                bundle_format_version=report.bundle_format_version,
                exported_at=opened.metadata.get("exported_at") or opened.metadata.get("timestamp"),
                target_depictio_version=get_version(),
                bundle_sha256=sha,
                migration_request_id=str(request_id),
                via="push",
            )
            prepared = project_bundle.prepare_docs_for_import(
                opened.data,
                owner_id=owner_id,
                owner_email=requester["email"] if requester else _get(approver, "email"),
                existing_user_ids={str(u["_id"]) for u in db.users_collection.find({}, {"_id": 1})},
                force_remap=True,
                strip_shares=True,
                source_bucket=project_bundle._source_bucket(opened.metadata, opened.data),
                target_bucket=settings.s3.bucket,
                hop=hop,
                existing_project=existing,
                # A push never decides visibility: the admin's make_public does.
                keep_bundle_visibility=False,
            )
            label = f"Migrated from {source_name}"
            if hop.source_depictio_version:
                label += f" (Depictio {hop.source_depictio_version})"
            actor = SimpleNamespace(id=str(approver_id), email=_get(approver, "email"))
            try:
                written = project_bundle.apply_project_import(
                    prepared,
                    actor=actor,
                    label=label,
                    existing_project=existing,
                    invalidate=project_bundle.default_invalidate,
                )
            except project_bundle.ImportWriteError as exc:
                raise ImportFailed(f"writing {exc.collection} failed: {exc}") from exc

            # Server-owned state the bundle can never carry.
            pid = prepared.project_id
            updates: dict[str, Any] = {}
            unsets: dict[str, Any] = {}
            if lock:
                updates["published_lock"] = PublishedLock(
                    locked_by_id=str(approver_id),
                    locked_by_email=_get(approver, "email"),
                    source="migration",
                    migration_request_id=str(request_id),
                    dashboard_ids=prepared.dashboard_ids,
                ).model_dump()
            else:
                unsets["published_lock"] = ""
            if pending_owner_email:
                updates["pending_owner_email"] = pending_owner_email
            else:
                unsets["pending_owner_email"] = ""
            if make_public:
                updates["is_public"] = True
                updates["last_modified"] = utc_now_str()
            op: dict[str, Any] = {}
            if updates:
                op["$set"] = updates
            if unsets:
                op["$unset"] = unsets
            db.projects_collection.update_one({"_id": pid}, op)
            if make_public:
                cascade_project_visibility(str(pid), True)

            result = MigrationResult(
                project_id=str(pid),
                owner_id=str(owner_id),
                pending_owner_email=pending_owner_email,
                locked=bool(lock),
                made_public=bool(make_public),
                documents={k: v for k, v in written.items() if isinstance(v, int)},
                s3_objects=s3_objects,
            )
        finally:
            opened.close()

    delete_staged_bundle(request_doc, client)
    _set_request(request_id, status="imported", result=result.model_dump())
    logger.info("migration import %s: project %s imported from %s", request_id, pid, source_name)


def run_migration_import(request_id: str, approver: Any, lock: bool, make_public: bool) -> None:
    """Import an approved request. Never raises: the outcome is the request's status.

    The approve route has already moved the request from ``pending`` to
    ``importing`` atomically, which is what keeps two approvals from running
    the same import twice.
    """
    try:
        oid = ObjectId(str(request_id))
        doc = _db().migration_requests_collection.find_one({"_id": oid})
    except Exception as exc:  # noqa: BLE001
        logger.error("migration import: cannot load request %s: %s", request_id, exc)
        return
    if not doc or doc.get("status") != "importing":
        logger.warning("migration import: request %s is not importing, skipping", request_id)
        return
    try:
        _import(oid, doc, approver, lock, make_public)
    except ImportFailed as exc:
        _fail(oid, doc, str(exc))
    except Exception as exc:  # noqa: BLE001 — the status must never stay "importing"
        logger.exception("migration import %s crashed", request_id)
        _fail(oid, doc, f"unexpected error: {exc}")


def expire_stale_requests(now: Any = None) -> int:
    """Expire pending requests older than ``pending_ttl_days`` and drop their bundles.

    Each request is claimed with an atomic status change, so several workers
    running the same sweep expire (and delete) it once.
    """
    now = now or utc_now()
    cutoff = (now - timedelta(days=settings.migration.pending_ttl_days)).strftime(TIMESTAMP_FORMAT)
    col = _db().migration_requests_collection
    expired = 0
    for doc in list(col.find({"status": "pending", "created_at": {"$lt": cutoff}})):
        claimed = col.find_one_and_update(
            {"_id": doc["_id"], "status": "pending"},
            {"$set": {"status": "expired", "updated_at": utc_now_str()}},
        )
        if claimed is None:
            continue
        delete_staged_bundle(claimed)
        expired += 1
    if expired:
        logger.info("migration: expired %d stale request(s)", expired)
    return expired


def revalidate_request(request_doc: dict[str, Any]) -> project_bundle.BundleReport:
    """Validate a request's staged bundle against this instance as it is now.

    The report stored at upload goes stale: another project may have taken the
    name since, or the lineage changed. Raises :class:`ImportFailed` when the
    staged bundle cannot be read at all.
    """
    with project_bundle.spool_file(settings.migration.spool_dir) as spool:
        _download_staged(request_doc, spool, _s3_client())
        try:
            opened = project_bundle.open_bundle_zip(spool)
        except project_bundle.BundleError as exc:
            raise ImportFailed(f"the staged bundle cannot be read: {exc}") from exc
        try:
            return validate_opened_bundle(
                opened,
                source_name=request_doc["source_name"],
                transfer_mode=request_doc.get("transfer_mode", "inline"),
            )
        finally:
            opened.close()
