"""MultiQC Component - Core Rendering Callbacks.

This module contains callbacks essential for rendering MultiQC components in view mode.
These callbacks are always loaded at app startup and work with saved dashboard components.

Callbacks:
    - render_multiqc_from_trigger: Render plot in view mode (existing dashboards)
    - patch_multiqc_plot_with_interactive_filtering: Apply interactive filters to MultiQC plots

Design-mode callbacks (module/plot/dataset selectors) are in design.py and only loaded
when editing/creating components.

Helper functions:
    - _normalize_multiqc_paths: Support both S3 and local filesystem paths
    - _extract_sample_filters: Extract sample filtering from interactive components
    - _create_error_figure: Create error figure with message
"""

import copy
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import dash
import polars as pl
from dash import ALL, MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.background_callback_helpers import should_use_background_for_component
from depictio.dash.modules.figure_component.multiqc_vis import create_multiqc_plot
from depictio.dash.modules.multiqc_component.utils import (
    analyze_multiqc_plot_structure,
    resolve_bson_id,
)
from depictio.dash.utils import (
    enrich_interactive_components_with_metadata,
    get_multiqc_sample_mappings,
    get_result_dc_for_workflow,
    resolve_link_values,
)

# Use centralized background callback configuration
USE_BACKGROUND_CALLBACKS = should_use_background_for_component("multiqc")


def _create_error_figure(title: str, message: Optional[str] = None) -> dict:
    """Create a Plotly figure dict displaying an error.

    Args:
        title: The title to display (also used as error heading).
        message: Optional additional error message for annotation.

    Returns:
        Plotly figure dict with error display.
    """
    layout = {"title": title, "data": []}
    if message:
        layout["annotations"] = [
            {
                "text": message,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"size": 16},
            }
        ]
    return {"data": [], "layout": layout}


def _normalize_multiqc_paths(locations: List[str]) -> List[str]:
    """
    Normalize MultiQC data paths - support both S3 and local filesystem.

    This helper provides backward compatibility during migration from S3 to local FS:
    - Phase 1: Support both S3 and local paths (this implementation)
    - Phase 2: CLI writes to local FS instead of MinIO
    - Phase 3: Remove S3 support once migration complete

    Args:
        locations: List of paths (S3 URIs like 's3://bucket/key' or local paths like '/data/...')

    Returns:
        List of normalized paths ready for use

    Strategy:
    - If path starts with 's3://', keep as-is (backward compat, log warning)
    - If path starts with '/', it's local - verify existence and use directly
    - If relative path, resolve to absolute

    Note: For production K8s deployment, use shared PersistentVolume mounted
    at /data/depictio. CLI and Dash pods both mount same volume for direct
    file access without S3/network overhead.
    """
    if not locations:
        return []

    normalized = []

    for location in locations:
        if not location:
            continue

        if location.startswith("s3://"):
            logger.warning(f"S3 path detected (use local FS for production): {location}")
            normalized.append(location)
        elif location.startswith("/"):
            if not os.path.exists(location):
                logger.error(f"Local file path does not exist: {location}")
            normalized.append(location)
        else:
            abs_path = os.path.abspath(location)
            logger.debug(f"Resolved relative path: {location} -> {abs_path}")
            normalized.append(abs_path)

    return normalized


def _extract_sample_filters(
    filter_values: Optional[Dict[str, Any]],
    interactive_metadata_list: List[Dict],
    component_metadata: Dict,
) -> Optional[List[str]]:
    """
    Extract sample filtering from interactive components.

    Integrates MultiQC component with interactive components for sample filtering.
    When interactive component targets same DC as MultiQC, apply sample filter.

    Args:
        filter_values: Filter state from interactive-values-store
        interactive_metadata_list: List of all interactive component metadata
        component_metadata: This MultiQC component's metadata

    Returns:
        List of selected sample names to filter to, or None if no filtering
    """
    if not filter_values or not interactive_metadata_list:
        return None

    # Get MultiQC component's DC
    multiqc_dc_id = component_metadata.get("dc_id") or component_metadata.get("data_collection_id")

    if not multiqc_dc_id:
        return None

    filtered_samples = None

    for interactive_meta in interactive_metadata_list:
        if not interactive_meta:
            continue

        interactive_dc_id = interactive_meta.get("dc_id") or interactive_meta.get(
            "data_collection_id"
        )

        if str(interactive_dc_id) != str(multiqc_dc_id):
            continue

        interactive_id = interactive_meta.get("index")
        if interactive_id and interactive_id in filter_values:
            selected_samples = filter_values[interactive_id]
            if isinstance(selected_samples, list) and selected_samples:
                filtered_samples = selected_samples
                break

    return filtered_samples


