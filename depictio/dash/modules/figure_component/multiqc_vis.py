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
) -> str:
    """Generate cache key for a rendered figure, including file mtimes for invalidation."""
    sorted_locations = sorted(s3_locations)

    mtimes = []
    for loc in sorted_locations:
        local_path = _resolve_local_cache_path(loc)
        if local_path and os.path.exists(local_path):
            mtimes.append(str(os.path.getmtime(local_path)))
        elif not loc.startswith("s3://") and os.path.exists(loc):
            mtimes.append(str(os.path.getmtime(loc)))
        else:
            mtimes.append("0")

    key_parts = [
        "|".join(sorted_locations),
        "|".join(mtimes),
        module,
        plot,
        str(dataset_id),
        theme,
    ]
    key_str = "::".join(key_parts)
    hash_digest = hashlib.sha256(key_str.encode()).hexdigest()[:16]
    return f"multiqc:figure:{hash_digest}"


def _get_or_parse_multiqc_logs(s3_locations: List[str], use_s3_cache: bool = True) -> bool:
    """Get cached MultiQC report or parse logs and cache the result.

    Thread-safe: uses global lock since MultiQC global state is not thread-safe.
    """
    import multiqc

    cache_key = _generate_cache_key(s3_locations)
    cache = get_cache()
    cached_report = cache.get(cache_key)

    if cached_report is not None:
        with _multiqc_lock:
            try:
                multiqc.report = cached_report
                return True
            except Exception as e:
                logger.warning(f"Failed to restore cached report: {e}")

    with _multiqc_lock:
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

        # Memory-only cache: multiqc.report contains Python modules that fail pickle
        try:
            cache._memory_cache[cache_key] = {
                "data": multiqc.report,
                "cached_at": time.time(),
                "ttl": 7200,
            }
        except Exception as e:
            logger.warning(f"Failed to cache report: {e}")

    return True


def create_multiqc_plot(
    s3_locations: List[str],
    module: str,
    plot: str,
    dataset_id: Optional[str] = None,
    use_s3_cache: bool = True,
    theme: str = "light",
) -> go.Figure:
    """Create a Plotly figure from MultiQC data with figure-level Redis caching.

    Cache layers: Redis figure cache -> in-memory report cache -> full parse.
    """
    import multiqc

    fig_cache_key = _generate_figure_cache_key(s3_locations, module, plot, dataset_id, theme)
    cache = get_cache()
    cached_fig_dict = cache.get(fig_cache_key)
    if cached_fig_dict is not None:
        return go.Figure(cached_fig_dict)

    parse_success = _get_or_parse_multiqc_logs(s3_locations, use_s3_cache=use_s3_cache)

    if not parse_success:
        raise ValueError("Failed to parse any MultiQC data files")

    plot_obj = multiqc.get_plot(module, plot)
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
        cache.set(fig_cache_key, fig.to_dict(), ttl=7200)
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
