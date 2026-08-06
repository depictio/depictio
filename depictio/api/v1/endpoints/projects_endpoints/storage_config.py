"""Per-project storage configuration (RFC remote-data §5.3, roadmap issue 383).

Owners can attach S3-compatible credentials to a project so its remote/manifest
data collections read private buckets. Credentials live in their own
``project_storage_configs`` collection — never on the ``Project`` document —
which keeps them out of ``ProjectResponse`` (``extra="allow"``) and away from
the ``.mongo()``/``SecretStr`` serialization traps. The secret is encrypted at
rest (Fernet, key under ``DEPICTIO_KEYS_DIR``) and is write-only through the
API: responses only ever carry ``has_secret``.

The read side is ``storage_options_for_project`` — a polars/boto-shaped
``storage_options`` dict threaded into the *remote read* path of manifest
ingestion. The instance's own MinIO config stays the Delta *write* target;
these are genuinely two different credentials.
"""

from datetime import datetime
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import project_storage_collection, projects_collection
from depictio.api.v1.remote_fetch import RemoteURLRejected, validate_remote_url
from depictio.models.logging import logger


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
    # The secret itself is never returned — only whether one is stored.
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


def _validate_storage_endpoint(endpoint_url: str) -> None:
    """Gate a caller-supplied S3 endpoint.

    The instance's own MinIO endpoint is always allowed; anything else goes
    through the same host validation as remote data URLs (scheme allowlist,
    private-range rejection, `DEPICTIO_REMOTE_URL_ALLOWLIST` escape hatch) —
    a project-supplied endpoint is the same SSRF surface.
    """
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(
            status_code=400,
            detail="endpoint_url must be an http(s) URL, e.g. https://s3.example.org",
        )
    try:
        if _normalize_endpoint(endpoint_url) == _normalize_endpoint(settings.minio.endpoint_url):
            return
    except Exception:  # own-endpoint comparison is best-effort
        pass
    try:
        validate_remote_url(endpoint_url)
    except RemoteURLRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _load_project_for_owner(project_id: str, current_user) -> dict:
    try:
        project_oid = ObjectId(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid project_id: {exc}")
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
    """Storage credentials are owner-only — stricter than the editor gate."""
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
        # Omitted/empty secret keeps whatever is stored — write-only semantics.
        secret_encrypted = existing.get("secret_encrypted")

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

    Returns None when the project has no storage config — callers fall back to
    the instance credentials. Decryption failures (rotated/lost keys dir) are
    logged and treated as "no config" rather than failing the whole ingestion.
    """
    try:
        project_oid = ObjectId(str(project_id))
    except Exception:
        return None
    doc = project_storage_collection.find_one({"project_id": project_oid})
    if not doc:
        return None

    secret = ""
    if doc.get("secret_encrypted"):
        from depictio.api.v1.crypto import decrypt_secret

        try:
            secret = decrypt_secret(doc["secret_encrypted"])
        except Exception as exc:
            logger.error(
                f"Could not decrypt storage secret for project {project_oid}: {exc} — "
                "falling back to instance credentials."
            )
            return None

    endpoint_url = doc.get("endpoint_url", "")
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
    message — never a 5xx (the whole point is diagnosing bad credentials).
    """
    project_dict = _load_project_for_owner(project_id, current_user)
    doc = project_storage_collection.find_one({"project_id": project_dict["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="No storage configured for this project.")

    options = storage_options_for_project(project_dict["_id"])
    if options is None:
        return StorageTestResult(
            success=False, message="Stored secret could not be decrypted — re-enter it."
        )

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