def expand_canonical_samples_to_variants(
    canonical_samples: List[str], sample_mappings: Dict[str, List[str]]
) -> List[str]:
    """
    Expand canonical sample IDs to all their MultiQC variants using stored mappings.

    Args:
        canonical_samples: List of canonical sample IDs from external metadata (e.g., ['SRR10070130'])
        sample_mappings: Dictionary mapping canonical IDs to variants
                        (e.g., {'SRR10070130': ['SRR10070130', 'SRR10070130_1', ...]})

    Returns:
        List of all sample variants to filter MultiQC plots
    """
    if not sample_mappings:
        logger.warning("No sample mappings available - returning canonical samples as-is")
        return canonical_samples

    expanded_samples = []
    for canonical_id in canonical_samples:
        variants = sample_mappings.get(canonical_id, [])
        if variants:
            expanded_samples.extend(variants)
        else:
            expanded_samples.append(canonical_id)

    return expanded_samples


def get_samples_from_metadata_filter(
    workflow_id: str,
    metadata_dc_id: str,
    join_column: str,
    interactive_components_dict: Dict[str, Any],
    token: str,
) -> List[str]:
    """
    Get sample names from filtered metadata table.

    Args:
        workflow_id: Workflow ID
        metadata_dc_id: Metadata data collection ID
        join_column: Column name containing sample identifiers (e.g., 'sample')
        interactive_components_dict: Filters to apply {component_index: {value, metadata}}
        token: Auth token

    Returns:
        List of canonical sample names that match the filters (not expanded to variants)
    """
    from bson import ObjectId

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    df = load_deltatable_lite(
        workflow_id=ObjectId(workflow_id),
        data_collection_id=ObjectId(metadata_dc_id),
        metadata=None,
        TOKEN=token,
    )

    if df is None or df.is_empty():
        logger.warning("Metadata table is empty")
        return []

    # Apply filters from interactive components
    for comp_data in interactive_components_dict.values():
        comp_metadata = comp_data.get("metadata", {})
        column_name = comp_metadata.get("column_name")
        filter_values = comp_data.get("value", [])

        if column_name and filter_values and column_name in df.columns:
            column_dtype = df[column_name].dtype
            default_state = comp_metadata.get("default_state", {})
            default_range = default_state.get("default_range")

            if column_dtype in (pl.Date, pl.Datetime):
                if default_range and filter_values == default_range:
                    continue

                try:
                    parsed_dates = [
                        datetime.strptime(str(v), "%Y-%m-%d").date() for v in filter_values
                    ]
                    df = df.filter(pl.col(column_name).is_in(parsed_dates))
                except Exception:
                    try:
                        string_values = [str(v) for v in filter_values]
                        df = df.filter(
                            pl.col(column_name).dt.strftime("%Y-%m-%d").is_in(string_values)
                        )
                    except Exception as e2:
                        logger.error(f"Failed to filter Date column '{column_name}': {e2}")

            elif isinstance(filter_values, (list, tuple)) and len(filter_values) == 2:
                try:
                    min_val, max_val = float(filter_values[0]), float(filter_values[1])
                    if default_range and filter_values == default_range:
                        continue

                    df = df.filter(
                        (pl.col(column_name) >= min_val) & (pl.col(column_name) <= max_val)
                    )
                except (ValueError, TypeError):
                    df = df.filter(pl.col(column_name).is_in(filter_values))
            else:
                df = df.filter(pl.col(column_name).is_in(filter_values))

    # Extract sample names from filtered DataFrame
    if join_column not in df.columns:
        logger.error(f"Join column '{join_column}' not found in metadata. Available: {df.columns}")
        return []

    samples = df[join_column].unique().to_list()
    return samples


