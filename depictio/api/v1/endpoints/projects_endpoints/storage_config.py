"""Per-project storage configuration (RFC remote-data §5.3, roadmap issue 383).

Owners can attach S3-compatible credentials to a project so its remote/manifest
data collections read private buckets. Credentials live in their own
``project_storage_configs`` collection (never on the ``Project`` document),
which keeps them out of ``ProjectResponse`` (``extra="allow"``) and away from
the ``.mongo()``/``SecretStr`` serialization traps. The secret is encrypted at
rest (Fernet; key in ``settings.auth.keys_dir``, i.e. ``DEPICTIO_AUTH_KEYS_DIR``,
next to the JWT keypair, see ``depictio.api.v1.crypto``) and is write-only
through the API: responses only ever carry ``has_secret``.

The read side is ``project_storage_for``, a
:class:`~depictio.models.s3_access.ProjectS3Config` threaded into the *remote
read* path of url/manifest/s3_prefix ingestion, where
``depictio.models.s3_access`` builds the ``project`` read target from it and
from nothing else. The instance's own S3 config stays the Delta *write*
target; these are genuinely two different credentials.

Read-side contract: ``None`` means "no config stored": a server-side read is
then public or refused, never done with the instance credentials. A config
that exists but cannot be used raises a ``ProjectStorageUnusable`` subclass
instead of degrading to ``None``, because silently reading a private bucket
with the wrong credentials is exactly the failure the feature exists to avoid.
"""

