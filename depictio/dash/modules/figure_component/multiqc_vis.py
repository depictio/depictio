"""
MultiQC visualization module for Dash components.

This module provides a simple wrapper around MultiQC's plotting functionality,
allowing users to visualize MultiQC reports within Depictio dashboards.
"""

import hashlib
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import fsspec
import plotly.graph_objects as go

from depictio.api.cache import get_cache
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.figure_component.utils import _get_theme_template

# Global lock to prevent concurrent MultiQC operations (MultiQC global state is not thread-safe)
_multiqc_lock = threading.RLock()

# Multi-day TTL: explicit `_invalidate_multiqc_caches_for_dc` on append/replace
# is the source of truth for staleness. The previous 2 h TTL caused silent
# re-parses every two hours under no real change, which masked the prewarm
# race: even a warm cache would go cold mid-day. 30 d covers typical project
# work cycles; entries get rebuilt on demand if they ever do expire.
MULTIQC_CACHE_TTL_SECONDS = 30 * 24 * 3600


def _get_s3_filesystem_config() -> Dict[str, Any]:
    """Get S3 filesystem configuration from settings."""
    return {
        "endpoint_url": settings.minio.endpoint_url,
        "key": settings.minio.root_user,
        "secret": settings.minio.root_password,
    }


# Module-level cached S3 filesystem (reused across calls within the same process)
_cached_s3_fs = None


def _get_s3_filesystem():
    """Get a cached S3 filesystem instance (avoids re-creating per call)."""
    global _cached_s3_fs
    if _cached_s3_fs is None:
        _cached_s3_fs = fsspec.filesystem("s3", **_get_s3_filesystem_config())
    return _cached_s3_fs


def _resolve_local_cache_path(s3_location: str) -> Optional[str]:
    """Compute the local cache path for an S3 location without any S3 calls."""
    if not s3_location.startswith("s3://"):
        return None
    cache_base = os.path.expanduser(settings.s3_cache.cache_dir)
    path_parts = s3_location.replace("s3://", "").split("/", 1)
    bucket = path_parts[0]
    key = path_parts[1] if len(path_parts) > 1 else ""
    return os.path.join(cache_base, bucket, key)


def _get_local_path_for_s3(s3_location: str, use_cache: bool = True) -> str:
    """Get a local path for an S3 file, using local cache to avoid S3 round-trips."""
    if not s3_location.startswith("s3://"):
        return s3_location

    if not use_cache:
        return _download_s3_file_direct(s3_location)

    cache_path = _resolve_local_cache_path(s3_location)
    if cache_path and os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return cache_path

    try:
        fs = _get_s3_filesystem()
        if not fs.exists(s3_location):
            raise FileNotFoundError(f"S3 file does not exist: {s3_location}")

        if cache_path is None:
            return _download_s3_file_direct(s3_location)

        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        fs.get(s3_location, cache_path)
        return cache_path

    except Exception as e:
        logger.error(f"S3 cache download failed: {e}")
        if cache_path and os.path.exists(cache_path):
            os.remove(cache_path)
        return _download_s3_file_direct(s3_location)


def _download_s3_file_direct(s3_location: str) -> str:
    """Direct download of S3 file to temporary location (fallback method)."""
    path_parts = s3_location.replace("s3://", "").split("/", 1)
    key = path_parts[1] if len(path_parts) > 1 else ""

    file_extension = Path(key).suffix or ".tmp"
    temp_file = tempfile.NamedTemporaryFile(suffix=file_extension, delete=False)
    local_path = temp_file.name
    temp_file.close()

    try:
        fs = _get_s3_filesystem()
        if not fs.exists(s3_location):
            raise FileNotFoundError(f"S3 file does not exist: {s3_location}")
        fs.get(s3_location, local_path)
        return local_path
    except Exception as e:
        try:
            os.unlink(local_path)
        except OSError:
            pass
        logger.error(f"Failed to download S3 file directly: {e}")
        raise


def get_multiqc_modules(s3_location: str, use_s3_cache: bool = True) -> List[str]:
    """Get available MultiQC modules from a parquet file."""
    try:
        import multiqc

        local_file = _get_local_path_for_s3(s3_location, use_cache=use_s3_cache)
        multiqc.reset()
        multiqc.parse_logs(local_file)
        return multiqc.list_modules()

    except Exception as e:
        logger.error(f"Error getting MultiQC modules from {s3_location}: {e}", exc_info=True)
        return []


def get_multiqc_plots(s3_location: str, module: str, use_s3_cache: bool = True) -> List[str]:
    """Get available plots for a specific MultiQC module."""
    try:
        import multiqc

        local_file = _get_local_path_for_s3(s3_location, use_cache=use_s3_cache)
        multiqc.reset()
        multiqc.parse_logs(local_file)
        return multiqc.list_plots().get(module, [])

    except Exception as e:
        logger.error(
            f"Error getting MultiQC plots for module {module} from {s3_location}: {e}",
            exc_info=True,
        )
        return []


