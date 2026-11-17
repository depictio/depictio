"""Test helpers: the instance storage backend on a fake boto3 client.

Code reaches the instance bucket through a ``StorageBackend`` (#1358). A test
that fakes boto3 wraps its fake in the real S3 backend, so the backend's own
calls (pagination, ranges, error mapping) are exercised as well.
"""

from __future__ import annotations

from typing import Any

from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
from depictio.models.storage import S3Backend


def s3_backend_on(client: Any, bucket: str | None = None) -> S3Backend:
    """An ``S3Backend`` whose boto3 client is ``client`` (the instance bucket by default)."""
    if bucket is None:
        from depictio.api.v1.configs.config import settings

        bucket = settings.s3.bucket
    backend = S3Backend(S3DepictioCLIConfig(bucket=bucket))
    backend._client = client
    return backend
