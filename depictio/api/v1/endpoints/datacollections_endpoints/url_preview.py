"""Show the start of a remote file before a table is made from it: ``POST /datacollections/url_preview``.

The "One file from its URL" source of Add data and New project hands the
server a location to fetch. This shows what that location holds first, so a wrong URL, a refused
host or an HTML error page is caught before a data collection exists.

- ``s3://`` is read as the run-folder preview reads it
  (:func:`run_file_preview.preview_run_file`, the file's own prefix as the
  folder), so it answers the same refusals: a bucket that is neither public nor
  credentialed for the server is refused with its own code.
- ``https://`` (``http://`` only when the policy allows it) goes through the
  SSRF gateway (:func:`remote_fetch.open_validated_stream`), every redirect
  re-validated, and only the first :data:`MAX_HEAD_BYTES` are read.

A parquet file at an http(s) URL is not opened: its footer is at the end, so
a bounded head read cannot show it.

Synchronous: the route dispatches via ``asyncio.to_thread``.
"""

from __future__ import annotations

import zlib
from urllib.parse import unquote, urlparse

import httpx
from pydantic import BaseModel, Field

from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.api.v1.endpoints.projects_endpoints.run_file_preview import (
    MAX_HEAD_BYTES,
    NOT_PREVIEWED,
    RunFilePreview,
    RunFilePreviewRequest,
    _decoded_preview,
    _gunzip,
    _not_shown,
    _suffix,
    preview_run_file,
)
from depictio.api.v1.remote_fetch import RemoteURLRejected, open_validated_stream
from depictio.models.logging import logger

URL_REFUSED = "url_refused"
URL_UNREACHABLE = "url_unreachable"
URL_NOT_A_FILE = "url_not_a_file"


class URLPreviewRequest(BaseModel):
    """Body of POST /datacollections/url_preview."""

    url: str
    max_rows: int = Field(default=10, ge=1, le=50)


def _name_of(path: str) -> str:
    return unquote(path.rstrip("/").rsplit("/", 1)[-1])


def _s3_preview(url: str, max_rows: int, *, request, current_user) -> RunFilePreview:
    parsed = urlparse(url)
    if not parsed.path.strip("/") or url.endswith("/"):
        raise CodedHTTPException(
            422, "This is a folder, not a file. Give the URL of one table file.", URL_NOT_A_FILE
        )
    folder = url.rsplit("/", 1)[0] + "/"
    return preview_run_file(
        RunFilePreviewRequest(data_root=folder, location=url, max_rows=max_rows),
        request=request,
        current_user=current_user,
    )


def _http_preview(url: str, max_rows: int) -> RunFilePreview:
    name = _name_of(urlparse(url).path)
    if not name:
        raise CodedHTTPException(
            422, "The URL names no file. Give the URL of one table file.", URL_NOT_A_FILE
        )
    suffix = _suffix(name)
    inner = _suffix(name[: -len(suffix)]) if suffix == ".gz" else suffix
    try:
        with open_validated_stream(url) as response:
            if not response.is_success:
                raise CodedHTTPException(
                    422,
                    f"The server answered HTTP {response.status_code} for this URL.",
                    URL_UNREACHABLE,
                )
            length = response.headers.get("content-length")
            size = int(length) if length and length.isdigit() else None
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            base = {"location": url, "name": name, "size": size}
            if suffix == ".parquet":
                return _not_shown(
                    "A parquet file at a URL is not previewed; its columns are read "
                    "when the table is added.",
                    base=base,
                )
            if inner in NOT_PREVIEWED:
                return _not_shown(NOT_PREVIEWED[inner], base=base)
            if content_type == "text/html" and inner not in (".html", ".htm"):
                return _not_shown(
                    "This URL returns a web page, not a data file. Use the direct "
                    "download link of the file.",
                    base=base,
                )
            head = bytearray()
            for chunk in response.iter_bytes(chunk_size=16 * 1024):
                head.extend(chunk)
                if len(head) >= MAX_HEAD_BYTES:
                    break
    except RemoteURLRejected as exc:
        raise CodedHTTPException(422, str(exc), URL_REFUSED) from exc
    except httpx.HTTPError as exc:
        logger.info(f"url_preview: cannot reach {url}: {exc}")
        raise CodedHTTPException(
            422, "The URL could not be reached from the server.", URL_UNREACHABLE
        ) from exc

    data = bytes(head[:MAX_HEAD_BYTES])
    complete = len(head) < MAX_HEAD_BYTES or (size is not None and len(head) >= size)
    if suffix == ".gz":
        try:
            data, ended = _gunzip(data)
        except zlib.error:
            return _not_shown("This file could not be decompressed.", base=base)
        complete = complete and ended
    return _decoded_preview(data, inner, complete=complete, max_rows=max_rows, base=base)


def preview_remote_url(payload: URLPreviewRequest, *, request, current_user) -> RunFilePreview:
    """The preview of ``payload.url``: an ``s3://`` object or an http(s) file.

    422 coded ``url_refused`` for a URL the policy refuses, ``url_unreachable``
    for a transport failure or a non-2xx answer, ``url_not_a_file`` for a URL
    naming no file; an ``s3://`` refusal keeps the run-folder preview's code.
    """
    url = payload.url.strip()
    scheme = urlparse(url).scheme.lower()
    if scheme == "s3":
        return _s3_preview(url, payload.max_rows, request=request, current_user=current_user)
    if scheme in ("http", "https"):
        return _http_preview(url, payload.max_rows)
    raise CodedHTTPException(
        422, "The URL must start with https://, s3:// or http://.", URL_REFUSED
    )