def get_multiqc_plots_from_metadata(metadata_plots: dict, module: str) -> List[str]:
    """Get available plots for a specific MultiQC module from metadata."""
    try:
        plot_names = []
        for plot_item in metadata_plots.get(module, []):
            if isinstance(plot_item, str):
                plot_names.append(plot_item)
            elif isinstance(plot_item, dict):
                plot_names.extend(plot_item.keys())
        return plot_names
    except Exception as e:
        logger.error(f"Error getting MultiQC plots for module {module} from metadata: {e}")
        return []


def get_multiqc_datasets(metadata_plots: dict, module: str, plot: str) -> List[str]:
    """Get available datasets for a specific MultiQC plot from metadata.

    Extracts dataset IDs from plots with sub-options, e.g.:
    {"Per Sequence GC Content": ["Percentages", "Counts"]}
    """
    try:
        for plot_item in metadata_plots.get(module, []):
            if isinstance(plot_item, dict) and plot in plot_item:
                datasets = plot_item[plot]
                return datasets if isinstance(datasets, list) else []
            if isinstance(plot_item, str) and plot_item == plot:
                return []
        return []
    except Exception as e:
        logger.error(f"Error getting MultiQC datasets for {module}/{plot}: {e}")
        return []


def _generate_cache_key(s3_locations: List[str]) -> str:
    """Generate deterministic cache key from S3 locations."""
    sorted_locations = sorted(s3_locations)
    locations_str = "|".join(sorted_locations)
    hash_digest = hashlib.sha256(locations_str.encode()).hexdigest()[:16]
    return f"multiqc:state:{hash_digest}"


def _generate_figure_cache_key(
    s3_locations: List[str],
    module: str,
    plot: str,
    dataset_id: Optional[str] = None,
    theme: str = "light",
    filter_sig: Optional[str] = None,
    dc_id: Optional[str] = None,
) -> str:
    """Generate cache key for a rendered figure.

    `dc_id` is embedded literally in the key so a DC-scoped invalidation
    (`cache.delete_pattern(f"dc={dc_id}")`) can drop every figure variant for
    that DC after an append/replace/clear, regardless of theme/filter combo.
    """
    sorted_locations = sorted(s3_locations)
    key_parts = [
        "|".join(sorted_locations),
        module,
        plot,
        str(dataset_id),
        theme,
        filter_sig or "",
    ]
    key_str = "::".join(key_parts)
    hash_digest = hashlib.sha256(key_str.encode()).hexdigest()[:16]
    return f"multiqc:figure:dc={dc_id or 'none'}:{hash_digest}"


# Public alias so callers (e.g. FastAPI endpoints) can layer filter-aware
# caching on top of the unfiltered baseline that `create_multiqc_plot` caches.
generate_figure_cache_key = _generate_figure_cache_key


def _get_or_parse_multiqc_logs(s3_locations: List[str], use_s3_cache: bool = True) -> bool:
    """Get cached MultiQC report or parse logs and cache the result.

    Thread-safe: uses global lock since MultiQC global state is not thread-safe.
    """
    import multiqc

    cache_key = _generate_cache_key(s3_locations)
    cache = get_cache()

    def _restore_from_cache_value(value: Any) -> bool:
        """Restore multiqc.report from a cache hit. Handles both the legacy
        in-memory shape (raw report object) and the new cloudpickle envelope
        produced below — `{"__cloudpickle__": <bytes>}`.
        """
        try:
            if isinstance(value, dict) and "__cloudpickle__" in value:
                import cloudpickle  # noqa: PLC0415

                multiqc.report = cloudpickle.loads(value["__cloudpickle__"])
            else:
                multiqc.report = value
            return True
        except Exception as e:
            logger.warning(f"Failed to restore cached multiqc.report: {e}")
            return False

    cached_report = cache.get(cache_key)
    if cached_report is not None:
        with _multiqc_lock:
            if _restore_from_cache_value(cached_report):
                return True

    with _multiqc_lock:
        # Double-check cache inside lock (another thread may have parsed while we waited)
        cached_report = cache.get(cache_key)
        if cached_report is not None and _restore_from_cache_value(cached_report):
            return True

        multiqc.reset()

        parsed_files = 0
        for s3_location in s3_locations:
            try:
                local_file = _get_local_path_for_s3(s3_location, use_cache=use_s3_cache)
                multiqc.parse_logs(local_file)
                parsed_files += 1
            except Exception as e:
                logger.warning(f"Error parsing {s3_location}: {e}")
                continue

        if parsed_files == 0:
            logger.error("No files could be parsed")
            return False

        # Try to persist `multiqc.report` to Redis (or whatever backend
        # cache.set() points at) via cloudpickle, which tolerates the module
        # references that plain pickle chokes on. This lets the parsed report
        # survive uvicorn dev-mode reloads and worker restarts. Fall back to
        # the in-process memory dict if cloudpickle is unavailable or fails
        # for an unforeseen reason — same behaviour as before this change.
        cached_via_cloudpickle = False
        try:
            import cloudpickle  # noqa: PLC0415

            payload = cloudpickle.dumps(multiqc.report)
            cache.set(cache_key, {"__cloudpickle__": payload}, ttl=MULTIQC_CACHE_TTL_SECONDS)
            cached_via_cloudpickle = True
        except Exception as e:
            logger.info(
                f"multiqc.report cloudpickle persist skipped ({e!r}); "
                f"falling back to in-process memory cache"
            )

        if not cached_via_cloudpickle:
            try:
                cache._memory_cache[cache_key] = {
                    "data": multiqc.report,
                    "cached_at": time.time(),
                    "ttl": MULTIQC_CACHE_TTL_SECONDS,
                }
            except Exception as e:
                logger.warning(f"Failed to cache report: {e}")

    return True


