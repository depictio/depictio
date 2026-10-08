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

Settings can also arrive before their project exists: a run folder in a
private bucket is browsed, inspected and previewed with the settings typed in
next to it (:class:`RunStorageIn`, validated by :meth:`RunStorageIn.settings_for`
exactly as a saved config is), and ``POST /projects/from_run`` stores them on
the project it creates. Those always carry an access key and its secret: a
bucket read without credentials is one an administrator listed
(``DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS``), never one a user names. Until then
they live in the request body only: never logged, never answered back, never
written anywhere.
"""

import re
from urllib.parse import urlparse

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

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
    is_missing_prefix,
    probe_bucket,
    project_target,
    split_s3_url,
)
from depictio.models.timestamps import utc_now_str

# With no endpoint the region becomes part of the AWS host name object-store
# reads from, so it is a plain name: letters, digits, '.', '-' and '_'.
_REGION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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
    key to one bucket). An empty ``endpoint_url`` means AWS S3.
    ``secret_access_key`` is optional on update: omitted or null keeps the
    stored secret, so edits don't require retyping it, as long as the access
    key ID, the endpoint and the bucket stay the ones it was saved with. An
    empty ``access_key_id`` means "read without credentials", and drops any
    stored secret.
    """

    endpoint_url: str
    bucket: str = Field(min_length=1)
    region: str = AWS_DEFAULT_REGION
    access_key_id: str | None = None
    secret_access_key: str | None = Field(default=None, repr=False)

    @field_validator("endpoint_url", mode="before")
    @classmethod
    def _strip_endpoint(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("bucket", mode="before")
    @classmethod
    def _strip_bucket(cls, value):
        return value.strip().strip("/") if isinstance(value, str) else value

    @field_validator("region", mode="before")
    @classmethod
    def _default_region(cls, value):
        return (value.strip() if isinstance(value, str) else value) or AWS_DEFAULT_REGION

    @field_validator("region")
    @classmethod
    def _plain_region(cls, value: str) -> str:
        if not _REGION_NAME.fullmatch(value):
            raise ValueError("The region must be a plain name, such as eu-west-1.")
        return value

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


RUN_STORAGE_KEYS_REQUIRED = (
    "Give the bucket's access key and secret: a bucket without credentials is read only "
    "when an administrator allows it."
)


class RunStorageIn(BaseModel):
    """Storage settings typed in with an ``s3://`` run folder, before its project exists.

    No bucket field: the bucket is the one the location names
    (:meth:`settings_for`). An empty ``endpoint_url`` means AWS S3, an empty
    ``region`` the default one. The access key and its secret are required
    (:meth:`require_keys`), unlike on ``PUT /projects/{id}/storage``. The
    secret is a ``SecretStr`` so a model that ends up in a log line or a
    traceback shows it masked.
    """

    endpoint_url: str | None = None
    region: str | None = None
    access_key_id: str | None = None
    secret_access_key: SecretStr | None = None

    def require_keys(self) -> None:
        """Refuse settings without an access key or without its secret (422).

        Blank and whitespace-only count as missing. Without this, settings
        with no keys would read any public bucket unsigned, at any endpoint,
        outside the buckets an administrator lists
        (``DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS``). The detail is fixed text:
        neither value is echoed.
        """
        key = (self.access_key_id or "").strip()
        secret = self.secret_access_key.get_secret_value() if self.secret_access_key else ""
        if not key or not secret.strip():
            raise HTTPException(status_code=422, detail=RUN_STORAGE_KEYS_REQUIRED)

    def settings_for(self, location: str) -> ProjectStorageConfigIn:
        """These settings for the bucket of ``location``, validated as a saved config is.

        Missing keys first (:meth:`require_keys`, 422). Then built through
        :class:`ProjectStorageConfigIn`, so its rules apply as they are, and
        checked as ``PUT /projects/{id}/storage`` checks before storing: the
        endpoint gating (400), the instance's own bucket (``S3AccessRefused``).
        A malformed location is ``S3AccessRefused`` too. Nothing goes out but
        the DNS lookup of the endpoint gating.
        """
        bucket, _key = split_s3_url(location)
        self.require_keys()
        secret = self.secret_access_key.get_secret_value() if self.secret_access_key else None
        try:
            payload = ProjectStorageConfigIn(
                endpoint_url=self.endpoint_url or "",
                bucket=bucket,
                region=self.region or "",
                access_key_id=self.access_key_id,
                secret_access_key=secret,
            )
        except ValidationError as exc:
            # The messages only: a validation error's own text repeats its
            # input, the secret included. ``from None`` keeps it out of any
            # traceback too.
            detail = " ".join(
                str(error["msg"]).removeprefix("Value error, ")
                for error in exc.errors(
                    include_url=False, include_context=False, include_input=False
                )
            )
            raise HTTPException(status_code=422, detail=detail) from None
        _check_storage_settings(payload, has_secret=bool(secret))
        return payload


class RunStorageTestRequest(BaseModel):
    """Body of POST /projects/storage_test: settings not stored anywhere yet."""

    location: str
    storage: RunStorageIn


def read_settings(payload: ProjectStorageConfigIn) -> ProjectS3Config:
    """The read-side form of validated settings, as ``project_storage_for`` returns it."""
    return ProjectS3Config(
        endpoint_url=payload.endpoint_url,
        bucket=payload.bucket,
        region=payload.region,
        access_key_id=(payload.access_key_id or "").strip(),
        secret_access_key=payload.secret_access_key or "",
    )


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
    *now*. No endpoint at all is AWS S3, whose host boto3 and object-store
    build from the region: nothing chosen by the project, nothing to gate.
    """
    if not endpoint_url.strip():
        return None
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


def _check_storage_settings(payload: ProjectStorageConfigIn, *, has_secret: bool) -> str | None:
    """Refuse settings no read could use; return the access key ID, None for none.

    ``has_secret`` says whether a secret goes with the key, typed in or
    already stored.
    """
    _validate_storage_endpoint(payload.endpoint_url)
    _refuse_instance_bucket(payload.bucket)
    access_key_id = (payload.access_key_id or "").strip() or None
    if access_key_id and not has_secret:
        # Reads would refuse a key without its secret; say so at save time.
        raise HTTPException(status_code=422, detail="Enter the secret for this access key.")
    return access_key_id


def _set_project_storage(
    project_id: str, payload: ProjectStorageConfigIn, current_user
) -> ProjectStorageConfigOut:
    project_dict = _load_project_for_owner(project_id, current_user)
    project_oid = project_dict["_id"]
    existing = project_storage_collection.find_one({"project_id": project_oid}) or {}
    access_key_id = (payload.access_key_id or "").strip() or None
    if access_key_id and not payload.secret_access_key and existing.get("secret_encrypted"):
        # The stored secret is kept for the settings it was saved with only.
        # Kept across a new key, or a new endpoint or bucket, it would be sent
        # where its owner never gave it.
        _refuse_stored_secret_for_new_settings(existing, payload, access_key_id)
    return _store_project_storage(
        project_oid, payload, stored_secret=existing.get("secret_encrypted")
    )


def _store_project_storage(
    project_oid: ObjectId, payload: ProjectStorageConfigIn, *, stored_secret: str | None = None
) -> ProjectStorageConfigOut:
    """Check ``payload`` and store it as the project's settings, the secret encrypted.

    ``stored_secret`` is the encrypted secret already stored, kept when the
    payload carries none. No ownership check: the caller made it, as
    ``_set_project_storage`` does, or created the project itself.
    """
    from depictio.api.v1.crypto import encrypt_secret

    access_key_id = _check_storage_settings(
        payload, has_secret=bool(payload.secret_access_key or stored_secret)
    )
    if not access_key_id:
        # No key: the bucket is read without credentials, so no secret either.
        secret_encrypted: str | None = None
    elif payload.secret_access_key:
        secret_encrypted = encrypt_secret(payload.secret_access_key)
    else:
        # Omitted/empty secret keeps whatever is stored: write-only semantics.
        secret_encrypted = stored_secret

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


def _test_run_storage(location: str, storage: RunStorageIn) -> StorageTestResult:
    """Probe the bucket of ``location`` with settings typed in and stored nowhere.

    The probes of :func:`_test_project_storage`, the listing under the
    location's prefix. Other settings no read could use and failed probes
    answer ``success: false`` with the message a read would get. A malformed
    location raises ``S3AccessRefused`` and settings without both keys a 422
    ``HTTPException``, since it is the request at fault, not the settings.
    The detected region is answered, not written anywhere.
    """
    from botocore.exceptions import ClientError

    bucket, key = split_s3_url(location)
    prefix = f"{key.strip('/')}/" if key.strip("/") else ""
    storage.require_keys()
    try:
        config = read_settings(storage.settings_for(location))
        target = project_target(config, bucket, prefix, timeout_s=remote_policy().timeout_s)
    except HTTPException as exc:
        return StorageTestResult(success=False, message=str(exc.detail))
    except S3AccessRefused as exc:
        return StorageTestResult(success=False, message=exc.detail)

    detected_region: str | None = None
    try:
        target, detected_region = probe_bucket(target)
        try:
            listing = target.client().list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
        except ClientError as exc:
            # Gateways that treat a prefix as a path answer an empty one 404.
            if not is_missing_prefix(exc):
                raise
            listing = {}
    except Exception as exc:
        failure = S3AccessFailed.from_exception(exc, target)
        logger.info(
            f"Storage test failed for {target.location} ({failure.code}): {type(exc).__name__}"
        )
        return StorageTestResult(
            success=False, message=failure.detail, detected_region=detected_region
        )

    notes = ""
    if detected_region and detected_region != config.region:
        notes += f" Its region is {detected_region}."
    if prefix and not (listing.get("KeyCount") or listing.get("Contents")):
        notes += f" Nothing is stored under {target.location}."
    return StorageTestResult(
        success=True,
        message=f"Bucket '{bucket}' is reachable.{notes}",
        detected_region=detected_region,
    )
