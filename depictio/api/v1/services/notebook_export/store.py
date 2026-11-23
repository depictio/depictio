"""Where a render job's notebook goes in, and its report comes out.

S3 and not a shared directory: the document is ~10 MB and the report ~10 MB
more, the API and the worker are separate containers with nothing in common but
Mongo, Redis and this bucket, and a broker message is the wrong place for
either. Keys are namespaced by the user who asked, so the download endpoint can
only ever address the caller's own reports.
"""

from __future__ import annotations

import mimetypes

from depictio.api.v1.configs.config import settings
from depictio.api.v1.s3 import s3_client

HTML_MEDIA_TYPE = "text/html; charset=utf-8"
QMD_MEDIA_TYPE = "text/markdown; charset=utf-8"
PDF_MEDIA_TYPE = "application/pdf"

#: The route a preview job's files are served from (the editor's iframe opens
#: the report under it). The token inside the URL is the capability: the route
#: asks for no sign-in, so the key path must carry nothing else secret.
PREVIEW_FILES_ROUTE = "/depictio/api/v1/dashboards/notebook_export/preview_files"


def job_key(user_id: str, job_id: str, name: str) -> str:
    prefix = settings.notebook_export.render_prefix.strip("/")
    return f"{prefix}/{user_id}/{job_id}/{name}"


def preview_url(token: str) -> str:
    """A preview job's report, as the editor's iframe opens it."""
    return f"{PREVIEW_FILES_ROUTE}/{token}/report.html"


def preview_key(token: str, relpath: str) -> str:
    """One preview file's object key, under the job's token.

    The token is the only secret: a reader needs no user id to open the report
    (the URL is the capability), so the key names the files exactly as the
    route serves them, with nothing else in between.
    """
    prefix = settings.notebook_export.render_prefix.strip("/")
    return f"{prefix}/preview/{token}/{relpath.lstrip('/')}"


def preview_content_type(relpath: str) -> str:
    """The MIME type a served preview file carries, from its extension.

    Quarto's output is web files (html, css, js, png, woff2...), which the
    extension names; the report itself keeps the exact type every served
    report carries.
    """
    if relpath.endswith(".html"):
        return HTML_MEDIA_TYPE
    return mimetypes.guess_type(relpath)[0] or "application/octet-stream"


def put(key: str, body: bytes, content_type: str) -> None:
    s3_client.put_object(Bucket=settings.s3.bucket, Key=key, Body=body, ContentType=content_type)


def get(key: str) -> bytes:
    return s3_client.get_object(Bucket=settings.s3.bucket, Key=key)["Body"].read()


def size(key: str) -> int | None:
    """The object's size, or ``None`` when it is not there (yet)."""
    try:
        return int(s3_client.head_object(Bucket=settings.s3.bucket, Key=key)["ContentLength"])
    except Exception:
        return None


def delete(key: str) -> None:
    try:
        s3_client.delete_object(Bucket=settings.s3.bucket, Key=key)
    except Exception:  # noqa: BLE001 — a leftover staged notebook is not a failure
        pass