def _force_reparse(
    s3_locations: List[str],
    use_s3_cache: bool = True,
    ve: Optional[Exception] = None,
) -> None:
    """Drop the cached ``multiqc.report`` for ``s3_locations`` and re-parse
    from scratch, then write the fresh report back to cache so subsequent
    requests don't re-trigger the same expensive re-parse.

    Caller MUST hold ``_multiqc_lock``. Used by ``create_multiqc_plot`` when
    ``multiqc.get_plot`` raises "Module X is not found" against a restored
    report — the cloudpickle round-trip can land a report with
    ``report.modules`` silently empty.
    """
    import multiqc

    cache = get_cache()
    state_cache_key = _generate_cache_key(s3_locations)
    try:
        cache.delete(state_cache_key)
    except Exception as del_err:
        logger.debug(f"cache.delete failed (non-fatal): {del_err}")
    multiqc.reset()
    parsed = 0
    for loc in s3_locations:
        try:
            local_file = _get_local_path_for_s3(loc, use_cache=use_s3_cache)
            multiqc.parse_logs(local_file)
            parsed += 1
        except Exception as e:
            logger.warning(f"Re-parse error for {loc}: {e}")
    if parsed == 0:
        raise ValueError("Failed to parse any MultiQC data files") from ve
    # Persist the freshly parsed report under the same cache key the original
    # parse used, so the next request lands a hit. Without this, every request
    # for this DC re-takes the lock and re-parses until the underlying
    # cloudpickle issue resolves on its own.
    try:
        import cloudpickle

        payload = cloudpickle.dumps(multiqc.report)
        cache.set(state_cache_key, {"__cloudpickle__": payload}, ttl=MULTIQC_CACHE_TTL_SECONDS)
    except Exception as e:
        logger.info(
            f"_force_reparse: cloudpickle persist after retry skipped ({e!r}); "
            f"in-process state still good"
        )