def patch_multiqc_figures(
    figures: List[Dict],
    selected_samples: List[str],
    metadata: Optional[Dict] = None,
    trace_metadata: Optional[Dict] = None,
) -> List[Dict]:
    """
    Apply sample filtering to MultiQC figures based on interactive selections.

    Args:
        figures: List of Plotly figure objects to patch
        selected_samples: List of selected sample names for filtering
        metadata: Optional metadata dictionary with plot information
        trace_metadata: Original trace metadata with x, y, z arrays and orientation

    Returns:
        List of patched figure objects
    """
    if not figures or not selected_samples:
        return figures

    patched_figures = []

    for fig_idx, fig in enumerate(figures):
        patched_fig = copy.deepcopy(fig)

        original_traces = []
        if trace_metadata and "original_data" in trace_metadata:
            original_traces = trace_metadata["original_data"]

        for i, trace in enumerate(patched_fig.get("data", [])):
            trace_type = trace.get("type", "").lower()
            trace_name = trace.get("name", "")

            # Get original data from trace metadata if available
            if i < len(original_traces):
                trace_info = original_traces[i]
                original_x = trace_info.get("original_x", [])
                original_y = trace_info.get("original_y", [])
                original_z = trace_info.get("original_z", [])
                orientation = trace_info.get("orientation", "v")
            else:
                original_x = list(trace.get("x", []))
                original_y = list(trace.get("y", []))
                original_z = list(trace.get("z", []))
                orientation = trace.get("orientation", "v")

            # Determine which axis contains sample names based on trace type
            if trace_type in ["bar", "box", "violin"]:
                if orientation == "h":
                    sample_axis = original_y
                    value_axis = original_x
                    sample_key = "y"
                    value_key = "x"
                else:
                    sample_axis = original_x
                    value_axis = original_y
                    sample_key = "x"
                    value_key = "y"

                # Filter to selected samples
                filtered_samples = []
                filtered_values = []
                for j, sample in enumerate(sample_axis):
                    if sample in selected_samples:
                        filtered_samples.append(sample)
                        if j < len(value_axis):
                            filtered_values.append(value_axis[j])

                trace[sample_key] = filtered_samples
                trace[value_key] = filtered_values

            elif trace_type == "heatmap":
                if original_x and original_z:
                    x_indices = [j for j, x in enumerate(original_x) if str(x) in selected_samples]
                    y_indices = (
                        [j for j, y in enumerate(original_y) if str(y) in selected_samples]
                        if original_y
                        else []
                    )

                    if y_indices and len(y_indices) >= len(x_indices):
                        trace["y"] = [original_y[j] for j in y_indices]
                        if isinstance(original_z, list) and original_z:
                            trace["z"] = [original_z[j] for j in y_indices if j < len(original_z)]
                    elif x_indices:
                        trace["x"] = [original_x[j] for j in x_indices]
                        if isinstance(original_z, list) and original_z:
                            trace["z"] = [
                                [row[j] for j in x_indices if j < len(row)] for row in original_z
                            ]

            elif trace_type in ["scatter", "scattergl"]:
                if trace_name:
                    trace["visible"] = trace_name in selected_samples
                else:
                    filtered_x = []
                    filtered_y = []
                    for j, x_val in enumerate(original_x):
                        if (
                            str(x_val) in selected_samples
                            or str(original_y[j] if j < len(original_y) else "") in selected_samples
                        ):
                            filtered_x.append(x_val)
                            if j < len(original_y):
                                filtered_y.append(original_y[j])
                    if filtered_x:
                        trace["x"] = filtered_x
                        trace["y"] = filtered_y

        patched_figures.append(patched_fig)

    return patched_figures


def _restore_figure_from_trace_metadata(
    current_figure: Dict, trace_metadata: Dict
) -> Optional[Dict]:
    """Restore an unfiltered figure from stored trace metadata.

    Args:
        current_figure: The currently displayed (filtered) figure.
        trace_metadata: Stored original trace data.

    Returns:
        Restored figure dict with filter marker cleared, or None if restoration fails.
    """
    if not trace_metadata or not trace_metadata.get("original_data"):
        return None

    restored_fig = copy.deepcopy(current_figure)
    original_traces = trace_metadata["original_data"]

    for i, trace in enumerate(restored_fig.get("data", [])):
        if i < len(original_traces):
            trace_info = original_traces[i]
            if trace_info.get("original_x"):
                trace["x"] = trace_info["original_x"]
            if trace_info.get("original_y"):
                trace["y"] = trace_info["original_y"]
            if trace_info.get("original_z"):
                trace["z"] = trace_info["original_z"]
            if "visible" in trace:
                trace["visible"] = True

    if "layout" not in restored_fig:
        restored_fig["layout"] = {}
    restored_fig["layout"]["_depictio_filter_applied"] = False

    return restored_fig


