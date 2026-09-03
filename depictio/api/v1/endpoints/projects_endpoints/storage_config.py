"""Per-project storage configuration (RFC remote-data §5.3, roadmap issue 383).

Owners can attach S3-compatible credentials to a project so its remote/manifest
data collections read private buckets. Credentials live in their own
``project_storage_configs`` collection (never on the ``Project`` document),
which keeps them out of ``ProjectResponse`` (``extra="allow"``) and away from
the ``.mongo()``/``SecretStr`` serialization traps. The secret is encrypted at
rest (Fernet; key in ``settings.auth.keys_dir``, i.e. ``DEPICTIO_AUTH_KEYS_DIR``,
next to the JWT keypair, see ``depictio.api.v1.crypto``) and is write-only
through the API: responses only ever carry ``has_secret``.

The read side is ``storage_options_for_project``, a polars/boto-shaped
``storage_options`` dict threaded into the *remote read* path of url/manifest
ingestion. The instance's own MinIO config stays the Delta *write* target;
these are genuinely two different credentials.

Read-side contract: ``None`` means "no config stored, use the instance
credentials". A config that exists but cannot be used raises a
``ProjectStorageUnusable`` subclass instead of degrading to ``None``, because
silently reading a private bucket with the wrong credentials is exactly the
failure the feature exists to avoid.
"""

from datetime import datetime
from urllib.parse import urlparse

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import (
    ensure_project_storage_indexes,
    project_storage_collection,
    projects_collection,
)
from depictio.api.v1.remote_fetch import RemoteURLRejected, validate_remote_url
from depictio.models.logging import logger


class ProjectStorageUnusable(RuntimeError):
    """A storage config is stored for the project but cannot be used for reads.

    ``detail`` is safe to return to API clients (``status_code`` says how);
    ``str(exc)`` adds operator context (filesystem paths) for logs and task
    ledgers.
    """

    status_code = 500

    def __init__(self, project_id: str | ObjectId, detail: str, operator_hint: str = ""):
        self.project_id = str(project_id)
        self.detail = detail
        super().__init__(f"{detail} {operator_hint}".strip())


class StorageSecretUnreadable(ProjectStorageUnusable):
    """The stored secret was encrypted with a key this process does not have.

    Either the keys directory was rotated or lost, or the process reading it
    (typically the Celery worker) does not share ``DEPICTIO_AUTH_KEYS_DIR``
    with the API that wrote it. A deployment fault, hence 500.
    """

    status_code = 500

    def __init__(self, project_id: str | ObjectId, keys_dir):
        self.keys_dir = str(keys_dir)
        super().__init__(
            project_id,
            detail=(
                f"The storage secret stored for project {project_id} cannot be decrypted "
                "with this instance's secrets key: the keys directory was rotated or lost, "
                "or the API and the Celery worker do not share it. Re-enter the secret in "
                "the project's storage settings, or restore the keys volume."
            ),
            operator_hint=(
                f"Secrets key: {self.keys_dir}/secrets_key.bin (settings.auth.keys_dir, "
                "DEPICTIO_AUTH_KEYS_DIR); backend and worker must mount the same directory."
            ),
        )


class StorageEndpointRejected(ProjectStorageUnusable):
    """The stored endpoint no longer passes the instance's host gating.

    The allow/deny lists can be tightened after a config was written; the
    stored endpoint is re-gated on every read so an older config cannot keep
    a now-forbidden host reachable. The stored resource conflicts with the
    current policy, hence 409.
    """

    status_code = 409

    def __init__(self, project_id: str | ObjectId, endpoint_url: str, reason: str):
        self.endpoint_url = endpoint_url
        super().__init__(
            project_id,
            detail=(
                f"The storage endpoint configured for project {project_id} "
                f"({endpoint_url}) is no longer allowed on this instance: {reason} "
                "Update the project's storage settings."
            ),
        )


class ProjectStorageConfigIn(BaseModel):
    """Body of PUT /projects/{project_id}/storage.

    ``secret_access_key`` is optional on update: omitted or null keeps the
    stored secret, so edits don't require retyping it.
    """

    endpoint_url: str
    bucket: str | None = None
    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None


