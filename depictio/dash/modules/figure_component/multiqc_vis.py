"""
MultiQC visualization module for Dash components.

This module provides a simple wrapper around MultiQC's plotting functionality,
allowing users to visualize MultiQC reports within Depictio dashboards.
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import fsspec
import plotly.graph_objects as go

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.figure_component.utils import _get_theme_template


def _get_s3_filesystem_config() -> Dict[str, Any]:
    """
    Get S3 filesystem configuration from settings.

    Returns:
        Dictionary with S3 configuration parameters
    """
    config = {
        "endpoint_url": settings.minio.endpoint_url,
        "key": settings.minio.root_user,
        "secret": settings.minio.root_password,
    }
    logger.debug(f"S3 filesystem config: endpoint={config['endpoint_url']}, user={config['key']}")
    return config


def _get_s3_filesystem():
    """
    Create a simple S3 filesystem for direct file operations.

    Returns:
        S3 filesystem instance
    """
    s3_config = _get_s3_filesystem_config()
    return fsspec.filesystem("s3", **s3_config)


def _check_s3_fuse_mount(s3_location: str) -> Optional[str]:
    """
    Check if S3 is FUSE-mounted and return local path if available.

    This is the most efficient method as it provides direct filesystem access
    without any downloading or caching.

    Args:
        s3_location: S3 path (s3://bucket/key)

    Returns:
        Local mounted path if available, None otherwise
    """
    # Parse S3 path
    path_parts = s3_location.replace("s3://", "").split("/", 1)
    bucket = path_parts[0]
    key = path_parts[1] if len(path_parts) > 1 else ""

    # Get mount points from settings
    mount_points = (
        settings.s3_cache.mount_points.split(",") if settings.s3_cache.mount_points else []
    )

    # Check configured mount points
    for mount_point in mount_points:
        # Try both /mount/bucket/key and /mount/key patterns
        potential_paths = [
            os.path.join(mount_point, bucket, key),  # /mnt/s3/bucket/key
            os.path.join(mount_point, key),  # /mnt/s3/key (if bucket is mount point)
        ]

        for local_path in potential_paths:
            if os.path.exists(local_path):
                logger.info(f"Found S3 FUSE mount: {s3_location} -> {local_path}")
                return local_path

    logger.debug(f"No S3 FUSE mount found for {s3_location}")
    return None


def _get_local_path_for_s3(s3_location: str, use_cache: bool = True) -> str:
    """
    Get a local path for S3 file using fsspec caching mechanisms.

    Since MultiQC requires actual file paths (not file handles), we use
    filecache which downloads and caches entire files locally.

    Args:
        s3_location: S3 path (s3://bucket/key) or local path
        use_cache: Whether to use caching (default True)

    Returns:
        Local file path that can be accessed by MultiQC
    """
    if not s3_location.startswith("s3://"):
        logger.debug(f"Path is already local: {s3_location}")
        return s3_location

    logger.info(f"Processing S3 location: {s3_location}")

    # First, check if S3 is FUSE-mounted (most efficient)
    fuse_path = _check_s3_fuse_mount(s3_location)
    if fuse_path:
        return fuse_path

    if not use_cache:
        logger.info("Cache disabled, falling back to direct download")
        return _download_s3_file_direct(s3_location)

    try:
        # Get S3 filesystem for operations
        fs = _get_s3_filesystem()

        # First, ensure the file exists and is accessible
        logger.debug(f"Checking S3 file existence: {s3_location}")
        if not fs.exists(s3_location):
            raise FileNotFoundError(f"S3 file does not exist: {s3_location}")

        # Get file info for logging
        file_info = fs.info(s3_location)
        file_size = file_info.get("size", 0)
        logger.info(f"S3 file found - size: {file_size} bytes")

        # For MultiQC compatibility, we need an actual file path.
        # Since fsspec's caching doesn't reliably provide local paths,
        # we'll use a simpler approach: download to a persistent cache directory

        # Create a cache directory structure that mirrors S3
        cache_base = settings.s3_cache.cache_dir
        os.makedirs(cache_base, exist_ok=True)

        # Parse S3 path to create cache path
        path_parts = s3_location.replace("s3://", "").split("/", 1)
        bucket = path_parts[0]
        key = path_parts[1] if len(path_parts) > 1 else ""

        # Create cache path that mirrors S3 structure
        cache_path = os.path.join(cache_base, bucket, key)
        cache_dir = os.path.dirname(cache_path)
        os.makedirs(cache_dir, exist_ok=True)

        # Check if file is already cached and fresh
        if os.path.exists(cache_path):
            # Check if cached file is still valid (compare size with S3)
            cached_size = os.path.getsize(cache_path)
            if cached_size == file_size:
                logger.info(f"Using cached file (size match): {cache_path}")
                return cache_path
            else:
                logger.info(f"Cache size mismatch ({cached_size} != {file_size}), re-downloading")
                os.remove(cache_path)

        # Download file to cache location
        logger.info(f"Downloading to cache: {s3_location} -> {cache_path}")
        try:
            fs.get(s3_location, cache_path)
            logger.info(f"Successfully cached S3 file at: {cache_path}")
            return cache_path
        except Exception as download_error:
            logger.error(f"Failed to download to cache: {download_error}")
            # Clean up partial download
            if os.path.exists(cache_path):
                os.remove(cache_path)
            # Fall back to temporary download
            return _download_s3_file_direct(s3_location)

    except Exception as e:
        logger.error(f"Failed to access S3 file with caching: {e}")
        logger.info("Falling back to direct download method")
        return _download_s3_file_direct(s3_location)


def _download_s3_file_direct(s3_location: str) -> str:
    """
    Direct download of S3 file to temporary location (fallback method).

    Args:
        s3_location: S3 path (s3://bucket/key)

    Returns:
        Local file path
    """
    logger.info(f"Direct download of S3 file: {s3_location}")

    # Parse S3 path
    path_parts = s3_location.replace("s3://", "").split("/", 1)
    key = path_parts[1] if len(path_parts) > 1 else ""

    # Create temporary file with proper extension
    file_extension = Path(key).suffix or ".tmp"
    temp_file = tempfile.NamedTemporaryFile(suffix=file_extension, delete=False)
    local_path = temp_file.name
    temp_file.close()

    logger.debug(f"Downloading {s3_location} to {local_path}")

    try:
        s3_config = _get_s3_filesystem_config()
        fs = fsspec.filesystem("s3", **s3_config)

        # Check file exists and get size for progress logging
        if fs.exists(s3_location):
            file_info = fs.info(s3_location)
            file_size = file_info.get("size", "unknown")
            logger.info(f"Downloading file of size: {file_size} bytes")
        else:
            raise FileNotFoundError(f"S3 file does not exist: {s3_location}")

        # Download file
        fs.get(s3_location, local_path)
        logger.info(f"Successfully downloaded S3 file to: {local_path}")

        return local_path

    except Exception as e:
        # Clean up failed download
        try:
            os.unlink(local_path)
        except OSError:
            pass
        logger.error(f"Failed to download S3 file directly: {e}")
        raise


def get_multiqc_modules(s3_location: str, use_s3_cache: bool = True) -> List[str]:
    """
    Get available MultiQC modules from a parquet file.

    Args:
        s3_location: S3 path to the MultiQC parquet file

    Returns:
        List of available module names
    """
    logger.info(f"Getting MultiQC modules from: {s3_location}")

    try:
        logger.debug("Attempting to import MultiQC in get_multiqc_modules...")
        import multiqc

        logger.debug(
            f"MultiQC imported successfully in get_multiqc_modules. Version: {getattr(multiqc, '__version__', 'unknown')}"
        )

        # Get local path using S3 mounting/caching
        local_file = _get_local_path_for_s3(s3_location, use_cache=use_s3_cache)
        logger.debug(f"Using local file path: {local_file}")

        # Reset MultiQC state and load the parquet file
        logger.debug("Resetting MultiQC state")
        multiqc.reset()

        logger.debug(f"Parsing MultiQC logs from: {local_file}")
        multiqc.parse_logs(local_file)

        # Get available modules
        logger.debug("Retrieving available MultiQC modules")
        modules = multiqc.list_modules()
        logger.info(f"Found {len(modules)} MultiQC modules: {modules}")
        return modules

    except Exception as e:
        logger.error(f"Error getting MultiQC modules from {s3_location}: {e}", exc_info=True)
        return []


def get_multiqc_plots(s3_location: str, module: str, use_s3_cache: bool = True) -> List[str]:
    """
    Get available plots for a specific MultiQC module.

    Args:
        s3_location: S3 path to the MultiQC parquet file
        module: Module name to get plots for

    Returns:
        List of available plot names for the module
    """
    logger.info(f"Getting MultiQC plots for module '{module}' from: {s3_location}")

    try:
        import multiqc

        # Get local path using S3 mounting/caching
        local_file = _get_local_path_for_s3(s3_location, use_cache=use_s3_cache)
        logger.debug(f"Using local file path: {local_file}")

        # Reset MultiQC state and load the parquet file
        logger.debug("Resetting MultiQC state")
        multiqc.reset()

        logger.debug(f"Parsing MultiQC logs from: {local_file}")
        multiqc.parse_logs(local_file)

        # Get available plots
        logger.debug("Retrieving all available MultiQC plots")
        all_plots = multiqc.list_plots()
        module_plots = all_plots.get(module, [])

        logger.info(f"Found {len(module_plots)} plots for module {module}: {module_plots}")
        return module_plots

    except Exception as e:
        logger.error(
            f"Error getting MultiQC plots for module {module} from {s3_location}: {e}",
            exc_info=True,
        )
        return []


def get_multiqc_plots_from_metadata(metadata_plots: dict, module: str) -> List[str]:
    """
    Get available plots for a specific MultiQC module from metadata.

    Args:
        metadata_plots: The plots dictionary from MultiQC metadata
        module: Module name to get plots for

    Returns:
        List of available plot names for the module
    """
    try:
        module_plots = metadata_plots.get(module, [])

        # Extract plot names from the metadata structure
        plot_names = []
        for plot_item in module_plots:
            if isinstance(plot_item, str):
                # Simple plot name
                plot_names.append(plot_item)
            elif isinstance(plot_item, dict):
                # Plot with sub-options, use the key as plot name
                for plot_name in plot_item.keys():
                    plot_names.append(plot_name)

        logger.info(f"Found plots for module {module} from metadata: {plot_names}")
        return plot_names

    except Exception as e:
        logger.error(f"Error getting MultiQC plots for module {module} from metadata: {e}")
        return []


def get_multiqc_datasets(metadata_plots: dict, module: str, plot: str) -> List[str]:
    """
    Get available datasets for a specific MultiQC plot from metadata.

    This function extracts dataset IDs from the plots metadata structure where
    some plots have sub-options like:
    {"Per Sequence GC Content": ["Percentages", "Counts"]}

    Args:
        metadata_plots: The plots dictionary from MultiQC metadata
        module: Module name
        plot: Plot name

    Returns:
        List of available dataset IDs for the plot
    """
    try:
        datasets = []

        # Get the plots for this module
        module_plots = metadata_plots.get(module, [])

        # Look for the specific plot
        for plot_item in module_plots:
            if isinstance(plot_item, dict):
                # This is a plot with sub-options (datasets)
                for plot_name, plot_datasets in plot_item.items():
                    if plot_name == plot and isinstance(plot_datasets, list):
                        datasets = plot_datasets
                        break
            elif isinstance(plot_item, str) and plot_item == plot:
                # This is a simple plot without datasets
                datasets = []
                break

        logger.info(f"Found datasets for {module}/{plot}: {datasets}")
        return datasets

    except Exception as e:
        logger.error(f"Error getting MultiQC datasets for {module}/{plot}: {e}")
        return []


def create_multiqc_plot(
    s3_locations: List[str],
    module: str,
    plot: str,
    dataset_id: Optional[str] = None,
    use_s3_cache: bool = True,
    theme: str = "light",
) -> go.Figure:
    """
    Create a Plotly figure from MultiQC data - SIMPLE VERSION.

    Args:
        s3_locations: List of S3 paths to MultiQC parquet files
        module: MultiQC module name (e.g., 'fastqc')
        plot: Plot name (e.g., 'Sequence Counts')
        dataset_id: Not used in simple version
        use_s3_cache: Whether to use S3 caching (default True)
        theme: Theme for plot styling - "light" or "dark" (default "light")

    Returns:
        Plotly Figure object
    """
    import multiqc

    logger.info(f"Creating MultiQC plot: {module}/{plot} from {len(s3_locations)} files")
    logger.debug(f"S3 locations: {s3_locations}")

    # Reset MultiQC state
    logger.debug("Resetting MultiQC state")
    multiqc.reset()

    # Parse all files
    parsed_files = 0
    local_files = []

    for i, s3_location in enumerate(s3_locations):
        logger.info(f"Processing file {i + 1}/{len(s3_locations)}: {s3_location}")
        try:
            # Get local path using S3 mounting/caching
            local_file = _get_local_path_for_s3(s3_location, use_cache=use_s3_cache)
            local_files.append(local_file)
            logger.debug(f"Using local file path: {local_file}")

            # Parse the file
            logger.debug(f"Parsing MultiQC logs from: {local_file}")
            multiqc.parse_logs(local_file)
            parsed_files += 1
            logger.info(f"Successfully parsed file {i + 1}: {s3_location}")

        except Exception as e:
            logger.warning(f"Error parsing MultiQC file {i + 1} from {s3_location}: {e}")
            # Continue with other files if one fails
            continue

    # Check if we successfully parsed any files
    if parsed_files == 0:
        logger.error("No MultiQC files could be parsed successfully")
        raise ValueError("Failed to parse any MultiQC data files")

    logger.info(f"Successfully parsed {parsed_files}/{len(s3_locations)} MultiQC files")

    # Get plot object and generate figure
    logger.debug(f"Getting plot object for {module}/{plot}")
    plot_obj = multiqc.get_plot(module, plot)

    # Type guard: ensure plot_obj has get_figure method
    if not plot_obj or not hasattr(plot_obj, "get_figure"):
        logger.error(f"Failed to get valid plot object for {module}/{plot}")
        raise ValueError(f"Failed to get plot object for {module}/{plot}")

    logger.debug("Plot object retrieved successfully, generating figure")

    try:
        if dataset_id:
            logger.debug(f"Creating figure with dataset_id: {dataset_id}")
            fig = plot_obj.get_figure(dataset_id=dataset_id)
        else:
            # Use index 0 for first dataset instead of the dataset object
            logger.debug("Creating figure with dataset_id: 0")
            fig = plot_obj.get_figure(dataset_id=0)
    except Exception as e:
        logger.error(f"Error generating figure: {e}")
        raise

    # Basic styling with theme support
    logger.debug(f"Applying styling to figure with theme: {theme}")
    fig.update_layout(
        title=f"{module.upper()}: {plot}",
        template=_get_theme_template(theme),
        autosize=True,
        margin=dict(t=60, l=60, r=60, b=60),
    )

    logger.info(f"Successfully created MultiQC plot with {len(fig.data)} traces")

    # Clean up temporary files if direct download was used
    for local_file in local_files:
        if local_file.startswith(tempfile.gettempdir()):
            try:
                os.unlink(local_file)
                logger.debug(f"Cleaned up temporary file: {local_file}")
            except Exception as cleanup_error:
                logger.debug(f"Could not clean up temporary file {local_file}: {cleanup_error}")

    return fig


def filter_samples_in_plot(fig: go.Figure, samples_to_show: List[str]) -> go.Figure:
    """
    Filter which samples are visible in a MultiQC plot.

    Args:
        fig: Plotly figure to filter
        samples_to_show: List of sample names to keep visible

    Returns:
        Modified Plotly figure with filtered samples
    """
    try:
        # Hide traces that don't match the samples to show
        for trace in fig.data:
            if hasattr(trace, "name") and trace.name:
                # Show trace if its name is in the samples list
                trace.visible = trace.name in samples_to_show
            else:
                # Keep traces without names visible (usually summary data)
                trace.visible = True

        visible_traces = sum(1 for trace in fig.data if getattr(trace, "visible", True))
        logger.info(
            f"Filtered plot to show {len(samples_to_show)} samples ({visible_traces} visible traces)"
        )
        return fig

    except Exception as e:
        logger.error(f"Error filtering samples in plot: {e}", exc_info=True)
        return fig