def register_core_callbacks(app):
    """Register core rendering callbacks for MultiQC component."""

    @app.callback(
        Output({"type": "multiqc-graph", "index": MATCH}, "figure"),
        Output({"type": "multiqc-trace-metadata", "index": MATCH}, "data", allow_duplicate=True),
        Output({"type": "multiqc-plot-wrapper", "index": MATCH}, "style"),
        Output({"type": "general-stats-wrapper", "index": MATCH}, "style"),
        Output({"type": "general-stats-wrapper", "index": MATCH}, "children"),
        Input({"type": "multiqc-trigger", "index": MATCH}, "data"),
        State({"type": "multiqc-trace-metadata", "index": MATCH}, "data"),
        background=False,
        prevent_initial_call="initial_duplicate",  # Allow duplicate + initial call
    )
    def render_multiqc_from_trigger(trigger_data, existing_trace_metadata):
        """Render MultiQC plot for view mode (existing dashboards).

        This callback is triggered by the multiqc-trigger store created by
        build_multiqc(). It reads the stored module/plot/dataset selections
        and renders the plot directly.

        For general_stats plots, it populates the general-stats-wrapper and
        hides the regular plot wrapper. For regular plots, vice versa.

        Args:
            trigger_data: Dict with s3_locations, module, plot, dataset_id, theme
            existing_trace_metadata: Existing trace metadata (to prevent re-render)

        Returns:
            Tuple of (figure, trace_metadata, plot_wrapper_style,
                       general_stats_wrapper_style, general_stats_children)
        """
        no_update_all = (
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
        )

        if existing_trace_metadata and existing_trace_metadata.get("summary"):
            return no_update_all

        if not trigger_data:
            return no_update_all

        s3_locations = trigger_data.get("s3_locations", [])
        selected_module = trigger_data.get("module")
        selected_plot = trigger_data.get("plot")
        selected_dataset = trigger_data.get("dataset_id")
        theme = trigger_data.get("theme", "light")
        component_id = trigger_data.get("component_id", "unknown")

        if not selected_module or not selected_plot or not s3_locations:
            return (
                _create_error_figure("Error: Missing parameters"),
                {},
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        # Default styles: plot visible, general stats hidden
        plot_wrapper_visible = {
            "position": "relative",
            "height": "100%",
            "width": "100%",
            "flex": "1",
            "display": "flex",
            "flexDirection": "column",
        }
        # Use position:absolute + visibility:hidden to truly remove from layout.
        # Plotly/Dash ignores display:none and still renders SVG canvases.
        plot_wrapper_hidden = {
            "position": "absolute",
            "visibility": "hidden",
            "overflow": "hidden",
            "height": "0",
            "width": "0",
        }
        gs_wrapper_visible = {
            "width": "100%",
            "height": "100%",
            "flex": "1",
            "display": "flex",
            "flexDirection": "column",
            "overflow": "hidden",
        }
        gs_wrapper_hidden = {
            "position": "absolute",
            "visibility": "hidden",
            "overflow": "hidden",
            "height": "0",
            "width": "0",
        }

        # ---- General Statistics branch ----
        if selected_module == "general_stats" or selected_plot == "general_stats":
            try:
                from depictio.dash.modules.figure_component.multiqc_vis import (
                    _get_local_path_for_s3,
                )
                from depictio.dash.modules.multiqc_component.general_stats import (
                    build_general_stats_content,
                )

                # Resolve first parquet path (S3 URI → local cached file)
                normalized = _normalize_multiqc_paths(s3_locations)
                raw_path = normalized[0] if normalized else s3_locations[0]
                parquet_path = _get_local_path_for_s3(raw_path)

                children, _store_data, _columns = build_general_stats_content(
                    parquet_path=parquet_path,
                    component_id=str(component_id),
                    show_hidden=True,
                )

                # Return: empty figure (hidden), no trace metadata,
                # hide plot wrapper, show general stats wrapper with real content
                return (
                    {"data": [], "layout": {}},
                    {},
                    plot_wrapper_hidden,
                    gs_wrapper_visible,
                    children,
                )

            except Exception as e:
                logger.error(f"Error building general stats: {e}", exc_info=True)
                return (
                    {"data": [], "layout": {"title": f"General stats error: {e}"}},
                    {},
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )

        # ---- Regular plot branch ----
        try:
            normalized_locations = _normalize_multiqc_paths(s3_locations)

            fig = create_multiqc_plot(
                s3_locations=normalized_locations,
                module=selected_module,
                plot=selected_plot,
                dataset_id=selected_dataset,
                theme=theme,
            )

            if not fig:
                logger.error("MultiQC plot generation returned None")
                return (
                    _create_error_figure("Error generating plot"),
                    {},
                    plot_wrapper_visible,
                    gs_wrapper_hidden,
                    dash.no_update,
                )

            trace_metadata = analyze_multiqc_plot_structure(fig)

            return (
                fig,
                trace_metadata,
                plot_wrapper_visible,
                gs_wrapper_hidden,
                dash.no_update,
            )

        except Exception as e:
            logger.error(f"Error rendering MultiQC plot: {e}", exc_info=True)
            return (
                _create_error_figure(f"Error: {e}", message=str(e)),
                {},
                plot_wrapper_visible,
                gs_wrapper_hidden,
                dash.no_update,
            )

    @app.callback(
        Output({"type": "multiqc-graph", "index": MATCH}, "figure", allow_duplicate=True),
        Input("interactive-values-store", "data"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        State({"type": "multiqc-graph", "index": MATCH}, "figure"),
        State({"type": "multiqc-trace-metadata", "index": MATCH}, "data"),
        State("local-store", "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        State("project-metadata-store", "data"),
        prevent_initial_call=True,
    )
    def patch_multiqc_plot_with_interactive_filtering(
        interactive_values,
        stored_metadata,
        current_figure,
        trace_metadata,
        local_data,
        interactive_metadata_list,
        interactive_metadata_ids,
        project_metadata,
    ):
        """Patch MultiQC plots when interactive filtering is applied (only for joined workflows).

        Uses existing figure and patches it directly without regenerating from S3.

        RESET SUPPORT: Empty interactive_values reloads unfiltered data.
        """
        # Early exit if no stored metadata (interactive_values can be empty for reset)
        if not stored_metadata:
            return dash.no_update

        # Guard: skip for general stats instances (handled by general_stats_callbacks)
        if (
            stored_metadata.get("selected_plot") == "general_stats"
            or stored_metadata.get("selected_module") == "general_stats"
        ):
            return dash.no_update

        # RESET SUPPORT: Allow empty interactive_values to reload unfiltered data
        if not interactive_values:
            interactive_values = {"interactive_components_values": []}

        # Get authentication token
        token = local_data.get("access_token") if local_data else None
        if not token:
            return dash.no_update

        # Enrich lightweight store data with full metadata using shared utility
        enriched_components = enrich_interactive_components_with_metadata(
            interactive_values,
            interactive_metadata_list,
            interactive_metadata_ids,
        )

        # Replace interactive_values with enriched version
        interactive_values = {"interactive_components_values": enriched_components}

        # Extract MultiQC component data from stored metadata
        s3_locations = stored_metadata.get("s3_locations", [])
        selected_module = stored_metadata.get("selected_module")
        selected_plot = stored_metadata.get("selected_plot")
        metadata = stored_metadata.get("metadata", {})
        workflow_id = resolve_bson_id(
            stored_metadata.get("workflow_id") or stored_metadata.get("wf_id")
        )
        interactive_patching_enabled = stored_metadata.get("interactive_patching_enabled", True)

        if not interactive_patching_enabled:
            return dash.no_update

        if not selected_module or not selected_plot or not s3_locations or not workflow_id:
            return dash.no_update

        multiqc_dc_id = resolve_bson_id(
            stored_metadata.get("dc_id") or stored_metadata.get("data_collection_id")
        )
        if not multiqc_dc_id:
            return dash.no_update

        result_dc_id = get_result_dc_for_workflow(workflow_id, token)
        use_link_resolution = not result_dc_id

        interactive_components_dict = {}
        has_active_filters = False

        if "interactive_components_values" in interactive_values:
            for component_data in interactive_values["interactive_components_values"]:
                component_index = component_data.get("index")
                component_value = component_data.get("value", [])

                if component_value and len(component_value) > 0:
                    comp_metadata = component_data.get("metadata", {})
                    component_type = comp_metadata.get("interactive_component_type", "")
                    default_state = comp_metadata.get("default_state", {})

                    if component_type == "DateRangePicker":
                        value = component_data.get("value")
                        if value and isinstance(value, list) and len(value) == 2:
                            if value[0] is None or value[1] is None:
                                continue
                            component_value = [
                                v.split("T")[0] if isinstance(v, str) and "T" in v else str(v)
                                for v in value
                            ]

                    if component_type in ["RangeSlider", "DateRangePicker"]:
                        default_range = default_state.get("default_range")

                        if component_type == "DateRangePicker" and default_range:
                            default_range = [
                                v.split("T")[0] if isinstance(v, str) and "T" in v else str(v)
                                for v in default_range
                            ]

                        if not (default_range and component_value == default_range):
                            has_active_filters = True
                    else:
                        has_active_filters = True

                if component_index:
                    interactive_components_dict[component_index] = component_data

        if not interactive_components_dict:
            return dash.no_update

        figure_was_patched = False
        if current_figure and isinstance(current_figure, dict):
            figure_was_patched = current_figure.get("layout", {}).get(
                "_depictio_filter_applied", False
            )

        if not has_active_filters and not figure_was_patched:
            return dash.no_update

        try:
            metadata_dc_id = None
            source_column = None
            join_column = "sample"

            for comp_data in interactive_components_dict.values():
                comp_dc_id = comp_data.get("metadata", {}).get("dc_id")
                comp_column = comp_data.get("metadata", {}).get("column_name")
                if comp_dc_id and comp_dc_id != multiqc_dc_id:
                    metadata_dc_id = comp_dc_id
                    if comp_column:
                        source_column = comp_column
                    break

            if not metadata_dc_id:
                return dash.no_update

            project_id = stored_metadata.get("project_id") if stored_metadata else None

            # Fallback: extract project_id from project-metadata-store
            if not project_id and project_metadata:
                project_data = project_metadata.get("project", {})
                if project_data:
                    pid = project_data.get("_id") or project_data.get("id")
                    if pid:
                        project_id = str(pid)

            # Link-based resolution path (fallback when no pre-computed join)
            if use_link_resolution and project_id:
                direct_sample_values = []
                indirect_filter_values = []
                for comp_data in interactive_components_dict.values():
                    comp_metadata = comp_data.get("metadata", {})
                    comp_type = comp_metadata.get("interactive_component_type", "")
                    column_type = comp_metadata.get("column_type", "")
                    column_name = comp_metadata.get("column_name", "")

                    is_categorical = (
                        comp_type in ["MultiSelect", "SegmentedControl"] or column_type == "object"
                    )
                    is_date_filter = comp_type == "DateRangePicker"
                    is_sample_column = column_name == join_column

                    if is_sample_column:
                        value = comp_data.get("value", [])
                        if value:
                            values_list = value if isinstance(value, list) else [value]
                            direct_sample_values.extend(values_list)
                    elif is_categorical or is_date_filter:
                        value = comp_data.get("value", [])
                        if value:
                            values_list = value if isinstance(value, list) else [value]
                            indirect_filter_values.extend(values_list)

                filter_values = direct_sample_values + indirect_filter_values

                if not filter_values and not has_active_filters and figure_was_patched:
                    # RESET MODE: restore all samples
                    sample_mappings = metadata.get("sample_mappings", {})
                    if not sample_mappings and project_id:
                        sample_mappings = get_multiqc_sample_mappings(
                            project_id=project_id,
                            dc_id=multiqc_dc_id,
                            token=token,
                        )

                    if sample_mappings:
                        selected_samples = []
                        for variants in sample_mappings.values():
                            selected_samples.extend(variants)
                    else:
                        restored = _restore_figure_from_trace_metadata(
                            current_figure, trace_metadata
                        )
                        return restored if restored else dash.no_update

                elif filter_values:
                    # FILTER MODE
                    sample_mappings = metadata.get("sample_mappings", {})
                    if not sample_mappings and project_id:
                        sample_mappings = get_multiqc_sample_mappings(
                            project_id=project_id,
                            dc_id=multiqc_dc_id,
                            token=token,
                        )

                    if direct_sample_values:
                        selected_samples = expand_canonical_samples_to_variants(
                            direct_sample_values, sample_mappings
                        )

                        if indirect_filter_values:
                            resolved = resolve_link_values(
                                project_id=project_id,
                                source_dc_id=metadata_dc_id,
                                source_column=source_column or join_column,
                                filter_values=indirect_filter_values,
                                target_dc_id=multiqc_dc_id,
                                token=token,
                            )
                            if resolved and resolved.get("resolved_values"):
                                indirect_set = set(resolved["resolved_values"])
                                selected_samples = [
                                    s for s in selected_samples if s in indirect_set
                                ]
                    else:
                        # Process each indirect filter component with its own source column,
                        # then intersect the resolved sample sets (AND semantics across filters)
                        resolved_set: set | None = None
                        for comp_data_inner in interactive_components_dict.values():
                            comp_meta = comp_data_inner.get("metadata", {})
                            inner_column = comp_meta.get("column_name", "")
                            if inner_column == join_column:
                                continue  # skip direct sample filters (already handled above)
                            inner_value = comp_data_inner.get("value", [])
                            if not inner_value:
                                continue
                            inner_values_list = (
                                inner_value if isinstance(inner_value, list) else [inner_value]
                            )
                            resolved = resolve_link_values(
                                project_id=project_id,
                                source_dc_id=metadata_dc_id,
                                source_column=inner_column,
                                filter_values=inner_values_list,
                                target_dc_id=multiqc_dc_id,
                                token=token,
                            )
                            if resolved and resolved.get("resolved_values"):
                                comp_resolved = set(resolved["resolved_values"])
                                resolved_set = (
                                    comp_resolved
                                    if resolved_set is None
                                    else resolved_set & comp_resolved
                                )

                        if resolved_set:
                            selected_samples = list(resolved_set)
                        else:
                            selected_samples = expand_canonical_samples_to_variants(
                                indirect_filter_values, sample_mappings
                            )

                    if not selected_samples:
                        logger.warning("No samples resolved via any method")
                        return dash.no_update

                else:
                    return dash.no_update

            # Pre-computed join path
            else:
                if not has_active_filters and figure_was_patched:
                    from bson import ObjectId

                    from depictio.api.v1.deltatables_utils import load_deltatable_lite

                    df = load_deltatable_lite(
                        workflow_id=ObjectId(workflow_id),
                        data_collection_id=ObjectId(metadata_dc_id),
                        metadata=None,
                        TOKEN=token,
                    )

                    if df is None or df.is_empty():
                        logger.warning("Metadata table is empty - cannot restore")
                        return dash.no_update

                    if join_column not in df.columns:
                        logger.error(f"Join column '{join_column}' not in metadata columns")
                        return dash.no_update

                    canonical_samples = df[join_column].unique().to_list()
                else:
                    canonical_samples = get_samples_from_metadata_filter(
                        workflow_id=workflow_id,
                        metadata_dc_id=metadata_dc_id,
                        join_column=join_column,
                        interactive_components_dict=interactive_components_dict,
                        token=token,
                    )

                    if not canonical_samples:
                        logger.warning("No canonical samples found after filtering")
                        return dash.no_update

                sample_mappings = metadata.get("sample_mappings", {})
                selected_samples = expand_canonical_samples_to_variants(
                    canonical_samples, sample_mappings
                )

            if not selected_samples:
                logger.warning("No samples found after expansion")
                if not has_active_filters and figure_was_patched:
                    restored = _restore_figure_from_trace_metadata(current_figure, trace_metadata)
                    if restored:
                        return restored
                return dash.no_update

            if not current_figure:
                logger.warning("No current figure available for patching")
                return dash.no_update

            if not trace_metadata or not trace_metadata.get("original_data"):
                logger.warning("No trace metadata available for patching")
                return dash.no_update

            patched_figures = patch_multiqc_figures(
                [current_figure], selected_samples, metadata, trace_metadata
            )

            if patched_figures:
                patched_fig = patched_figures[0]
                if "layout" not in patched_fig:
                    patched_fig["layout"] = {}
                patched_fig["layout"]["_depictio_filter_applied"] = has_active_filters
                return patched_fig

            logger.warning("No data available after filtering")
            return dash.no_update

        except Exception as e:
            logger.error(f"Error patching MultiQC plot: {e}", exc_info=True)
            return dash.no_update
