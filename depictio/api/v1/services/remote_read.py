"""Range-capable reads of track files, local to Depictio or read in place.

Genome browsers read indexed files (bigWig, BAM, tabix…) a few kilobytes at a
time with HTTP ``Range`` requests. This module turns a stored location into a
byte source the API can stream from, whatever it points at:

- ``depictio_s3``: an object in Depictio's own bucket (uploaded at ingestion);
- ``remote_s3``: an object in another, allow-listed bucket, read with a
  separate client (anonymous unless credentials are configured) so Depictio's
  own credentials never leave for a third-party endpoint;
- ``https``: a file on an allow-listed host, read with httpx. Redirects are
  not followed (a redirect could leave the allow-list), and every request has
  a timeout.

Callers never pass a URL from the browser: locations come from a data
collection the caller has access to, and allow-lists are checked here again at
read time. The same shape as the bioimage store reader (#1120), so the two can
share one module later.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

SourceKind = Literal["depictio_s3", "remote_s3", "https"]

_CHUNK = 256 * 1024
_SIZE_TTL_S = 300.0


class RemoteReadError(Exception):
    """A source could not be read; ``status`` is the HTTP code to answer with."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class ByteSource:
    kind: SourceKind
    bucket: str | None = None
    key: str | None = None
    url: str | None = None

    @property
    def cache_key(self) -> str:
        return self.url or f"{self.kind}:{self.bucket}/{self.key}"


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int  # inclusive

    @property
    def length(self) -> int:
        return self.end - self.start + 1


# --------------------------------------------------------------------------
# Location → source
# --------------------------------------------------------------------------


