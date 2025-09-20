"""
MultiQC visualization module for Dash components.

This module provides a simple wrapper around MultiQC's plotting functionality,
allowing users to visualize MultiQC reports within Depictio dashboards.
"""

import tempfile
from pathlib import Path
from typing import List, Optional

import fsspec
import plotly.graph_objects as go

from depictio.api.v1.configs.logging_init import logger


def _get_local_path_for_s3(s3_location: str, temp_dir: Path) -> str:
    """
    Download S3 file to temporary directory and return local path.

    Args:
        s3_location: S3 path (s3://bucket/key)
        temp_dir: Temporary directory path

    Returns:
        Local file path
    """
    if not s3_location.startswith("s3://"):
        # Already a local path
        return s3_location

    # Parse S3 path
    path_parts = s3_location.replace("s3://", "").split("/", 1)
    bucket = path_parts[0]
    key = path_parts[1] if len(path_parts) > 1 else ""

    # Preserve the full S3 directory structure in the temp directory
    # e.g., s3://bucket/DCID/MQC_REPORT_ID/multiqc.parquet -> /tmp/tmpXXX/DCID/MQC_REPORT_ID/multiqc.parquet
    local_path = temp_dir / key

    # Create parent directories if they don't exist
    local_path.parent.mkdir(parents=True, exist_ok=True)

    # Download file using fsspec
    try:
        from depictio.api.v1.configs.config import settings

        # Use settings from config
        fs = fsspec.filesystem(
            "s3",
            endpoint_url=settings.minio.endpoint_url,
            key=settings.minio.root_user,
            secret=settings.minio.root_password,
        )
    except ImportError:
        # Fallback to boto3 if s3fs is not available
        import boto3
        from botocore.client import Config

        from depictio.api.v1.configs.config import settings

        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.minio.root_user,
            aws_secret_access_key=settings.minio.root_password,
            endpoint_url=settings.minio.endpoint_url,
            config=Config(signature_version="s3v4"),
        )
        logger.info(f"Downloading {s3_location} to {local_path} using boto3")
        s3_client.download_file(bucket, key, str(local_path))
        return str(local_path)

    logger.info(f"Downloading {s3_location} to {local_path}")
    with fs.open(f"{bucket}/{key}", "rb") as remote_file:
        with open(local_path, "wb") as local_file:
            local_file.write(remote_file.read())

    return str(local_path)


def get_multiqc_modules(s3_location: str) -> List[str]:
    """
    Get available MultiQC modules from a parquet file.

    Args:
        s3_location: S3 path to the MultiQC parquet file

    Returns:
        List of available module names
    """
    try:
        logger.debug("Attempting to import MultiQC in get_multiqc_modules...")
        import multiqc

        logger.debug(
            f"MultiQC imported successfully in get_multiqc_modules. Version: {getattr(multiqc, '__version__', 'unknown')}"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_file = _get_local_path_for_s3(s3_location, temp_path)

            # Reset MultiQC state and load the parquet file
            multiqc.reset()
            multiqc.parse_logs(local_file)

            # Get available modules
            modules = multiqc.list_modules()
            logger.info(f"Found MultiQC modules: {modules}")
            return modules

    except Exception as e:
        logger.error(f"Error getting MultiQC modules: {e}")
        return []


def get_multiqc_plots(s3_location: str, module: str) -> List[str]:
    """
    Get available plots for a specific MultiQC module.

    Args:
        s3_location: S3 path to the MultiQC parquet file
        module: Module name to get plots for

    Returns:
        List of available plot names for the module
    """
    try:
        import multiqc

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_file = _get_local_path_for_s3(s3_location, temp_path)

            # Reset MultiQC state and load the parquet file
            multiqc.reset()
            multiqc.parse_logs(local_file)

            # Get available plots
            all_plots = multiqc.list_plots()
            module_plots = all_plots.get(module, [])

            logger.info(f"Found plots for module {module}: {module_plots}")
            return module_plots

    except Exception as e:
        logger.error(f"Error getting MultiQC plots for module {module}: {e}")
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
    s3_locations: List[str], module: str, plot: str, dataset_id: Optional[str] = None
) -> go.Figure:
    """
    Create a Plotly figure from MultiQC data - SIMPLE VERSION.

    Args:
        s3_locations: List of S3 paths to MultiQC parquet files
        module: MultiQC module name (e.g., 'fastqc')
        plot: Plot name (e.g., 'Sequence Counts')
        dataset_id: Not used in simple version

    Returns:
        Plotly Figure object
    """
    import multiqc

    logger.info(f"Creating simple MultiQC plot: {module}/{plot}")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Reset and parse all files
        multiqc.reset()
        for s3_location in s3_locations:
            local_file = _get_local_path_for_s3(s3_location, temp_path)
            multiqc.parse_logs(local_file)

        # Get first available plot and generate figure
        plot_obj = multiqc.get_plot(module, plot)

        # Type guard: ensure plot_obj has get_figure method
        if not plot_obj or not hasattr(plot_obj, "get_figure"):
            raise ValueError(f"Failed to get plot object for {module}/{plot}")

        if dataset_id:
            fig = plot_obj.get_figure(dataset_id=dataset_id)
        else:
            # Use index 0 for first dataset instead of the dataset object
            fig = plot_obj.get_figure(dataset_id=0)

        # Basic styling
        fig.update_layout(
            title=f"{module.upper()}: {plot}",
            template="plotly_white",
            autosize=True,
            margin=dict(t=60, l=60, r=60, b=60),
        )

        logger.info(f"Created MultiQC plot with {len(fig.data)} traces")
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

        logger.info(f"Filtered plot to show {len(samples_to_show)} samples")
        return fig

    except Exception as e:
        logger.error(f"Error filtering samples in plot: {e}")
        return fig
