from typing import Any

import httpx
import plotly.graph_objects as go
from dash import dcc, html

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger


def analyze_multiqc_plot_structure(fig: go.Figure) -> dict:
    """
    Analyze how samples are represented in the MultiQC plot and store original data.

    This function preserves the original trace data (x, y, z arrays and orientation)
    which is essential for proper patching operations when filtering by samples.

    Args:
        fig: Plotly Figure object to analyze

    Returns:
        Dictionary containing original trace data and summary information
    """
    if not fig or not hasattr(fig, "data"):
        return {"original_data": [], "summary": "No data"}

    # Store complete original data for each trace
    original_data = []
    trace_types = []
    sample_mapping = []

    for i, trace in enumerate(fig.data):
        trace_info = {
            "index": i,
            "type": trace.type if hasattr(trace, "type") else "",
            "name": trace.name if hasattr(trace, "name") else "",
            "orientation": trace.orientation if hasattr(trace, "orientation") else "v",
            # Store original data as tuples or lists (preserve type for Plotly compatibility)
            "original_x": (
                tuple(trace.x)
                if hasattr(trace, "x") and trace.x is not None and isinstance(trace.x, tuple)
                else (list(trace.x) if hasattr(trace, "x") and trace.x is not None else [])
            ),
            "original_y": (
                tuple(trace.y)
                if hasattr(trace, "y") and trace.y is not None and isinstance(trace.y, tuple)
                else (list(trace.y) if hasattr(trace, "y") and trace.y is not None else [])
            ),
            "original_z": (
                tuple(trace.z)
                if hasattr(trace, "z") and trace.z is not None and isinstance(trace.z, tuple)
                else (list(trace.z) if hasattr(trace, "z") and trace.z is not None else [])
            ),
        }
        original_data.append(trace_info)

        # Collect metadata for display
        trace_types.append(trace.type if hasattr(trace, "type") else "unknown")
        if hasattr(trace, "name") and trace.name:
            sample_mapping.append(trace.name)

    # Create summary for display
    unique_types = list(set(trace_types))
    summary = {
        "traces": len(original_data),
        "types": ", ".join(unique_types),
        "samples_in_traces": len(sample_mapping),
        "sample_names": ", ".join(sample_mapping[:3]) + ("..." if len(sample_mapping) > 3 else ""),
    }

    logger.debug(
        f"Analyzed MultiQC plot: {summary['traces']} traces, "
        f"types: {summary['types']}, samples: {summary['samples_in_traces']}"
    )

    return {"original_data": original_data, "summary": summary}


def add_multiqc_logo_overlay(fig, logo_size_px=45):
    """Add MultiQC logo overlay to any plotly figure using Dash assets"""

    try:
        # Use Dash assets URL - this will work in web deployment
        # Dash automatically serves files from assets/ directory
        logo_url = "/assets/images/logos/multiqc.png"

        # Get figure dimensions
        width = fig.layout.width or 700
        height = fig.layout.height or 450
        sizex = logo_size_px / width
        sizey = logo_size_px / height

        # Add logo overlay (top-right corner) using assets URL
        fig.add_layout_image(
            dict(
                source=logo_url,  # Dash assets URL
                xref="paper",
                yref="paper",
                x=0.95,
                y=0.95,  # Top-right corner
                sizex=sizex,
                sizey=sizey,
                xanchor="right",
                yanchor="top",
                opacity=0.6,
                layer="above",
            )
        )

        logger.debug("Added MultiQC logo overlay using Dash assets")

    except Exception as e:
        logger.warning(f"Failed to add MultiQC logo overlay: {e}")

    return fig


