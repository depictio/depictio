"""Read/prune CLI-shipped pre-rendered MultiQC figures on S3.

The CLI offline prerender (``depictio.cli.cli.utils.multiqc_processor``) builds a
DC's aggregated Plotly figures at ingest and uploads them, gzipped, to
``s3://{bucket}/{dc_id}/prerender/{sha}.json.gz`` where ``{sha}`` is the trailing
hash of the figure's bare cache key (``generate_figure_cache_key``). Because the
CLI and the API compute that key from the same shared code, the render endpoint
can resolve a figure straight from S3 — no ``multiqc.parse_logs``/``get_plot``.

This module is the server-side reader/pruner for that prefix. It is intentionally
dumb: locate the object by cache key, gunzip it, return the dict (or ``None`` on
any miss/error — the caller then falls back to the Celery prerender path).
"""

from __future__ import annotations

import gzip
import json
from typing import Optional

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

# Shared "figure file name from cache key" — the same helper the on-disk store
# and the CLI upload path use, so all three name a figure identically.
from depictio.cli.cli.utils.multiqc_figures import figure_cache_key_sha


def _dc_prefix_uri(dc_id: str) -> str:
    """``s3://{bucket}/{dc_id}/prerender/`` — where the CLI uploads this DC's figures."""
    return f"s3://{settings.minio.bucket}/{dc_id}/prerender/"


def _figure_uri(dc_id: str, cache_key: str) -> str:
    """URI of a single prerendered figure object, named by the cache key's hash."""
    return f"{_dc_prefix_uri(dc_id)}{figure_cache_key_sha(cache_key)}.json.gz"


def read_figure(dc_id: str, cache_key: str) -> Optional[dict]:
    """Return the CLI-prerendered figure dict for ``cache_key``, or ``None``.

    A miss (object absent, gunzip/JSON error, S3 unavailable) returns ``None`` so
    the render endpoint falls through to its existing cold-build path rather than
    failing the request.
    """
    # Reuse the render service's cached fsspec S3 filesystem so we don't
    # re-create a client per request.
    from depictio.api.v1.services.multiqc.figures import _get_s3_filesystem

    uri = _figure_uri(dc_id, cache_key)
    try:
        fs = _get_s3_filesystem()
        if not fs.exists(uri):
            return None
        with fs.open(uri, "rb") as f:
            raw = f.read()
        return json.loads(gzip.decompress(raw).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — any failure is a cache miss
        logger.warning(f"multiqc_s3_prerender: read failed for {uri}: {exc}")
        return None


def delete_dc_prefix(dc_id: str) -> int:
    """Remove every CLI-prerendered object under ``{dc_id}/prerender/``.

    Called from the DC cache invalidator on append/replace so stale figures
    (keyed over the pre-mutation report set) don't linger. Returns the number of
    objects deleted; idempotent (missing prefix returns 0).
    """
    from depictio.api.v1.services.multiqc.figures import _get_s3_filesystem

    prefix = _dc_prefix_uri(dc_id)
    try:
        fs = _get_s3_filesystem()
        if not fs.exists(prefix.rstrip("/")):
            return 0
        objects = fs.find(prefix)
        if not objects:
            return 0
        fs.rm(objects)
        return len(objects)
    except Exception as exc:  # noqa: BLE001 — invalidation must never raise
        logger.warning(f"multiqc_s3_prerender: prefix delete failed for {prefix}: {exc}")
        return 0