class ProjectStorageConfigOut(BaseModel):
    endpoint_url: str
    bucket: str | None = None
    region: str = "us-east-1"
    access_key_id: str | None = None
    # The secret itself is never returned, only whether one is stored.
    has_secret: bool = False
    updated_at: str | None = None


class StorageTestResult(BaseModel):
    success: bool
    message: str


def _normalize_endpoint(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{parsed.scheme}://{host}:{port}"


def _storage_endpoint_rejection(endpoint_url: str) -> str | None:
    """Gate an S3 endpoint; return the rejection reason, or None when allowed.

    The instance's own MinIO endpoint is always allowed; anything else goes
    through the same host validation as remote data URLs (scheme allowlist,
    private-range rejection, ``DEPICTIO_REMOTE_URL_ALLOWLIST`` escape hatch):
    a project-supplied endpoint is the same SSRF surface. Shared by the write
    path (400) and the read path (``StorageEndpointRejected``) so both apply
    the gating in force *now*.
    """
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "endpoint_url must be an http(s) URL, e.g. https://s3.example.org"
    try:
        if _normalize_endpoint(endpoint_url) == _normalize_endpoint(settings.minio.endpoint_url):
            return None
    except Exception:  # own-endpoint comparison is best-effort
        pass
    try:
        validate_remote_url(endpoint_url)
    except RemoteURLRejected as exc:
        return str(exc)
    return None


def _validate_storage_endpoint(endpoint_url: str) -> None:
    reason = _storage_endpoint_rejection(endpoint_url)
    if reason:
        raise HTTPException(status_code=400, detail=reason)


def _project_oid(project_id: str | ObjectId) -> ObjectId:
    try:
        return ObjectId(str(project_id))
    except InvalidId as exc:
        raise ValueError(f"Invalid project_id: {project_id!r}") from exc


def _load_project_for_owner(project_id: str, current_user) -> dict:
    try:
        project_oid = _project_oid(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    project_dict = projects_collection.find_one({"_id": project_oid})
    if not project_dict:
        raise HTTPException(status_code=404, detail="Project not found.")
    if not _user_owns_project(project_dict, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only project owners can manage storage credentials.",
        )
    return project_dict


def _user_owns_project(project_dict: dict, current_user) -> bool:
    """Storage credentials are owner-only, stricter than the editor gate."""
    if getattr(current_user, "is_admin", False):
        return True
    owners = (project_dict.get("permissions") or {}).get("owners") or []
    user_id = str(current_user.id)
    return any(str(owner.get("_id") or owner.get("id") or "") == user_id for owner in owners)


def _set_project_storage(
    project_id: str, payload: ProjectStorageConfigIn, current_user
) -> ProjectStorageConfigOut:
    from depictio.api.v1.crypto import encrypt_secret

    project_dict = _load_project_for_owner(project_id, current_user)
    _validate_storage_endpoint(payload.endpoint_url)

    project_oid = project_dict["_id"]
    existing = project_storage_collection.find_one({"project_id": project_oid}) or {}

    if payload.secret_access_key:
        secret_encrypted: str | None = encrypt_secret(payload.secret_access_key)
    else:
        # Omitted/empty secret keeps whatever is stored: write-only semantics.
        secret_encrypted = existing.get("secret_encrypted")

    # Storage writes are rare and owner-driven; ensuring the unique index here
    # (idempotent) covers instances upgraded past the first boot, where the
    # db_init call never ran.
    ensure_project_storage_indexes(project_storage_collection)

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    project_storage_collection.update_one(
        {"project_id": project_oid},
        {
            "$set": {
                "endpoint_url": payload.endpoint_url,
                "bucket": payload.bucket,
                "region": payload.region,
                "access_key_id": payload.access_key_id,
                "secret_encrypted": secret_encrypted,
                "updated_at": updated_at,
            }
        },
        upsert=True,
    )
    return ProjectStorageConfigOut(
        endpoint_url=payload.endpoint_url,
        bucket=payload.bucket,
        region=payload.region,
        access_key_id=payload.access_key_id,
        has_secret=bool(secret_encrypted),
        updated_at=updated_at,
    )


def _get_project_storage(project_id: str, current_user) -> ProjectStorageConfigOut:
    project_dict = _load_project_for_owner(project_id, current_user)
    doc = project_storage_collection.find_one({"project_id": project_dict["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="No storage configured for this project.")
    return ProjectStorageConfigOut(
        endpoint_url=doc.get("endpoint_url", ""),
        bucket=doc.get("bucket"),
        region=doc.get("region") or "us-east-1",
        access_key_id=doc.get("access_key_id"),
        has_secret=bool(doc.get("secret_encrypted")),
        updated_at=doc.get("updated_at"),
    )


def _delete_project_storage(project_id: str, current_user) -> dict:
    project_dict = _load_project_for_owner(project_id, current_user)
    project_storage_collection.delete_one({"project_id": project_dict["_id"]})
    return {"deleted": True}


def storage_options_for_project(project_id: str | ObjectId) -> dict | None:
    """Polars/boto-shaped storage options for a project's remote reads.

    Returns ``None`` when the project has no storage config: callers fall back
    to the instance credentials. Raises:

    * ``ValueError`` for a malformed ``project_id``;
    * ``StorageEndpointRejected`` when the stored endpoint fails the host
      gating currently in force (re-checked on every read);
    * ``StorageSecretUnreadable`` when the stored secret cannot be decrypted
      with this process's secrets key.

    None of these fall back to the instance credentials: a private bucket read
    with the wrong key fails loudly downstream or, worse, reads the wrong data.
    """
    project_oid = _project_oid(project_id)
    doc = project_storage_collection.find_one({"project_id": project_oid})
    if not doc:
        return None

    endpoint_url = doc.get("endpoint_url", "")
    reason = _storage_endpoint_rejection(endpoint_url)
    if reason:
        logger.error(f"Storage endpoint for project {project_oid} rejected at read time: {reason}")
        raise StorageEndpointRejected(project_oid, endpoint_url, reason)

    secret = ""
    if doc.get("secret_encrypted"):
        from depictio.api.v1.crypto import InvalidToken, decrypt_secret

        try:
            secret = decrypt_secret(doc["secret_encrypted"])
        except InvalidToken:
            exc = StorageSecretUnreadable(project_oid, settings.auth.keys_dir)
            logger.error(str(exc))
            raise exc from None

    is_https = endpoint_url.startswith("https://")
    return {
        "endpoint_url": endpoint_url,
        "aws_access_key_id": doc.get("access_key_id") or "",
        "aws_secret_access_key": secret,
        "region": doc.get("region") or "us-east-1",
        "use_ssl": "true" if is_https else "false",
        "AWS_ALLOW_HTTP": "false" if is_https else "true",
        "signature_version": "s3v4",
    }


def _test_project_storage(project_id: str, current_user) -> StorageTestResult:
    """Probe the configured endpoint/bucket with the stored credentials.

    Connection failures come back as ``success: false`` with a sanitized
    message, never a 5xx (the whole point is diagnosing bad credentials).
    """
    project_dict = _load_project_for_owner(project_id, current_user)
    doc = project_storage_collection.find_one({"project_id": project_dict["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="No storage configured for this project.")

    try:
        options = storage_options_for_project(project_dict["_id"])
    except ProjectStorageUnusable as exc:
        return StorageTestResult(success=False, message=exc.detail)
    if options is None:  # deleted between the two reads
        raise HTTPException(status_code=404, detail="No storage configured for this project.")

    import boto3

    try:
        client = boto3.client(
            "s3",
            endpoint_url=options["endpoint_url"],
            aws_access_key_id=options["aws_access_key_id"],
            aws_secret_access_key=options["aws_secret_access_key"],
            region_name=options["region"],
        )
        bucket = doc.get("bucket")
        if bucket:
            client.list_objects_v2(Bucket=bucket, MaxKeys=1)
            return StorageTestResult(success=True, message=f"Bucket '{bucket}' is reachable.")
        client.list_buckets()
        return StorageTestResult(success=True, message="Endpoint is reachable.")
    except Exception as exc:
        # Sanitize: boto errors can embed request ids/hosts but not secrets.
        message = str(exc).split("\n")[0][:300]
        logger.info(f"Storage test failed for project {project_dict['_id']}: {message}")
        return StorageTestResult(success=False, message=message)