def build_multiqc(**kwargs: Any):
    """
    Build MultiQC component for dashboard display - PLOT ONLY (no controls).

    Args:
        **kwargs: Component metadata including selected_module, selected_plot, selected_dataset, s3_locations

    Returns:
        Dash component with MultiQC plot and metadata store
    """

    logger.info(f"Building MultiQC plot component with kwargs keys: {list(kwargs.keys())}")

    # Extract required parameters
    component_id = kwargs.get("index", "multiqc-component")
    selected_module = kwargs.get("selected_module")
    selected_plot = kwargs.get("selected_plot")
    selected_dataset = kwargs.get("selected_dataset")
    s3_locations = kwargs.get("s3_locations", [])
    stepper = kwargs.get("stepper", False)
    theme = kwargs.get("theme", "light")

    # Metadata management - Create a store component to store the metadata (following card pattern)
    # For stepper mode, use the temporary index to avoid conflicts with existing components
    # For normal mode, use the original index (remove -tmp suffix if present)
    if stepper:
        component_id = f"{component_id}-tmp"  # Apply -tmp suffix once here
        store_index = component_id  # Use the temporary index with -tmp suffix
        data_index = (
            component_id.replace("-tmp", "") if component_id else "unknown"
        )  # Clean index for data
    else:
        store_index = component_id.replace("-tmp", "") if component_id else "unknown"
        data_index = store_index

    # Create comprehensive metadata for the component including interactive filtering support
    component_metadata = {
        "index": str(data_index),
        "component_type": "multiqc",
        "workflow_id": kwargs.get("workflow_id"),
        "data_collection_id": kwargs.get("data_collection_id"),
        "wf_id": kwargs.get("workflow_id"),  # Alias for compatibility
        "dc_id": kwargs.get("data_collection_id"),  # Alias for compatibility
        "selected_module": selected_module,
        "selected_plot": selected_plot,
        "selected_dataset": selected_dataset,
        "s3_locations": s3_locations,
        # Additional metadata needed for interactive filtering
        "metadata": kwargs.get("metadata", {}),  # MultiQC metadata (modules, plots, samples)
        "interactive_patching_enabled": True,  # Flag to enable interactive patching
    }

    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": str(store_index),
        },
        data=component_metadata,
    )

    # Initialize trace metadata store (empty by default)
    trace_metadata_store = dcc.Store(
        id={"type": "multiqc-trace-metadata", "index": str(component_id)},
        data={},
    )

    # Check if we have the minimum required information for a plot
    if not selected_module or not selected_plot or not s3_locations:
        plot_component = dcc.Graph(
            id={"type": "multiqc-graph", "index": str(component_id)},
            figure={
                "data": [],
                "layout": {
                    "title": "MultiQC Component - Configure in edit mode",
                    "xaxis": {"visible": False},
                    "yaxis": {"visible": False},
                    "annotations": [
                        {
                            "text": "No data available",
                            "xref": "paper",
                            "yref": "paper",
                            "x": 0.5,
                            "y": 0.5,
                            "showarrow": False,
                            "font": {"size": 16, "color": "gray"},
                        }
                    ],
                },
            },
            style={"height": "100%", "width": "100%"},
        )
    else:
        # Lazy loading: return placeholder and trigger background generation
        plot_component = html.Div(
            id={"type": "multiqc-plot-wrapper", "index": str(component_id)},
            style={
                "position": "relative",
                "height": "100%",
                "width": "100%",
                "flex": "1",  # CRITICAL: Grow to take all space in flex parent
                "display": "flex",
                "flexDirection": "column",
            },
            children=[
                # Actual dcc.Graph component - will be populated by background callback via figure property
                dcc.Graph(
                    id={"type": "multiqc-graph", "index": str(component_id)},
                    figure={
                        "data": [],
                        "layout": {
                            "title": "Loading MultiQC plot...",
                            "xaxis": {"visible": False},
                            "yaxis": {"visible": False},
                        },
                    },
                    style={
                        "width": "100%",
                        "height": "100%",
                        "flex": "1",  # CRITICAL: Grow within flex parent
                        "minHeight": "300px",  # Ensure minimum height
                    },
                    config={"displayModeBar": "hover", "responsive": True},
                ),
                # MultiQC logo overlay - CSS positioned for consistent size across all plots
                html.Img(
                    src="/assets/images/logos/multiqc.png",
                    style={
                        "position": "absolute",
                        "top": "10px",
                        "right": "10px",
                        "width": "40px",
                        "height": "40px",
                        "opacity": "0.6",
                        "pointerEvents": "none",
                        "zIndex": "1000",
                    },
                    title="Generated with MultiQC",
                ),
                # Trigger store for background callback
                dcc.Store(
                    id={"type": "multiqc-trigger", "index": str(component_id)},
                    data={
                        "s3_locations": s3_locations,
                        "module": selected_module,
                        "plot": selected_plot,
                        "dataset_id": selected_dataset,
                        "theme": theme,
                        "component_id": str(component_id),
                    },
                ),
            ],
        )

    # Return container with plot, stores, and trace metadata (following card pattern)
    # CRITICAL: Add the component ID so enable_box_edit_mode can extract it properly
    # CRITICAL: Add flexbox-compatible styling so component is visible in edit mode
    logger.error(
        f"🔨 MULTIQC BUILD RETURNING - Component ID: {component_id}, "
        f"Plot wrapper type: {type(plot_component).__name__}, "
        f"Has stores: store={store_component is not None}, trace={trace_metadata_store is not None}"
    )

    return html.Div(
        [plot_component, store_component, trace_metadata_store],
        id=component_id,
        style={
            "width": "100%",
            "height": "100%",
            "flex": "1",  # CRITICAL: Grow within flex parent
            "display": "flex",
            "flexDirection": "column",
            "overflow": "hidden",
            "minHeight": "300px",  # Ensure minimum height
            "backgroundColor": "rgba(255, 0, 0, 0.1)",  # DEBUG: Red tint to see if visible
        },
    )