from urllib.parse import urlparse

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import (
    ensure_project_storage_indexes,
    project_storage_collection,
    projects_collection,
)
from depictio.api.v1.remote_fetch import RemoteURLRejected, remote_policy, validate_remote_url
from depictio.models.logging import logger
from depictio.models.s3_access import (
    AWS_DEFAULT_REGION,
    ProjectS3Config,
    S3AccessFailed,
    S3AccessRefused,
    is_instance_bucket,
    probe_bucket,
    project_target,
)
from depictio.models.timestamps import utc_now_str


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

    ``bucket`` is required: the storage test probes that bucket and nothing
    else (an endpoint-wide ``list_buckets`` is denied by gateways that scope a
    key to one bucket). ``secret_access_key`` is optional on update: omitted
    or null keeps the stored secret, so edits don't require retyping it, as
    long as the access key ID, the endpoint and the bucket stay the ones it
    was saved with. An empty ``access_key_id`` means "read without
    credentials", and drops any stored secret.
    """

    endpoint_url: str
    bucket: str = Field(min_length=1)
    region: str = AWS_DEFAULT_REGION
    access_key_id: str | None = None
    secret_access_key: str | None = None

    @field_validator("bucket", mode="before")
    @classmethod
    def _strip_bucket(cls, value):
        return value.strip().strip("/") if isinstance(value, str) else value

    @field_validator("region", mode="before")
    @classmethod
    def _default_region(cls, value):
        return (value.strip() if isinstance(value, str) else value) or AWS_DEFAULT_REGION

    @model_validator(mode="after")
    def _secret_needs_a_key(self) -> "ProjectStorageConfigIn":
        if self.secret_access_key and not (self.access_key_id or "").strip():
            raise ValueError("A secret access key needs its access key ID.")
        return self


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
    # The region the bucket named in its ``x-amz-bucket-region`` header, when
    # it sent one (AWS does; the EMBL gateway and SeaweedFS do not). Written
    # back to the stored config when it differs from the configured one.
    detected_region: str | None = None


def _normalize_endpoint(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{parsed.scheme}://{host}:{port}"


def _instance_endpoints() -> set[str]:
    """The instance's own S3 endpoint, normalised, as this process reaches it.

    ``settings.s3.endpoint_url`` (the internal service URL in server context)
    and the configured public URL. A malformed one is a deployment problem,
    logged, and simply not exempted.
    """
    endpoints: set[str] = set()
    for candidate in (settings.s3.endpoint_url, settings.s3.public_url):
        if not candidate:
            continue
        try:
            endpoints.add(_normalize_endpoint(candidate))
        except ValueError as exc:
            logger.warning(f"Instance S3 endpoint is malformed, not exempted from gating: {exc}")
    return endpoints


def _storage_endpoint_rejection(endpoint_url: str) -> str | None:
    """Gate an S3 endpoint; return the rejection reason, or None when allowed.

    The instance's own S3 endpoint (``settings.s3``) is always allowed: the
    compose service ``http://s3:9000`` is a private address the host gating
    would otherwise reject. Reading through it still needs the project's own
    keys, and the instance's bucket stays refused (see
    ``depictio.models.s3_access``). Anything else goes through the same host
    validation as remote data URLs (scheme allowlist, private-range rejection,
    ``DEPICTIO_REMOTE_URL_ALLOWLIST`` escape hatch): a project-supplied
    endpoint is the same SSRF surface. Shared by the write path (400) and the
    read path (``StorageEndpointRejected``) so both apply the gating in force
    *now*.
    """
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "endpoint_url must be an http(s) URL, e.g. https://s3.example.org"
    try:
        normalized = _normalize_endpoint(endpoint_url)
    except ValueError:
        return "endpoint_url has an invalid port."
    if normalized in _instance_endpoints():
        return None
    try:
        validate_remote_url(endpoint_url)
    except RemoteURLRejected as exc:
        return str(exc)
    return None


def _refuse_instance_bucket(bucket: str) -> None:
    """The instance's own bucket cannot back a project's storage settings."""
    if is_instance_bucket(bucket, settings.s3):
        raise S3AccessRefused(
            f"The bucket '{bucket}' holds this Depictio instance's own data and cannot be "
            "used in a project's storage settings."
        )


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


def _refuse_stored_secret_for_new_settings(
    existing: dict, payload: ProjectStorageConfigIn, access_key_id: str
) -> None:
    """422 when a PUT without a secret changes what the stored secret belongs to."""
    if access_key_id != existing.get("access_key_id"):
        raise HTTPException(
            status_code=422,
            detail="Enter the secret for the new access key: the stored one is for another key.",
        )
    changed = [
        name
        for name, new, old in (
            ("endpoint", payload.endpoint_url, existing.get("endpoint_url")),
            ("bucket", payload.bucket, existing.get("bucket")),
        )
        if new != old
    ]
    if changed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Enter the secret again for the new {' and '.join(changed)}: a stored "
                "secret is only kept for the endpoint and bucket it was saved with."
            ),
        )


def _set_project_storage(
    project_id: str, payload: ProjectStorageConfigIn, current_user
) -> ProjectStorageConfigOut:
    from depictio.api.v1.crypto import encrypt_secret

    project_dict = _load_project_for_owner(project_id, current_user)
    _validate_storage_endpoint(payload.endpoint_url)
    _refuse_instance_bucket(payload.bucket)

    project_oid = project_dict["_id"]
    existing = project_storage_collection.find_one({"project_id": project_oid}) or {}
    access_key_id = (payload.access_key_id or "").strip() or None

    if not access_key_id:
        # No key: the bucket is read without credentials, so no secret either.
        secret_encrypted: str | None = None
    elif payload.secret_access_key:
        secret_encrypted = encrypt_secret(payload.secret_access_key)
    else:
        # Omitted/empty secret keeps whatever is stored: write-only semantics,
        # for the settings it was saved with only. Kept across a new key, or a
        # new endpoint or bucket, an old secret would be sent where its owner
        # never gave it.
        secret_encrypted = existing.get("secret_encrypted")
        if secret_encrypted:
            _refuse_stored_secret_for_new_settings(existing, payload, access_key_id)
    if access_key_id and not secret_encrypted:
        # Reads would refuse a key without its secret; say so at save time.
        raise HTTPException(status_code=422, detail="Enter the secret for this access key.")

    # Storage writes are rare and owner-driven; ensuring the unique index here
    # (idempotent) covers instances upgraded past the first boot, where the
    # db_init call never ran.
    ensure_project_storage_indexes(project_storage_collection)

    # Naive UTC, like every stored timestamp: the viewer reads it as UTC.
    updated_at = utc_now_str()
    project_storage_collection.update_one(
        {"project_id": project_oid},
        {
            "$set": {
                "endpoint_url": payload.endpoint_url,
                "bucket": payload.bucket,
                "region": payload.region,
                "access_key_id": access_key_id,
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
        access_key_id=access_key_id,
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


def project_storage_for(project_id: str | ObjectId) -> ProjectS3Config | None:
    """A project's storage settings for its remote reads, secret decrypted.

    Returns ``None`` when the project has no storage config: a server-side
    read is then public or refused, never done with the instance credentials.
    Raises:

    * ``ValueError`` for a malformed ``project_id``;
    * ``StorageEndpointRejected`` when the stored endpoint fails the host
      gating currently in force (re-checked on every read);
    * ``StorageSecretUnreadable`` when the stored secret cannot be decrypted
      with this process's secrets key.

    None of these fall back to other credentials: a private bucket read with
    the wrong key fails loudly downstream or, worse, reads the wrong data.
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

    return ProjectS3Config(
        endpoint_url=endpoint_url,
        bucket=doc.get("bucket") or None,
        region=doc.get("region") or AWS_DEFAULT_REGION,
        access_key_id=doc.get("access_key_id") or "",
        secret_access_key=secret,
    )