def create_multiqc_plot(
    s3_locations: List[str],
    module: str,
    plot: str,
    dataset_id: Optional[str] = None,
    use_s3_cache: bool = True,
    theme: str = "light",
    dc_id: Optional[str] = None,
) -> go.Figure:
    """Create a Plotly figure from MultiQC data with figure-level Redis caching.

    Cache layers: Redis figure cache -> in-memory report cache -> full parse.

    Filter-aware caching is layered on top by callers via
    :func:`generate_figure_cache_key` — this helper only caches the unfiltered
    baseline.
    """
    import multiqc

    cache = get_cache()

    # Ensure every parquet is materialised on disk *before* we compute the
    # figure cache key. ``_generate_figure_cache_key`` includes the local
    # file's mtime so that a re-uploaded parquet invalidates the cache —
    # but if we hash on a not-yet-downloaded file, mtime falls back to "0"
    # and we end up writing under a key that no future request can ever
    # look up (the next call sees the real mtime and computes a different
    # key, producing a miss + a re-parse). Ensuring the file is local
    # first keys both writers and readers off the same mtime. Fast no-op
    # when the file is already cached locally.
    for loc in s3_locations:
        try:
            _get_local_path_for_s3(loc, use_cache=use_s3_cache)
        except Exception as e:
            logger.warning(f"Pre-download failed for {loc}: {e}")

    fig_cache_key = _generate_figure_cache_key(
        s3_locations, module, plot, dataset_id, theme, dc_id=dc_id
    )
    cached_fig_dict = cache.get(fig_cache_key)
    if cached_fig_dict is not None:
        return go.Figure(cached_fig_dict)

    # Hold _multiqc_lock across BOTH parse and get_plot so concurrent renders
    # of different DCs don't trample each other's `multiqc.report` global
    # state. _get_or_parse_multiqc_logs uses an RLock so the inner acquire is
    # a no-op recursive lock. Without this, three multiqc components added in
    # the same dashboard render in parallel: the parse-lock releases, another
    # thread restores its own cached report, and the first thread's
    # multiqc.get_plot then sees the wrong report → "Module X is not found".
    with _multiqc_lock:
        parse_success = _get_or_parse_multiqc_logs(s3_locations, use_s3_cache=use_s3_cache)

        if not parse_success:
            raise ValueError("Failed to parse any MultiQC data files")

        # Cloudpickle round-trips the parsed `multiqc.report` for cross-worker
        # reuse, but the restored object can come back without populated
        # `report.modules` (silent loss of `Module` instances). When that
        # happens, get_plot raises "Module X is not found" even though the
        # underlying parquet contains the module. Detect, drop the bad cache
        # entry, force a fresh parse, and retry once.
        try:
            plot_obj = multiqc.get_plot(module, plot)
        except ValueError as ve:
            if "is not found" not in str(ve):
                raise
            logger.warning(
                f"create_multiqc_plot: get_plot('{module}','{plot}') failed "
                f"after parse — invalidating cached multiqc.report and re-parsing"
            )
            _force_reparse(s3_locations, use_s3_cache=use_s3_cache, ve=ve)
            try:
                plot_obj = multiqc.get_plot(module, plot)
            except ValueError as retry_err:
                available: list[str] = []
                try:
                    available = multiqc.list_modules()
                except Exception:
                    pass
                raise ValueError(
                    f"MultiQC module '{module}' not in parsed report after re-parse. "
                    f"s3_locations={s3_locations}, available_modules={available}"
                ) from retry_err

        if not plot_obj or not hasattr(plot_obj, "get_figure"):
            raise ValueError(f"Failed to get plot object for {module}/{plot}")

        fig = plot_obj.get_figure(dataset_id=dataset_id if dataset_id else 0)

    fig.update_layout(
        title=f"{module.upper()}: {plot}",
        template=_get_theme_template(theme),
        autosize=True,
        width=None,
        height=None,
        margin=dict(t=60, l=60, r=60, b=60),
    )

    try:
        cache.set(fig_cache_key, fig.to_dict(), ttl=MULTIQC_CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"Failed to cache figure: {e}")

    return fig


def _filter_heatmap_trace(trace, samples_set: set) -> None:
    """Filter heatmap trace to show only matching samples."""
    x_data = list(trace.x) if trace.x is not None else []
    y_data = list(trace.y) if trace.y is not None else []
    z_data = list(trace.z) if trace.z is not None else []

    x_matches = [i for i, x in enumerate(x_data) if str(x) in samples_set]
    y_matches = [i for i, y in enumerate(y_data) if str(y) in samples_set]

    if y_matches and len(y_matches) >= len(x_matches):
        trace.y = [y_data[i] for i in y_matches]
        if z_data:
            trace.z = [z_data[i] for i in y_matches if i < len(z_data)]
    elif x_matches:
        trace.x = [x_data[i] for i in x_matches]
        if z_data:
            trace.z = [[row[i] for i in x_matches if i < len(row)] for row in z_data]


def _filter_categorical_trace(trace, samples_set: set) -> None:
    """Filter bar/box/violin trace to show only matching samples."""
    if hasattr(trace, "name") and trace.name:
        trace.visible = trace.name in samples_set
        return

    orientation = getattr(trace, "orientation", "v")
    is_horizontal = orientation == "h"

    sample_axis = list(trace.y if is_horizontal else trace.x) or []
    value_axis = list(trace.x if is_horizontal else trace.y) or []

    indices = [i for i, s in enumerate(sample_axis) if str(s) in samples_set]
    if not indices:
        return

    filtered_samples = [sample_axis[i] for i in indices]
    filtered_values = [value_axis[i] for i in indices if i < len(value_axis)]

    if is_horizontal:
        trace.y = filtered_samples
        trace.x = filtered_values
    else:
        trace.x = filtered_samples
        trace.y = filtered_values


def filter_samples_in_plot(fig: go.Figure, samples_to_show: List[str]) -> go.Figure:
    """Filter which samples are visible in a MultiQC plot."""
    try:
        samples_set = set(str(s) for s in samples_to_show)

        for trace in fig.data:
            trace_type = getattr(trace, "type", "").lower()

            if trace_type == "heatmap":
                _filter_heatmap_trace(trace, samples_set)
            elif trace_type in ["bar", "box", "violin"]:
                _filter_categorical_trace(trace, samples_set)
            elif hasattr(trace, "name") and trace.name:
                trace.visible = trace.name in samples_set
            else:
                trace.visible = True

        return fig

    except Exception as e:
        logger.error(f"Error filtering samples in plot: {e}", exc_info=True)
        return fig