def get_multiqc_reports_for_data_collection(data_collection_id: str, token: str) -> list:
    """
    Retrieve MultiQC reports for a specific data collection.

    Args:
        data_collection_id: The ID of the data collection
        token: Authentication token

    Returns:
        List of MultiQC reports
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/multiqc/reports/data-collection/{data_collection_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

        if response.status_code == 200:
            data = response.json()
            reports = data.get("reports", [])
            logger.info(
                f"Retrieved {len(reports)} MultiQC reports for data collection {data_collection_id}"
            )
            return reports
        else:
            logger.warning(
                f"Failed to retrieve MultiQC reports: {response.status_code} - {response.text}"
            )
            return []

    except Exception as e:
        logger.error(f"Error retrieving MultiQC reports: {str(e)}")
        return []


def get_multiqc_report_metadata(report_id: str, token: str) -> dict:
    """
    Get metadata for a specific MultiQC report.

    Args:
        report_id: The ID of the MultiQC report
        token: Authentication token

    Returns:
        Dictionary containing report metadata
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/multiqc/reports/{report_id}/metadata",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

        if response.status_code == 200:
            metadata = response.json()
            logger.info(f"Retrieved metadata for MultiQC report {report_id}")
            return metadata
        else:
            logger.warning(
                f"Failed to retrieve MultiQC report metadata: {response.status_code} - {response.text}"
            )
            return {}

    except Exception as e:
        logger.error(f"Error retrieving MultiQC report metadata: {str(e)}")
        return {}


def check_multiqc_data_availability(data_collection_id: str, token: str) -> dict:
    """
    Check if MultiQC data is available for a data collection.

    Args:
        data_collection_id: The ID of the data collection
        token: Authentication token

    Returns:
        Dictionary with availability status and details
    """
    try:
        # Check for MultiQC reports
        reports = get_multiqc_reports_for_data_collection(data_collection_id, token)

        # Get data collection info to verify it's a MultiQC type
        dc_response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/{data_collection_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

        dc_info = {}
        if dc_response.status_code == 200:
            dc_info = dc_response.json()

        dc_type = dc_info.get("config", {}).get("type", "").lower()

        return {
            "available": len(reports) > 0,
            "report_count": len(reports),
            "is_multiqc_type": dc_type == "multiqc",
            "data_collection_info": dc_info,
            "reports": reports,
        }

    except Exception as e:
        logger.error(f"Error checking MultiQC data availability: {str(e)}")
        return {
            "available": False,
            "report_count": 0,
            "is_multiqc_type": False,
            "error": str(e),
        }


def format_multiqc_summary(reports: list, metadata: dict | None = None) -> dict:
    """
    Format MultiQC data for display in the component.

    Args:
        reports: List of MultiQC reports
        metadata: Optional metadata dictionary

    Returns:
        Formatted summary information
    """
    if not reports:
        return {
            "total_reports": 0,
            "total_samples": 0,
            "modules": [],
            "summary": "No MultiQC reports available",
        }

    try:
        # Extract information from reports and metadata
        total_reports = len(reports)

        # Get sample and module information from metadata if available
        if metadata:
            samples = metadata.get("samples", [])
            modules = metadata.get("modules", [])
            plots = metadata.get("plots", {})
        else:
            # Try to extract from first report if metadata not provided
            first_report = reports[0]
            report_metadata = first_report.get("metadata", {})
            samples = report_metadata.get("samples", [])
            modules = report_metadata.get("modules", [])
            plots = report_metadata.get("plots", {})

        total_samples = len(samples)

        # Create summary text
        summary_parts = [f"{total_reports} report{'s' if total_reports != 1 else ''}"]
        if total_samples > 0:
            summary_parts.append(f"{total_samples} sample{'s' if total_samples != 1 else ''}")
        if modules:
            summary_parts.append(f"{len(modules)} module{'s' if len(modules) != 1 else ''}")

        summary = " • ".join(summary_parts)

        return {
            "total_reports": total_reports,
            "total_samples": total_samples,
            "modules": modules,
            "plots": plots,
            "samples": samples,
            "summary": summary,
        }

    except Exception as e:
        logger.error(f"Error formatting MultiQC summary: {str(e)}")
        return {
            "total_reports": len(reports),
            "total_samples": 0,
            "modules": [],
            "summary": f"Error formatting summary: {str(e)}",
        }
