"""Where an ``s3://`` read goes, and with which credentials.

Every S3 read Depictio makes for a user-supplied location (scan mode
``s3_prefix``, ``s3://`` url and manifest entries, a project's storage test)
is decided here, once: :func:`resolve_s3_target` turns the location into an
:class:`S3Target` from configuration alone, and :meth:`S3Target.client` and
:meth:`S3Target.polars_options` are the only ways to talk to it. Deciding
before any request goes out is what keeps a bucket name typed by a user from
becoming an existence or region oracle.

Server context (API process, Celery worker), in order:

1. a malformed location is refused;
2. a location in the instance's own bucket is refused, before anything else
   can match it: that bucket holds every project's data;
3. a project whose storage settings carry keys for this very bucket reads
   with them (kind ``project``), even when the bucket is also on
   ``public_s3_buckets``: its private objects stay readable;
4. a location on ``public_s3_buckets`` is read unsigned (kind ``public``);
5. any other project with storage settings reads with those settings and
   nothing else (kind ``project``): an empty access key reads unsigned
   against the project's endpoint, a key without its secret is refused, the
   instance's keys are never mixed in;
6. a location on ``credentialed_s3_buckets`` is read with the server's own
   ambient credentials, the boto3 / object-store default chain (kind
   ``ambient``);
7. anything else is refused.

The instance's credentials are never used for a user-supplied location in
server context. CLI context keeps its order: the project's keys for this
bucket, public, any other project settings, then the instance credentials of the CLI configuration (kind ``instance``), then the
ambient chain when that configuration carries no keys.

This module sits under ``depictio.models`` so the CLI-only install can use
it, which is why it never imports ``depictio.api``: the gateway policy and
the instance S3 settings come in as parameters (:class:`S3AccessPolicy`,
:class:`InstanceS3`). boto3 and botocore are imported lazily.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from depictio.models.logging import logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from botocore.config import Config
    from mypy_boto3_s3 import S3Client

# Public buckets are read against the default AWS endpoint. Their real region is
# resolved per bucket by :func:`ensure_region`; this is the region that
# resolution is itself asked in, and the fallback when it comes back empty.
AWS_DEFAULT_REGION = "us-east-1"

# Same default as ``RemoteConfig.timeout_s``, for targets built without a policy.
DEFAULT_TIMEOUT_S = 30.0

S3Context = Literal["server", "cli"]
S3TargetKind = Literal["public", "project", "instance", "ambient"]

# Bucket names as S3 accepts them, legacy uppercase and underscores included.
_BUCKET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# ── Inputs ──────────────────────────────────────────────────────────────────


class S3AccessPolicy(Protocol):
    """The slice of ``RemoteConfig`` the resolver reads."""

    @property
    def public_s3_buckets(self) -> str: ...

    @property
    def credentialed_s3_buckets(self) -> str: ...

    @property
    def timeout_s(self) -> float: ...


class InstanceS3(Protocol):
    """The slice of ``S3DepictioCLIConfig`` the resolver reads."""

    @property
    def bucket(self) -> str: ...

    @property
    def endpoint_url(self) -> str: ...

    @property
    def aws_access_key_id(self) -> str: ...

    @property
    def aws_secret_access_key(self) -> str: ...

    @property
    def verify_tls(self) -> bool: ...


class ProjectS3Config(BaseModel):
    """A project's own storage settings, the only source of a ``project`` target.

    Built by the API from the stored, decrypted configuration. The polars
    spellings (``aws_access_key_id``, ``aws_region``, ...) are accepted too,
    so a hand-written ``remote_storage_options`` block in a CLI configuration
    keeps loading.
    """

    model_config = ConfigDict(extra="ignore")

    endpoint_url: str = Field(validation_alias=AliasChoices("endpoint_url", "aws_endpoint_url"))
    bucket: str | None = None
    region: str = Field(
        default=AWS_DEFAULT_REGION,
        validation_alias=AliasChoices("region", "aws_region", "region_name"),
    )
    access_key_id: str = Field(
        default="", validation_alias=AliasChoices("access_key_id", "aws_access_key_id")
    )
    secret_access_key: str = Field(
        default="",
        repr=False,
        validation_alias=AliasChoices("secret_access_key", "aws_secret_access_key"),
    )

    @field_validator("region", mode="before")
    @classmethod
    def _default_region(cls, value: Any) -> Any:
        return value or AWS_DEFAULT_REGION

    @field_validator("access_key_id", "secret_access_key", mode="before")
    @classmethod
    def _empty_when_missing(cls, value: Any) -> Any:
        return value or ""


# ── Errors ──────────────────────────────────────────────────────────────────


class S3AccessError(Exception):
    """An S3 read that was refused or failed.

    ``detail`` is plain English, safe to return to API clients: it names the
    kind of access, the bucket and the prefix, never an endpoint of the
    instance, a key or a request id. ``code`` is one of ``s3_refused``,
    ``s3_access_denied``, ``s3_no_such_bucket``, ``s3_wrong_region``,
    ``s3_unreachable`` and ``s3_error``. ``str(exc)`` is the detail, so the
    messages the CLI helpers fold an exception into stay sanitized too.
    """

    status_code: int = 502
    code: str = "s3_error"

    def __init__(self, detail: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class S3AccessRefused(S3AccessError, ValueError):
    """The configuration does not allow this read. Decided before any request.

    A ``ValueError`` too, so the existing ``except ValueError`` handlers on the
    scan and preview paths keep catching it.
    """

    status_code = 422
    code = "s3_refused"


class S3AccessFailed(S3AccessError):
    """The read was allowed and attempted, and S3 (or the network) said no."""

    @classmethod
    def from_client_error(cls, exc: Exception, target: S3Target) -> S3AccessFailed:
        """Map a botocore ``ClientError`` onto a code, a status and a safe message."""
        code, status = client_error_code(exc)
        where = target.location
        if code in _ACCESS_DENIED_CODES or status == 403:
            return cls(
                f"Access to {where} was denied when read {_credentials_phrase(target)}. "
                f"{_access_denied_hint(target)}",
                code="s3_access_denied",
                status_code=422,
            )
        if code in _NO_SUCH_BUCKET_CODES or status == 404:
            return cls(
                f"The bucket '{target.bucket}' does not exist {_store_phrase(target)}.",
                code="s3_no_such_bucket",
                status_code=422,
            )
        if code in _WRONG_REGION_CODES or status in (301, 307):
            return cls(
                f"The bucket '{target.bucket}' answered from another region than "
                f"{target.region or AWS_DEFAULT_REGION}. {_wrong_region_hint(target)}",
                code="s3_wrong_region",
                status_code=502,
            )
        if code in _UNAVAILABLE_CODES or (status is not None and status >= 500):
            return cls.unreachable(target)
        # An S3 error code is a fixed vocabulary word, safe to show; anything
        # that does not look like one is left out rather than echoed.
        shown = f" ({code})" if re.fullmatch(r"[A-Za-z0-9.]{1,64}", code) else ""
        return cls(f"Reading {where} failed with an S3 error{shown}.")

    @classmethod
    def unreachable(cls, target: S3Target) -> S3AccessFailed:
        return cls(
            f"Could not reach the storage holding {target.location}. Try again later; "
            f"{_unreachable_hint(target)}",
            code="s3_unreachable",
            status_code=502,
        )

    @classmethod
    def from_exception(cls, exc: Exception, target: S3Target) -> S3AccessFailed:
        """Any error a boto3 call raised: ``ClientError``, a transport error, no credentials."""
        from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

        if isinstance(exc, S3AccessFailed):
            return exc
        if isinstance(exc, ClientError):
            return cls.from_client_error(exc, target)
        if isinstance(exc, NoCredentialsError | PartialCredentialsError):
            return cls(
                f"No credentials are available to read {target.location} "
                f"{_credentials_phrase(target)}.",
                code="s3_access_denied",
                status_code=422,
            )
        return cls.unreachable(target)


_ACCESS_DENIED_CODES = frozenset(
    {
        "AccessDenied",
        "AllAccessDisabled",
        "AccountProblem",
        "ExpiredToken",
        "Forbidden",
        "InvalidAccessKeyId",
        "InvalidSecurity",
        "InvalidToken",
        "SignatureDoesNotMatch",
        "403",
    }
)
_NO_SUCH_BUCKET_CODES = frozenset({"NoSuchBucket", "NotFound", "404"})
_WRONG_REGION_CODES = frozenset(
    {
        "AuthorizationHeaderMalformed",
        "IllegalLocationConstraintException",
        "PermanentRedirect",
        "TemporaryRedirect",
        "301",
        "307",
    }
)
_UNAVAILABLE_CODES = frozenset(
    {"InternalError", "RequestTimeout", "ServiceUnavailable", "SlowDown", "500", "502", "503"}
)
# What ListObjectsV2 answers for a prefix that holds nothing on gateways that
# treat a prefix as a path (EMBL Group Volume buckets): an empty listing, not
# an error. ``NoSuchBucket`` is not one of them.
_MISSING_PREFIX_CODES = frozenset({"NoSuchKey", "NotFound", "404"})


def client_error_code(exc: Exception) -> tuple[str, int | None]:
    """``(error code, HTTP status)`` out of a botocore ``ClientError``."""
    response: dict = getattr(exc, "response", None) or {}
    code = str((response.get("Error") or {}).get("Code") or "")
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code, status if isinstance(status, int) else None


def _credentials_phrase(target: S3Target) -> str:
    if target.kind == "public":
        return "without credentials, as a public bucket"
    if target.kind == "project":
        if target.unsigned:
            return "without credentials, as the project's storage settings carry no access key"
        return "with the project's storage credentials"
    if target.kind == "instance":
        return "with the S3 credentials of the Depictio configuration"
    return "with the server's own credentials"


def _access_denied_hint(target: S3Target) -> str:
    if target.kind == "public":
        return (
            "The bucket does not allow anonymous reads: add storage credentials to the "
            "project, or ask an administrator to take it off the public bucket list."
        )
    if target.kind == "project":
        return (
            "Check the access key and secret in the project's storage settings, and that "
            "they may read this bucket."
        )
    if target.kind == "instance":
        return "Check the S3 credentials in the Depictio CLI configuration."
    return "Ask an administrator to check the server's access to this bucket."


def _store_phrase(target: S3Target) -> str:
    if target.kind == "project":
        return "at the endpoint in the project's storage settings"
    if target.kind == "instance":
        return "in the configured S3 storage"
    return "on AWS S3"


def _wrong_region_hint(target: S3Target) -> str:
    if target.kind == "project":
        return (
            "Set the bucket's region in the project's storage settings; testing the "
            "storage settings detects it."
        )
    return "The read could not follow it."


def _unreachable_hint(target: S3Target) -> str:
    if target.kind == "project":
        return "if it keeps failing, check the endpoint in the project's storage settings."
    return "if it keeps failing, ask an administrator to check the storage."


# ── Locations and bucket lists ──────────────────────────────────────────────


def split_s3_url(url: str) -> tuple[str, str]:
    """``(bucket, key)`` out of ``s3://bucket/key``. Refuses anything else.

    The key is kept verbatim (S3 keys may hold ``?`` or ``#``), only the
    slashes at its start are dropped.
    """
    if not isinstance(url, str) or url[:5].lower() != "s3://":
        raise S3AccessRefused(f"'{url}' is not an s3:// location.")
    bucket, _, key = url[5:].partition("/")
    if not _BUCKET_NAME.fullmatch(bucket):
        raise S3AccessRefused(
            f"'{url}' is not a valid s3:// location: it needs a bucket name, as in "
            "s3://bucket/path."
        )
    return bucket, key.lstrip("/")


def parse_bucket_list(raw: str) -> list[tuple[str, str]]:
    """Parse a ``bucket[/prefix]`` list into ``(bucket, prefix)`` pairs.

    The syntax of ``public_s3_buckets`` and ``credentialed_s3_buckets``: comma
    separated, each entry either ``bucket`` (the whole bucket, prefix ``""``)
    or ``bucket/prefix`` (that subtree only). Bucket names are case sensitive,
    so unlike the host lists these are not lowercased.
    """
    entries: list[tuple[str, str]] = []
    for raw_entry in (raw or "").split(","):
        entry = raw_entry.strip().strip("/")
        if not entry:
            continue
        bucket, _, prefix = entry.partition("/")
        entries.append((bucket, prefix.strip("/")))
    return entries


def bucket_list_matches(raw: str, bucket: str, key: str) -> bool:
    """Whether ``bucket``/``key`` falls under an entry of a ``bucket[/prefix]`` list.

    A ``bucket/prefix`` entry matches that prefix and everything under it, and
    only on a path boundary, so ``data`` does not match ``database/``.
    """
    key = key.lstrip("/")
    for entry_bucket, prefix in parse_bucket_list(raw):
        if entry_bucket != bucket:
            continue
        if not prefix or key == prefix or key.startswith(f"{prefix}/"):
            return True
    return False


def is_public_s3_location(url: str, policy: S3AccessPolicy) -> bool:
    """Whether ``url`` names an s3 location the administrator marked public.

    Decided from configuration alone, never by probing: an unsigned read
    attempted against an arbitrary user-supplied bucket would leak whether that
    bucket exists and in which region, through the error it returns.
    """
    try:
        bucket, key = split_s3_url(url)
    except S3AccessRefused:
        return False
    return bucket_list_matches(policy.public_s3_buckets, bucket, key)


def is_instance_bucket(bucket: str, instance_s3: InstanceS3 | None) -> bool:
    """Whether ``bucket`` is the one the instance keeps every project's data in.

    Compared by name only, whatever endpoint the read would go to. On AWS a
    bucket name is global, so ``s3://<instance bucket>`` is the instance's data
    from any regional or virtual-hosted endpoint. Elsewhere the same store
    answers under several names (the compose service ``s3``, its ``minio``
    alias, the external URL, a public URL), which no endpoint comparison can
    list reliably. Refusing a same-named bucket on another store is the price,
    and the safe side to err on.
    """
    instance_bucket = getattr(instance_s3, "bucket", "") if instance_s3 is not None else ""
    return bool(instance_bucket) and bucket == instance_bucket


# ── Targets ─────────────────────────────────────────────────────────────────


class S3Target(BaseModel):
    """One resolved S3 read: where it goes, and how it signs.

    Build one with :func:`resolve_s3_target` (or :func:`project_target` for a
    storage test), never by hand at a call site. ``key`` is the object key or
    prefix the read is about, kept for messages.
    """

    model_config = ConfigDict(frozen=True)

    kind: S3TargetKind
    bucket: str
    key: str = ""
    endpoint_url: str | None = None
    region: str | None = None
    access_key_id: str | None = Field(default=None, repr=False)
    secret_access_key: str | None = Field(default=None, repr=False)
    unsigned: bool = False
    verify_tls: bool = True
    timeout_s: float = DEFAULT_TIMEOUT_S

    @property
    def location(self) -> str:
        return f"s3://{self.bucket}/{self.key}"

    @property
    def _signs_with_keys(self) -> bool:
        return not self.unsigned and self.kind in ("project", "instance")

    def with_region(self, region: str) -> S3Target:
        return self.model_copy(update={"region": region})

    def with_key(self, key: str) -> S3Target:
        return self.model_copy(update={"key": key.lstrip("/")})

    def _boto_config(self) -> Config:
        from botocore import UNSIGNED
        from botocore.config import Config

        # ``when_required``: the EMBL S3 gateway rejects the CRC checksums boto3
        # >= 1.36 sends by default. Path-style for any explicit endpoint:
        # SeaweedFS, MinIO and most on-premise gateways do not serve
        # virtual-hosted bucket names. Three attempts in all, the standard
        # retry mode's own default, stated so a profile cannot raise it.
        return Config(
            signature_version=UNSIGNED if self.unsigned else "s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            s3={"addressing_style": "path"} if self.endpoint_url else {},
            connect_timeout=self.timeout_s,
            read_timeout=self.timeout_s,
            retries={"mode": "standard", "total_max_attempts": 3},
        )

    def client(self) -> S3Client:
        """The boto3 S3 client for this target. The one place one is built.

        Never call ``list_buckets`` on it: gateways that scope keys to one
        bucket (EMBL) deny it, and it says nothing about the bucket at hand.
        """
        import boto3

        signed = self._signs_with_keys
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url or None,
            region_name=self.region or None,
            # None for the unsigned and ambient kinds: boto3 then signs nothing,
            # or signs with its own default chain.
            aws_access_key_id=self.access_key_id if signed else None,
            aws_secret_access_key=self.secret_access_key if signed else None,
            config=self._boto_config(),
            verify=self.verify_tls,
        )

    def polars_options(self) -> dict[str, str]:
        """polars / object-store ``storage_options`` for this target, normalised keys."""
        options: dict[str, str] = {}
        if self.endpoint_url:
            options["aws_endpoint_url"] = self.endpoint_url
            options["aws_allow_http"] = (
                "true" if self.endpoint_url.lower().startswith("http://") else "false"
            )
        if self.region:
            options["aws_region"] = self.region
        if self.unsigned:
            options["aws_skip_signature"] = "true"
        elif self._signs_with_keys:
            options["aws_access_key_id"] = self.access_key_id or ""
            options["aws_secret_access_key"] = self.secret_access_key or ""
            blank_foreign_session_token(options, self.access_key_id)
        if not self.verify_tls:
            options["allow_invalid_certificates"] = "true"
        return options


# The names object-store and deltalake read a session token from in the
# environment, in any case: a bare TOKEN as well as AWS_SESSION_TOKEN.
SESSION_TOKEN_ENV_NAMES = ("aws_session_token", "aws_token", "session_token", "token")


def blank_foreign_session_token(options: dict, access_key_id: str | None) -> dict:
    """Give ``aws_session_token`` empty when the environment holds one for another key.

    object-store (under polars and deltalake) fills in every option it is not
    given from the environment, a session token included, and sends it with
    the keys it is given: the user's own AWS session token would reach a
    project's or the instance's endpoint. An option given wins over the
    environment and there is no way to give none, so it is given empty. A
    token exported for the very key given is kept: temporary credentials.
    """
    if os.environ.get("AWS_ACCESS_KEY_ID") != access_key_id and any(
        name.lower() in SESSION_TOKEN_ENV_NAMES for name in os.environ
    ):
        options["aws_session_token"] = ""
    return options


def public_target(bucket: str, key: str = "", *, timeout_s: float = DEFAULT_TIMEOUT_S) -> S3Target:
    """An unsigned read of an allowlisted public bucket, on the default AWS endpoint."""
    return S3Target(
        kind="public",
        bucket=bucket,
        key=key,
        region=AWS_DEFAULT_REGION,
        unsigned=True,
        timeout_s=timeout_s,
    )


def project_target(
    config: ProjectS3Config,
    bucket: str,
    key: str = "",
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> S3Target:
    """A read with a project's storage settings, and nothing else.

    No access key reads unsigned against the project's endpoint (an open
    bucket on an on-premise gateway). A key without its secret, or a secret
    without its key, is refused rather than completed from anywhere else.
    """
    key_id = config.access_key_id.strip()
    secret = config.secret_access_key
    if bool(key_id) != bool(secret):
        raise S3AccessRefused(
            "The project's storage settings have an access key without its secret, or a "
            "secret without its key. Enter both, or clear both to read without credentials."
        )
    return S3Target(
        kind="project",
        bucket=bucket,
        key=key,
        endpoint_url=config.endpoint_url or None,
        region=config.region or AWS_DEFAULT_REGION,
        access_key_id=key_id or None,
        secret_access_key=secret or None,
        unsigned=not key_id,
        timeout_s=timeout_s,
    )


def instance_target(
    instance_s3: InstanceS3,
    bucket: str,
    key: str = "",
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> S3Target:
    """A read with the S3 credentials of a CLI configuration (CLI context only)."""
    return S3Target(
        kind="instance",
        bucket=bucket,
        key=key,
        endpoint_url=instance_s3.endpoint_url or None,
        # The region the Delta writes of the same configuration use.
        region=AWS_DEFAULT_REGION,
        access_key_id=instance_s3.aws_access_key_id,
        secret_access_key=instance_s3.aws_secret_access_key,
        verify_tls=bool(getattr(instance_s3, "verify_tls", True)),
        timeout_s=timeout_s,
    )


def _has_instance_keys(instance_s3: InstanceS3 | None) -> bool:
    if instance_s3 is None:
        return False
    return bool(instance_s3.aws_access_key_id) and bool(instance_s3.aws_secret_access_key)


def holds_keys_for(config: ProjectS3Config, bucket: str) -> bool:
    """Whether ``config`` carries an access key for ``bucket`` itself.

    Such settings win over the public list: a bucket an administrator lists as
    public may still hold objects only the project's keys can read. Settings
    for another bucket, or without a key, leave the public list first, so a
    project with keys for its own bucket still reads a public one unsigned.
    """
    return bool(config.access_key_id.strip()) and config.bucket == bucket


def resolve_s3_target(
    url: str,
    *,
    context: S3Context,
    project_storage: ProjectS3Config | None,
    instance_s3: InstanceS3 | None,
    policy: S3AccessPolicy,
) -> S3Target:
    """Decide how ``url`` is read. Configuration only: no request goes out.

    Raises :class:`S3AccessRefused` when the configuration does not allow the
    read. The order is in the module docstring. ``instance_s3`` is the
    instance's (server) or the CLI configuration's (CLI) S3 settings.
    """
    bucket, key = split_s3_url(url)
    timeout_s = policy.timeout_s
    server = context == "server"

    if server and is_instance_bucket(bucket, instance_s3):
        raise S3AccessRefused(
            f"{url} is in the bucket that holds this Depictio instance's own data, which "
            "cannot be read as a data source."
        )
    if project_storage is not None and holds_keys_for(project_storage, bucket):
        return project_target(project_storage, bucket, key, timeout_s=timeout_s)
    if bucket_list_matches(policy.public_s3_buckets, bucket, key):
        return public_target(bucket, key, timeout_s=timeout_s)
    if project_storage is not None:
        return project_target(project_storage, bucket, key, timeout_s=timeout_s)
    if server:
        if bucket_list_matches(policy.credentialed_s3_buckets, bucket, key):
            return S3Target(kind="ambient", bucket=bucket, key=key, timeout_s=timeout_s)
        raise S3AccessRefused(
            f"{url} cannot be read by the server: the project has no storage settings "
            "and the bucket is not one this instance allows. Add the bucket's endpoint "
            "and credentials in the project's storage settings, or ask an administrator "
            "to allow it."
        )
    if instance_s3 is not None and _has_instance_keys(instance_s3):
        return instance_target(instance_s3, bucket, key, timeout_s=timeout_s)
    return S3Target(kind="ambient", bucket=bucket, key=key, timeout_s=timeout_s)


# ── Region ──────────────────────────────────────────────────────────────────

# Buckets do not move, so one answer per (kind, endpoint, bucket) per process
# is enough. ``None`` records "answered, but named no region" (EMBL, SeaweedFS):
# the target keeps the region it was configured with.
_bucket_regions: dict[tuple[str, str, str], str | None] = {}


def bucket_region_header(response: dict | None) -> str | None:
    """``x-amz-bucket-region`` out of a boto3 response or an error payload."""
    headers = ((response or {}).get("ResponseMetadata") or {}).get("HTTPHeaders") or {}
    return headers.get("x-amz-bucket-region") or None


def probe_bucket(target: S3Target) -> tuple[S3Target, str | None]:
    """HeadBucket ``target``'s bucket in its own region.

    Returns the target moved to the region the bucket named, and that region
    (``None`` when the answer carried no ``x-amz-bucket-region`` header, as on
    the EMBL gateway and SeaweedFS: keep the configured one). A 301 that names
    another region is retried there, once. Any other failure raises the
    botocore error; :meth:`S3AccessFailed.from_exception` maps it.

    Talks to the network: call it only for a target :func:`resolve_s3_target`
    returned, so a bucket name a user typed is never probed unless the
    configuration already allows reading it.
    """
    from botocore.exceptions import ClientError

    try:
        response = target.client().head_bucket(Bucket=target.bucket)
    except ClientError as exc:
        region = bucket_region_header(getattr(exc, "response", None))
        _, status = client_error_code(exc)
        if status != 301 or not region or region == target.region:
            raise
        moved = target.with_region(region)
        moved.client().head_bucket(Bucket=moved.bucket)
        return moved, region
    region = bucket_region_header(dict(response))
    if region and region != target.region:
        return target.with_region(region), region
    return target, region


def ensure_region(target: S3Target) -> S3Target:
    """``target`` in its bucket's own region, asked once per process.

    object-store does not follow the 301 S3 answers for a bucket that lives in
    another region (it fails with "Received redirect without LOCATION"), so a
    read has to start in the right one. Never raises: a failed lookup keeps
    the configured region and lets the read itself report the real failure.
    Only a real answer is cached, so one transient failure does not pin a
    bucket to the wrong region for the life of a long-lived worker.

    ``instance`` targets are left alone: they keep the region the Delta writes
    of the same configuration use. Same network caveat as :func:`probe_bucket`.
    """
    if target.kind == "instance":
        return target
    cache_key = (target.kind, target.endpoint_url or "", target.bucket)
    if cache_key in _bucket_regions:
        cached = _bucket_regions[cache_key]
        return target.with_region(cached) if cached else target

    from botocore.exceptions import ClientError

    try:
        resolved, region = probe_bucket(target)
    except ClientError as exc:
        # A bucket that forbids listing answers HeadBucket with a 403 that still
        # names its region; that is an answer, not a failure.
        region = bucket_region_header(getattr(exc, "response", None))
        if not region:
            code, status = client_error_code(exc)
            logger.warning(
                f"Could not resolve the region of {target.kind} bucket '{target.bucket}': "
                f"{code or status}"
            )
            return target
        resolved = target.with_region(region)
    except Exception as exc:
        # Offline, DNS down, no credentials, a response in an unexpected shape.
        logger.warning(
            f"Could not resolve the region of {target.kind} bucket '{target.bucket}': "
            f"{type(exc).__name__}"
        )
        return target
    _bucket_regions[cache_key] = region
    return resolved


# ── Listing ─────────────────────────────────────────────────────────────────


def is_missing_prefix(exc: Exception) -> bool:
    """Whether a ListObjectsV2 ``ClientError`` means "nothing under this prefix"."""
    code, status = client_error_code(exc)
    if code == "NoSuchBucket":
        return False
    return code in _MISSING_PREFIX_CODES or (status == 404 and not code)


def iter_object_pages(
    target: S3Target, prefix: str, *, delimiter: str | None = None
) -> Iterator[dict]:
    """ListObjectsV2 pages under ``prefix`` in ``target``'s bucket.

    With ``delimiter="/"`` a page holds the direct children only: the keys
    under ``Contents``, the sub-prefixes under ``CommonPrefixes``. A 404 for a
    prefix that holds nothing is an empty listing; every other failure raises
    :class:`S3AccessFailed`. Exceptions raised by the caller's loop body are
    the caller's: only the paginator's own are mapped.
    """
    from botocore.exceptions import ClientError

    params: dict[str, Any] = {"Bucket": target.bucket, "Prefix": prefix}
    if delimiter:
        params["Delimiter"] = delimiter
    try:
        paginator = target.client().get_paginator("list_objects_v2")
        pages = iter(paginator.paginate(**params))
    except Exception as exc:
        raise S3AccessFailed.from_exception(exc, target.with_key(prefix)) from exc
    while True:
        try:
            page = next(pages)
        except StopIteration:
            return
        except ClientError as exc:
            if is_missing_prefix(exc):
                return
            raise S3AccessFailed.from_client_error(exc, target.with_key(prefix)) from exc
        except Exception as exc:
            raise S3AccessFailed.from_exception(exc, target.with_key(prefix)) from exc
        yield dict(page)


# ── Public buckets (kept for the call sites that predate the targets) ───────


def public_s3_region(bucket: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """Region of an allowlisted public ``bucket``, ``us-east-1`` when unknown.

    Asked with an unsigned HeadBucket: the ``x-amz-bucket-region`` header comes
    back even on the 301 and the 403 a bucket that forbids listing returns.
    Only call it for a bucket :func:`is_public_s3_location` already accepted.
    """
    resolved = ensure_region(public_target(bucket, timeout_s=timeout_s))
    return resolved.region or AWS_DEFAULT_REGION


def public_s3_storage_options(url: str, policy: S3AccessPolicy) -> dict | None:
    """Polars options for reading ``url`` unsigned, or ``None`` when it is not public."""
    if not is_public_s3_location(url, policy):
        return None
    bucket, key = split_s3_url(url)
    target = ensure_region(public_target(bucket, key, timeout_s=policy.timeout_s))
    return target.polars_options()