def _test_project_storage(project_id: str, current_user) -> StorageTestResult:
    """Probe the configured bucket with the stored credentials.

    HeadBucket first, which also learns the bucket's region from its
    ``x-amz-bucket-region`` header (a 301 naming another region is retried
    there once) and writes it back when it differs from the stored one; then
    a one-key ListObjectsV2, which is what reads need. Never ``list_buckets``:
    gateways that scope a key to one bucket (EMBL) deny it.

    Failures come back as ``success: false`` with the same sanitized message a
    read would get, never a 5xx (the whole point is diagnosing bad settings).
    """
    project_dict = _load_project_for_owner(project_id, current_user)
    project_oid = project_dict["_id"]
    doc = project_storage_collection.find_one({"project_id": project_oid})
    if not doc:
        raise HTTPException(status_code=404, detail="No storage configured for this project.")

    try:
        config = project_storage_for(project_oid)
    except ProjectStorageUnusable as exc:
        return StorageTestResult(success=False, message=exc.detail)
    if config is None:  # deleted between the two reads
        raise HTTPException(status_code=404, detail="No storage configured for this project.")
    bucket = config.bucket
    if not bucket:
        # Configs saved before the bucket became required.
        return StorageTestResult(
            success=False, message="Set the bucket name in the storage settings, then test again."
        )

    try:
        _refuse_instance_bucket(bucket)
        target = project_target(config, bucket, timeout_s=remote_policy().timeout_s)
    except S3AccessRefused as exc:
        return StorageTestResult(success=False, message=exc.detail)

    detected_region: str | None = None
    region_note = ""
    try:
        target, detected_region = probe_bucket(target)
        if detected_region and detected_region != config.region:
            project_storage_collection.update_one(
                {"project_id": project_oid}, {"$set": {"region": detected_region}}
            )
            region_note = (
                f" Its region is {detected_region}; the storage settings were updated to match."
            )
        target.client().list_objects_v2(Bucket=bucket, MaxKeys=1)
    except Exception as exc:
        failure = S3AccessFailed.from_exception(exc, target)
        logger.info(
            f"Storage test failed for project {project_oid} ({failure.code}): {type(exc).__name__}"
        )
        return StorageTestResult(
            success=False, message=failure.detail, detected_region=detected_region
        )
    return StorageTestResult(
        success=True,
        message=f"Bucket '{bucket}' is reachable.{region_note}",
        detected_region=detected_region,
    )
