"""The S3 backend: any S3-compatible store (SeaweedFS, MinIO, AWS, Ceph, ...).

A thin layer over boto3 with the settings the instance's clients used before
they were gathered here: the endpoint and key pair of ``DEPICTIO_S3_*``,
``verify_tls``, region ``us-east-1``, and SigV4 presigned URLs signed for the
public endpoint so a browser can use them. Checksums follow the process-wide
``AWS_*_CHECKSUM_*`` defaults set in ``settings_models``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from depictio.models.storage.base import ObjectInfo, StorageError, StorageNotFound
from depictio.models.storage.registry import register_backend
from depictio.models.storage.uri import object_url, split_object_url

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

    from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig

#: The region every instance client signs with. S3-compatible stores ignore it;
#: AWS redirects a wrong one. Same value as ``PolarsStorageOptions.region``.
REGION = "us-east-1"

_NOT_FOUND = frozenset({"404", "NoSuchKey", "NoSuchBucket", "NotFound"})


def _code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return response.get("Error", {}).get("Code")
    return None


def _wrap(exc: Exception, what: str) -> StorageError:
    code = _code(exc)
    cls = StorageNotFound if code in _NOT_FOUND else StorageError
    return cls(f"{what}: {exc}", code=code)


@register_backend
class S3Backend:
    """The instance bucket on an S3-compatible endpoint."""

    name: ClassVar[str] = "s3"
    scheme: ClassVar[str] = "s3"

    def __init__(self, config: S3DepictioCLIConfig, *, fail_fast: bool = False) -> None:
        """``fail_fast`` trades retries for a short connect timeout (3 s, 2 attempts):
        for reads that have a fallback and must not hang on an unreachable store."""
        self.config = config
        self.bucket = config.bucket
        self.fail_fast = fail_fast
        self._lock = threading.Lock()
        self._client: S3Client | None = None
        self._presign_client: S3Client | None = None

    def __repr__(self) -> str:
        return f"S3Backend(bucket={self.bucket!r}, endpoint={self.config.endpoint_url!r})"

    # -- clients -------------------------------------------------------------

    def _make_client(self, endpoint_url: str, **config: Any) -> S3Client:
        import boto3
        from botocore.config import Config

        if self.fail_fast:
            config.setdefault("connect_timeout", 3)
            config.setdefault("retries", {"total_max_attempts": 2})
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=self.config.aws_access_key_id,
            aws_secret_access_key=self.config.aws_secret_access_key,
            region_name=REGION,
            verify=self.config.verify_tls,
            config=Config(**config) if config else None,
        )

    @property
    def client(self) -> S3Client:
        """The boto3 client on the configured endpoint, built once.

        S3-only: code outside ``depictio.models.storage`` should use the
        backend's methods, which every backend has.
        """
        with self._lock:
            if self._client is None:
                self._client = self._make_client(self.config.endpoint_url)
            return self._client

    def _presigner(self) -> S3Client:
        """A client whose signatures are valid for the browser's endpoint."""
        with self._lock:
            if self._presign_client is None:
                self._presign_client = self._make_client(
                    self.config.external_url, signature_version="s3v4"
                )
            return self._presign_client

    # -- addresses -----------------------------------------------------------

    def url(self, key: str = "") -> str:
        return object_url(self.scheme, self.bucket, key)

    def key_of(self, location: str) -> str | None:
        try:
            parts = split_object_url(location, (self.scheme,))
        except ValueError:
            return None
        return parts.key if parts.bucket == self.bucket else None

    # -- reads ---------------------------------------------------------------

    def list_objects(self, prefix: str = "") -> Iterator[ObjectInfo]:
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    yield ObjectInfo(
                        key=obj["Key"],
                        size=int(obj.get("Size", 0)),
                        etag=(obj.get("ETag") or "").strip('"'),
                        last_modified=obj.get("LastModified"),
                    )
        except Exception as exc:
            if isinstance(exc, StorageError):
                raise
            raise _wrap(exc, f"listing {self.url(prefix)}") from exc

    def head(self, key: str) -> ObjectInfo | None:
        try:
            meta = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if _code(exc) in _NOT_FOUND:
                return None
            raise _wrap(exc, f"head {self.url(key)}") from exc
        return ObjectInfo(
            key=key,
            size=int(meta.get("ContentLength", 0)),
            etag=(meta.get("ETag") or "").strip('"'),
            last_modified=meta.get("LastModified"),
        )

    def read_bytes(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            raise _wrap(exc, f"reading {self.url(key)}") from exc

    def read_range(self, key: str, start: int, end: int) -> bytes:
        if end <= start:
            return b""
        try:
            obj = self.client.get_object(
                Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end - 1}"
            )
            return obj["Body"].read()
        except Exception as exc:
            raise _wrap(exc, f"reading {self.url(key)}") from exc

    # -- writes --------------------------------------------------------------

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        except Exception as exc:
            raise _wrap(exc, f"writing {self.url(key)}") from exc

    def upload_file(self, key: str, path: str | Path, *, content_type: str | None = None) -> None:
        extra = {"ExtraArgs": {"ContentType": content_type}} if content_type else {}
        try:
            self.client.upload_file(str(path), self.bucket, key, **extra)
        except Exception as exc:
            raise _wrap(exc, f"uploading {path} to {self.url(key)}") from exc

    def delete_keys(self, keys: Iterable[str]) -> list[Any]:
        from depictio.models.s3_utils import delete_keys

        try:
            return delete_keys(self.client, self.bucket, keys)
        except Exception as exc:
            raise _wrap(exc, f"deleting from {self.url()}") from exc

    def delete_prefix(self, prefix: str) -> int:
        keys = [obj.key for obj in self.list_objects(prefix)]
        if keys:
            self.delete_keys(keys)
        return len(keys)

    # -- bucket --------------------------------------------------------------

    def bucket_exists(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception as exc:
            if _code(exc) in _NOT_FOUND:
                return False
            raise _wrap(exc, f"checking bucket {self.bucket}") from exc

    def ensure_bucket(self) -> bool:
        if self.bucket_exists():
            return False
        try:
            self.client.create_bucket(Bucket=self.bucket)
            return True
        except Exception as exc:
            # Another worker won the race, or the bundled store pre-created it.
            if _code(exc) in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                return False
            raise _wrap(exc, f"creating bucket {self.bucket}") from exc

    # -- handing the store to other libraries --------------------------------

    def presign_get(self, key: str, expires_in: int) -> str:
        return self._presigner().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def storage_options(self) -> dict[str, str]:
        from depictio.models.models.s3 import PolarsStorageOptions

        return PolarsStorageOptions.from_s3_config(self.config).model_dump(exclude_none=True)

    def filesystem(self) -> Any:
        import fsspec

        return fsspec.filesystem(
            "s3",
            endpoint_url=self.config.endpoint_url,
            key=self.config.aws_access_key_id,
            secret=self.config.aws_secret_access_key,
        )