def _split_s3(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    bucket, key = parsed.netloc, parsed.path.lstrip("/")
    if not bucket or not key:
        raise RemoteReadError(400, f"Malformed S3 location: {uri}")
    return bucket, key


def _safe_relative(path: str) -> str:
    """Normalise a relative key and refuse any traversal out of its prefix."""
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise RemoteReadError(400, "Relative track path escapes its folder")
        parts.append(part)
    if not parts:
        raise RemoteReadError(400, "Empty track path")
    return "/".join(parts)


def resolve_location(uri: str, base_folder: str) -> ByteSource:
    """Turn a stored track/assembly location into a readable source.

    ``base_folder`` is the ``s3://bucket/prefix/`` relative locations live under
    (the data collection's own folder in Depictio's bucket). An ``s3://`` URI
    into Depictio's bucket is accepted only inside that folder: reading the
    bucket by URL would otherwise bypass per-collection access control.
    """
    uri = uri.strip()
    scheme = urlparse(uri).scheme.lower()
    own_bucket = settings.s3.bucket

    if scheme in ("", "file") and "://" not in uri:
        base_bucket, base_prefix = _split_s3(base_folder.rstrip("/") + "/_")
        base_prefix = base_prefix[: -len("_")]
        return ByteSource("depictio_s3", bucket=base_bucket, key=base_prefix + _safe_relative(uri))

    if scheme == "s3":
        bucket, key = _split_s3(uri)
        if bucket == own_bucket:
            base_bucket, base_prefix = _split_s3(base_folder.rstrip("/") + "/_")
            base_prefix = base_prefix[: -len("_")]
            if base_bucket != bucket or not key.startswith(base_prefix) or ".." in key.split("/"):
                raise RemoteReadError(
                    403, "Depictio's data bucket is only readable inside a collection's folder"
                )
            return ByteSource("depictio_s3", bucket=bucket, key=key)
        if bucket not in settings.jbrowse.s3_buckets:
            raise RemoteReadError(
                403,
                f"S3 bucket '{bucket}' is not allow-listed (DEPICTIO_JBROWSE_REMOTE_S3_BUCKETS)",
            )
        return ByteSource("remote_s3", bucket=bucket, key=key)

    if scheme in ("https", "http"):
        host = (urlparse(uri).hostname or "").lower()
        if scheme == "http":
            raise RemoteReadError(403, "Plain http:// tracks are not served; use https://")
        if host not in settings.jbrowse.https_hosts:
            raise RemoteReadError(
                403,
                f"Host '{host}' is not allow-listed (DEPICTIO_JBROWSE_REMOTE_HTTPS_HOSTS)",
            )
        return ByteSource("https", url=uri)

    raise RemoteReadError(400, f"Unsupported track location scheme: {scheme or uri}")


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

_clients: dict[str, object] = {}
_clients_lock = threading.Lock()


def _own_s3_client():
    import boto3
    from botocore.config import Config

    with _clients_lock:
        client = _clients.get("own")
        if client is None:
            client = boto3.client(
                "s3",
                endpoint_url=settings.s3.endpoint_url,
                aws_access_key_id=settings.s3.aws_access_key_id,
                aws_secret_access_key=settings.s3.aws_secret_access_key,
                verify=settings.s3.verify_tls,
                config=Config(connect_timeout=5, retries={"total_max_attempts": 2}),
            )
            _clients["own"] = client
    return client


def _remote_s3_client():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    cfg = settings.jbrowse
    with _clients_lock:
        client = _clients.get("remote")
        if client is None:
            access_key = cfg.remote_s3_access_key
            secret_key = (
                cfg.remote_s3_secret_key.get_secret_value() if cfg.remote_s3_secret_key else None
            )
            signed = bool(access_key and secret_key)
            client = boto3.client(
                "s3",
                endpoint_url=cfg.remote_s3_endpoint_url or None,
                region_name=cfg.remote_s3_region,
                aws_access_key_id=access_key if signed else None,
                aws_secret_access_key=secret_key if signed else None,
                config=Config(
                    signature_version=None if signed else UNSIGNED,
                    connect_timeout=5,
                    read_timeout=cfg.remote_timeout_s,
                    retries={"total_max_attempts": 2},
                ),
            )
            _clients["remote"] = client
    return client


def _s3_client_for(src: ByteSource):
    return _own_s3_client() if src.kind == "depictio_s3" else _remote_s3_client()


def _http_client():
    import httpx

    with _clients_lock:
        client = _clients.get("http")
        if client is None:
            client = httpx.Client(
                follow_redirects=False,
                timeout=httpx.Timeout(settings.jbrowse.remote_timeout_s),
                headers={"User-Agent": "depictio-track-proxy"},
            )
            _clients["http"] = client
    return client


# --------------------------------------------------------------------------
# Size (cached: JBrowse reads the same file block by block)
# --------------------------------------------------------------------------

_sizes: dict[str, tuple[float, int]] = {}


def _check_https_status(status: int, url: str) -> None:
    if 300 <= status < 400:
        raise RemoteReadError(
            502, f"Remote track redirected ({status}); redirects are not followed"
        )
    if status in (401, 403):
        raise RemoteReadError(502, f"Remote host refused access ({status})")
    if status == 404:
        raise RemoteReadError(404, "Remote track not found")
    if status >= 400:
        raise RemoteReadError(502, f"Remote host answered {status}")


def source_size(src: ByteSource) -> int:
    cached = _sizes.get(src.cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _SIZE_TTL_S:
        return cached[1]

    if src.kind == "https":
        assert src.url
        client = _http_client()
        resp = client.head(src.url)
        size: int | None = None
        if resp.status_code < 300 and resp.headers.get("content-length"):
            size = int(resp.headers["content-length"])
        else:
            # Some servers do not answer HEAD: ask for one byte and read the total.
            resp = client.get(src.url, headers={"Range": "bytes=0-0"})
            _check_https_status(resp.status_code, src.url)
            total = resp.headers.get("content-range", "").rpartition("/")[2]
            if total.isdigit():
                size = int(total)
            elif resp.status_code == 200 and resp.headers.get("content-length"):
                size = int(resp.headers["content-length"])
        if size is None:
            _check_https_status(resp.status_code, src.url)
            raise RemoteReadError(502, "Remote host did not report the file size")
    else:
        from botocore.exceptions import ClientError

        try:
            head = _s3_client_for(src).head_object(Bucket=src.bucket, Key=src.key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                raise RemoteReadError(404, "Track file not found") from exc
            if code in ("403", "AccessDenied"):
                raise RemoteReadError(502, "Storage refused access to the track file") from exc
            raise RemoteReadError(502, f"Storage error: {code}") from exc
        except Exception as exc:  # noqa: BLE001 - network errors of any kind
            raise RemoteReadError(502, f"Storage unreachable: {exc}") from exc
        size = int(head["ContentLength"])

    _sizes[src.cache_key] = (now, size)
    if len(_sizes) > 4096:
        _sizes.clear()
    return size


# --------------------------------------------------------------------------
# Range parsing and streaming
# --------------------------------------------------------------------------


def parse_range(header: str | None, size: int) -> ByteRange | None:
    """Parse a ``Range`` header against ``size``.

    Returns None for "no range" (whole file). A single range is clamped to the
    file (JBrowse routinely over-reads the end of small tabix files); several
    ranges, a malformed header or a start past the end raise 416.
    """
    if not header:
        return None
    unit, _, spec = header.strip().partition("=")
    if unit.strip().lower() != "bytes" or not spec or "," in spec:
        raise RemoteReadError(416, "Only a single bytes range is supported")
    first, _, last = spec.strip().partition("-")
    try:
        if first == "":
            suffix = int(last)
            if suffix <= 0:
                raise ValueError
            start, end = max(size - suffix, 0), size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
    except ValueError as exc:
        raise RemoteReadError(416, "Malformed Range header") from exc
    if start < 0 or start >= size or end < start:
        raise RemoteReadError(416, "Range not satisfiable")
    return ByteRange(start, min(end, size - 1))


def open_range(src: ByteSource, rng: ByteRange) -> Iterator[bytes]:
    """Open ``rng`` of ``src`` and return an iterator over its chunks.

    The upstream request is made *before* returning, so a missing file or a
    refusal surfaces as a ``RemoteReadError`` the endpoint can still turn into
    a proper status code, instead of a stream that dies after a 206.
    """
    if src.kind == "https":
        assert src.url
        client = _http_client()
        request = client.build_request(
            "GET", src.url, headers={"Range": f"bytes={rng.start}-{rng.end}"}
        )
        resp = client.send(request, stream=True)
        try:
            _check_https_status(resp.status_code, src.url)
            if resp.status_code == 200 and rng.start != 0:
                raise RemoteReadError(502, "Remote host ignored the Range request")
        except RemoteReadError:
            resp.close()
            raise

        def _https_chunks() -> Iterator[bytes]:
            remaining = rng.length
            try:
                for chunk in resp.iter_bytes(_CHUNK):
                    if remaining <= 0:
                        break
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]
                    remaining -= len(chunk)
                    yield chunk
            finally:
                resp.close()

        return _https_chunks()

    try:
        obj = _s3_client_for(src).get_object(
            Bucket=src.bucket, Key=src.key, Range=f"bytes={rng.start}-{rng.end}"
        )
    except Exception as exc:  # noqa: BLE001 - boto raises many types
        logger.warning(f"Track range read failed for {src.cache_key}: {exc}")
        raise RemoteReadError(502, "Storage read failed") from exc
    body = obj["Body"]

    def _s3_chunks() -> Iterator[bytes]:
        try:
            yield from body.iter_chunks(_CHUNK)
        finally:
            body.close()

    return _s3_chunks()


def read_all(src: ByteSource, max_bytes: int) -> bytes:
    """Read a whole (small) file, e.g. a chrom.sizes or alias file."""
    size = source_size(src)
    if size > max_bytes:
        raise RemoteReadError(413, "File too large to read whole")
    if size == 0:
        return b""
    return b"".join(open_range(src, ByteRange(0, size - 1)))
