"""Where a render job's notebook goes in, and its report comes out.

S3 and not a shared directory: the notebook is ~10 MB and the report ~10 MB
more, the API and the worker are separate containers with nothing in common but
Mongo, Redis and this bucket, and a broker message is the wrong place for
either. Keys are namespaced by the user who asked, so the download endpoint can
only ever address the caller's own reports.
"""

from __future__ import annotations

from depictio.api.v1.configs.config import settings
from depictio.api.v1.s3 import s3_client

HTML_MEDIA_TYPE = "text/html; charset=utf-8"
IPYNB_MEDIA_TYPE = "application/x-ipynb+json"


def job_key(user_id: str, job_id: str, name: str) -> str:
    prefix = settings.notebook_export.render_prefix.strip("/")
    return f"{prefix}/{user_id}/{job_id}/{name}"


def put(key: str, body: bytes, content_type: str) -> None:
    s3_client.put_object(Bucket=settings.minio.bucket, Key=key, Body=body, ContentType=content_type)


def get(key: str) -> bytes:
    return s3_client.get_object(Bucket=settings.minio.bucket, Key=key)["Body"].read()


def size(key: str) -> int | None:
    """The object's size, or ``None`` when it is not there (yet)."""
    try:
        return int(s3_client.head_object(Bucket=settings.minio.bucket, Key=key)["ContentLength"])
    except Exception:
        return None


def delete(key: str) -> None:
    try:
        s3_client.delete_object(Bucket=settings.minio.bucket, Key=key)
    except Exception:  # noqa: BLE001 — a leftover staged notebook is not a failure
        pass
