"""MultiQC Component - Core Rendering Callbacks.

This module contains callbacks essential for rendering MultiQC components in view mode.
These callbacks are always loaded at app startup.

Callbacks:
    - render_multiqc_from_trigger: Render plot in view mode (existing dashboards)
    - load_multiqc_metadata: Load MultiQC reports and populate module selector
    - populate_plot_selector: Populate plot dropdown when module changes
    - populate_dataset_selector: Show/hide dataset selector for multi-dataset plots
    - render_multiqc_plot: Render MultiQC plot with optional sample filtering
    - patch_multiqc_plot_with_interactive_filtering: Apply interactive filters to MultiQC plots

Callback cascade: WF/DC -> Modules -> Plots -> Datasets (optional) -> Render

Helper functions:
    - _normalize_multiqc_paths: Support both S3 and local filesystem paths
    - _extract_sample_filters: Extract sample filtering from interactive components
    - _create_error_figure: Create error figure with message
"""

import copy
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import dash
import polars as pl
from dash import ALL, MATCH, Input, Output, State, dcc
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.background_callback_helpers import should_use_background_for_component
from depictio.dash.modules.figure_component.multiqc_vis import (
    create_multiqc_plot,
    filter_samples_in_plot,
)
from depictio.dash.modules.multiqc_component.utils import (
    analyze_multiqc_plot_structure,
    get_multiqc_report_metadata,
    get_multiqc_reports_for_data_collection,
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
            # S3 path - keep for backward compatibility
            # Production should use local FS instead
            logger.warning(f"S3 path detected (not recommended for production): {location}")
            logger.info("For production, use shared local FS (PersistentVolume) instead of S3")
            normalized.append(location)

        elif location.startswith("/"):
            # Absolute local path - verify it exists
            if os.path.exists(location):
                logger.info(f"Using local file path: {location}")
                normalized.append(location)
            else:
                logger.error(f"Local file path does not exist: {location}")
                # Keep it anyway - will fail later with better error context
                normalized.append(location)

        else:
            # Relative path - resolve to absolute
            abs_path = os.path.abspath(location)
            logger.info(f"Resolved relative path: {location} -> {abs_path}")
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
        logger.debug("No DC ID in MultiQC component metadata")
        return None

    # Find interactive components targeting same DC
    filtered_samples = None

    for interactive_meta in interactive_metadata_list:
        if not interactive_meta:
            continue

        interactive_dc_id = interactive_meta.get("dc_id") or interactive_meta.get(
            "data_collection_id"
        )

        if str(interactive_dc_id) == str(multiqc_dc_id):
            # Found matching DC - extract selected samples
            interactive_id = interactive_meta.get("index")

            if interactive_id and interactive_id in filter_values:
                selected_samples = filter_values[interactive_id]

                if isinstance(selected_samples, list) and selected_samples:
                    logger.info(
                        f"Applying sample filter from interactive component {interactive_id}: "
                        f"{len(selected_samples)} samples"
                    )
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
        # Get all variants for this canonical ID
        variants = sample_mappings.get(canonical_id, [])

        if variants:
            expanded_samples.extend(variants)
            logger.debug(
                f"Expanded '{canonical_id}' to {len(variants)} variants: {variants[:3]}..."
            )
        else:
            # If no mapping found, include the canonical ID itself
            expanded_samples.append(canonical_id)
            logger.debug(f"No variants found for '{canonical_id}' - using as-is")

    logger.info(
        f"Expanded {len(canonical_samples)} canonical IDs to {len(expanded_samples)} MultiQC variants"
    )
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

    # Load metadata table
    logger.debug(f"Loading metadata table {metadata_dc_id}")
    df = load_deltatable_lite(
        workflow_id=ObjectId(workflow_id),
        data_collection_id=ObjectId(metadata_dc_id),
        metadata=None,
        TOKEN=token,
    )

    if df is None or df.is_empty():
        logger.warning("Metadata table is empty")
        return []

    logger.debug(f"Loaded metadata table with columns: {df.columns}")
    logger.info(f"Metadata table shape: {df.shape}")

    # Apply filters from interactive components
    for comp_data in interactive_components_dict.values():
        comp_metadata = comp_data.get("metadata", {})
        column_name = comp_metadata.get("column_name")
        filter_values = comp_data.get("value", [])

        if column_name and filter_values and column_name in df.columns:
            logger.info(f"Filtering {column_name} = {filter_values}")

            # Get column dtype to handle type-specific filtering
            column_dtype = df[column_name].dtype

            # Strategy 1: Handle Date/Datetime columns by parsing filter values as dates
            if column_dtype in (pl.Date, pl.Datetime):
                # Check if this is the default range (no actual filtering needed)
                default_state = comp_metadata.get("default_state", {})
                default_range = default_state.get("default_range")

                # If filter_values equals default_range, skip filtering
                if default_range and filter_values == default_range:
                    logger.debug(
                        f"Date filter '{column_name}' at default range {default_range} - "
                        "skipping (not an active filter)"
                    )
                    continue  # Skip to next component - no filtering for this column

                # Otherwise, apply the date filter (user has changed from default)
                try:
                    # Parse string filter values as Python date objects (format: YYYY-MM-DD)
                    parsed_dates = [
                        datetime.strptime(str(v), "%Y-%m-%d").date() for v in filter_values
                    ]
                    df = df.filter(pl.col(column_name).is_in(parsed_dates))
                    logger.debug(f"After filtering: {df.shape[0]} rows remaining (Date parsing)")
                except Exception as e:
                    logger.warning(
                        f"Failed to filter Date column '{column_name}' with date parsing: {e}"
                    )
                    # Fallback to string casting
                    try:
                        string_values = [str(v) for v in filter_values]
                        df = df.filter(
                            pl.col(column_name).dt.strftime("%Y-%m-%d").is_in(string_values)
                        )
                        logger.info(
                            f"After filtering: {df.shape[0]} rows remaining (Date as formatted string)"
                        )
                    except Exception as e2:
                        logger.error(f"Failed to filter Date column '{column_name}': {e2}")
            # Strategy 2: Handle numeric range filters (from RangeSlider)
            elif isinstance(filter_values, (list, tuple)) and len(filter_values) == 2:
                # Check if all values look like numbers (could be a range)
                try:
                    min_val, max_val = float(filter_values[0]), float(filter_values[1])
                    # Check if this is the default range
                    default_state = comp_metadata.get("default_state", {})
                    default_range = default_state.get("default_range")

                    if default_range and filter_values == default_range:
                        logger.debug(
                            f"Numeric filter '{column_name}' at default range {default_range} - "
                            "skipping (not an active filter)"
                        )
                        continue

                    # Apply range filter
                    df = df.filter(
                        (pl.col(column_name) >= min_val) & (pl.col(column_name) <= max_val)
                    )
                    logger.info(f"After range filtering: {df.shape[0]} rows remaining")
                except (ValueError, TypeError):
                    # Not a numeric range, treat as categorical
                    df = df.filter(pl.col(column_name).is_in(filter_values))
                    logger.info(f"After filtering: {df.shape[0]} rows remaining")
            else:
                # Standard categorical filtering
                df = df.filter(pl.col(column_name).is_in(filter_values))
                logger.info(f"After filtering: {df.shape[0]} rows remaining")

    # Extract sample names from filtered DataFrame
    if join_column not in df.columns:
        logger.error(f"Join column '{join_column}' not found in metadata. Available: {df.columns}")
        return []

    samples = df[join_column].unique().to_list()
    logger.debug(f"Found {len(samples)} unique samples after filtering")
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

    logger.info(f"Patching MultiQC figures with {len(selected_samples)} selected samples")
    patched_figures = []

    for fig_idx, fig in enumerate(figures):
        logger.debug(f"Processing figure {fig_idx}")
        patched_fig = copy.deepcopy(fig)

        # Get all samples from metadata if available
        all_samples = metadata.get("samples", []) if metadata else []
        if not all_samples:
            # Fallback: try to extract samples from figure data
            all_samples = []
            for trace in fig.get("data", []):
                if "x" in trace and isinstance(trace["x"], (list, tuple)):
                    all_samples.extend(trace["x"])
                if "y" in trace and isinstance(trace["y"], (list, tuple)):
                    all_samples.extend(trace["y"])
            all_samples = list(set(all_samples))

        logger.info(f"  Figure has {len(all_samples)} total samples")
        logger.info(f"  Selected samples: {len(selected_samples)} samples")

        # Get original trace data from metadata (critical for proper patching)
        original_traces = []
        if trace_metadata and "original_data" in trace_metadata:
            original_traces = trace_metadata["original_data"]
            logger.debug(f"  Using stored trace metadata with {len(original_traces)} traces")

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
                logger.debug(
                    f"    Trace {i} ({trace_type}): {len(filtered_samples)} samples after filtering"
                )

            elif trace_type == "heatmap":
                # For heatmaps, samples can be on either x-axis (columns) or y-axis (rows)
                # Check both axes to determine where samples are located
                if original_x and original_z:
                    # First, check if samples are on x-axis (columns)
                    x_indices = [j for j, x in enumerate(original_x) if str(x) in selected_samples]
                    # Also check y-axis (rows) for samples
                    y_indices = (
                        [j for j, y in enumerate(original_y) if str(y) in selected_samples]
                        if original_y
                        else []
                    )

                    logger.debug(
                        f"    Heatmap trace {i}: x has {len(x_indices)}/{len(original_x)} matches, "
                        f"y has {len(y_indices)}/{len(original_y) if original_y else 0} matches"
                    )

                    # Determine which axis contains samples (use the one with more matches)
                    if y_indices and len(y_indices) >= len(x_indices):
                        # Samples are on y-axis (rows) - filter rows
                        logger.debug("    Filtering heatmap ROWS (y-axis) for samples")
                        trace["y"] = [original_y[j] for j in y_indices]
                        # Filter z-values (filter rows, keep all columns)
                        if isinstance(original_z, list) and original_z:
                            trace["z"] = [original_z[j] for j in y_indices if j < len(original_z)]
                        logger.debug(
                            f"    Trace {i} (heatmap): filtered to {len(y_indices)} samples (rows)"
                        )
                    elif x_indices:
                        # Samples are on x-axis (columns) - filter columns
                        logger.debug("    Filtering heatmap COLUMNS (x-axis) for samples")
                        trace["x"] = [original_x[j] for j in x_indices]
                        # Filter z-values (each row needs same column indices filtered)
                        if isinstance(original_z, list) and original_z:
                            trace["z"] = [
                                [row[j] for j in x_indices if j < len(row)] for row in original_z
                            ]
                        logger.debug(
                            f"    Trace {i} (heatmap): filtered to {len(x_indices)} samples (columns)"
                        )
                    else:
                        logger.debug(
                            f"    Trace {i} (heatmap): no sample matches found in x or y axis"
                        )

            elif trace_type in ["scatter", "scattergl"]:
                # For scatter/line plots, check if this trace represents a sample
                # In MultiQC line plots, each trace.name is typically a sample name
                if trace_name:
                    # Check if this trace's name matches any selected sample
                    if trace_name in selected_samples:
                        trace["visible"] = True
                        logger.debug(
                            f"    Trace {i} ({trace_type}): '{trace_name}' matches - visible"
                        )
                    else:
                        trace["visible"] = False
                        logger.debug(f"    Trace {i} ({trace_type}): '{trace_name}' hidden")
                else:
                    # Trace has no name - try to filter data points
                    # Check if samples are in the data
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
                        logger.debug(
                            f"    Trace {i} ({trace_type}): filtered to {len(filtered_x)} data points"
                        )

        patched_figures.append(patched_fig)

    logger.info(f"Returning {len(patched_figures)} patched figures")
    return patched_figures


def register_core_callbacks(app):
    """Register core rendering callbacks for MultiQC component."""

    # ============================================================================
    # CALLBACK 0: Render MultiQC Plot from Trigger (VIEW MODE)
    # ============================================================================
    # This callback handles view mode rendering where build_multiqc creates
    # a multiqc-trigger store with all the data needed to render the plot.
    # This is for EXISTING dashboard components, not design/edit mode.

    @app.callback(
        Output({"type": "multiqc-graph", "index": MATCH}, "figure"),
        Output({"type": "multiqc-trace-metadata", "index": MATCH}, "data", allow_duplicate=True),
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

        Args:
            trigger_data: Dict with s3_locations, module, plot, dataset_id, theme
            existing_trace_metadata: Existing trace metadata (to prevent re-render)

        Returns:
            Tuple of (Plotly Figure object, trace_metadata dict for interactive patching)
        """
        task_id = str(uuid.uuid4())[:8]
        logger.info("=" * 80)
        logger.info(f"[{task_id}] RENDER MULTIQC (VIEW MODE)")
        logger.info(f"Trigger data received: {trigger_data}")

        # Skip if already rendered (prevents spurious re-renders during Patch operations)
        if existing_trace_metadata and existing_trace_metadata.get("summary"):
            logger.info(
                "RENDER CALLBACK: Already rendered, skipping re-render "
                "(Patch operation or spurious Store update detected)"
            )
            return dash.no_update, dash.no_update

        if not trigger_data:
            logger.warning("No trigger_data - returning no_update")
            return dash.no_update, dash.no_update

        # Extract parameters from trigger
        s3_locations = trigger_data.get("s3_locations", [])
        selected_module = trigger_data.get("module")
        selected_plot = trigger_data.get("plot")
        selected_dataset = trigger_data.get("dataset_id")
        theme = trigger_data.get("theme", "light")

        logger.info(f"   Module: {selected_module}")
        logger.info(f"   Plot: {selected_plot}")
        logger.info(f"   Dataset: {selected_dataset}")
        logger.info(f"   Data locations: {len(s3_locations)}")
        logger.info(f"   Theme: {theme}")

        # Validate inputs
        if not selected_module or not selected_plot or not s3_locations:
            logger.error("   Missing required parameters")
            return {
                "data": [],
                "layout": {"title": "Error: Missing parameters"},
            }, {}

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
                logger.error(f"[{task_id}] Plot generation returned None")
                return {
                    "data": [],
                    "layout": {"title": "Error generating plot"},
                }, {}

            # Analyze plot structure and store trace metadata for interactive patching
            trace_metadata = analyze_multiqc_plot_structure(fig)
            logger.info(
                f"   Trace metadata: {len(trace_metadata.get('original_data', []))} traces stored"
            )

            logger.debug(f"[{task_id}] MULTIQC VIEW MODE PLOT RENDERED")
            logger.info("=" * 80)

            return fig, trace_metadata

        except Exception as e:
            logger.error(f"[{task_id}] Error rendering MultiQC plot: {e}", exc_info=True)
            return {
                "data": [],
                "layout": {
                    "title": f"Error: {str(e)}",
                    "annotations": [
                        {
                            "text": str(e),
                            "xref": "paper",
                            "yref": "paper",
                            "x": 0.5,
                            "y": 0.5,
                            "showarrow": False,
                        }
                    ],
                },
            }, {}

    # ============================================================================
    # CALLBACK 1: Load MultiQC Metadata and Populate Module Selector (DESIGN MODE)
    # ============================================================================

    @app.callback(
        Output({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        Output({"type": "multiqc-s3-store", "index": MATCH}, "data"),
        Output({"type": "multiqc-module-select", "index": MATCH}, "data"),
        Output({"type": "multiqc-status", "index": MATCH}, "children"),
        [
            Input({"type": "multiqc-store-workflow", "index": MATCH}, "data"),
            Input({"type": "multiqc-store-datacollection", "index": MATCH}, "data"),
        ],
        [
            State({"type": "multiqc-store-workflow", "index": MATCH}, "id"),
            State("local-store", "data"),
        ],
        prevent_initial_call=False,
    )
    def load_multiqc_metadata(wf_id, dc_id, component_id, local_data):
        """Load MultiQC reports and populate module selector.

        Triggered by dashboard load (view mode) or WF/DC selection (design mode).

        Args:
            wf_id: Workflow ID.
            dc_id: Data collection ID.
            component_id: Component ID dict with 'index' key.
            local_data: Local store data with access_token.

        Returns:
            Tuple of (metadata, data_locations, module_options, status_text).
        """
        component_index = component_id.get("index", "unknown")
        logger.debug(f"Loading MultiQC metadata for component {component_index}")

        if not wf_id or not dc_id or not local_data:
            logger.warning("Missing WF/DC or local_data")
            return {}, [], [], "Waiting for workflow/data collection selection"

        TOKEN = local_data.get("access_token")
        if not TOKEN:
            logger.error("No access token in local-store")
            return {}, [], [], "Error: No access token"

        try:
            reports = get_multiqc_reports_for_data_collection(dc_id, TOKEN)

            if not reports:
                logger.warning(f"No MultiQC reports found for DC {dc_id}")
                return {}, [], [], "No MultiQC reports found"

            # Extract s3_location from nested report structure
            # API wraps reports in MultiQCReportResponse: {"report": {...}, "data_collection_tag": "...", ...}
            data_locations = [
                r.get("report", {}).get("s3_location")
                for r in reports
                if r.get("report", {}).get("s3_location")
            ]

            if not data_locations:
                logger.error("No data locations found in reports")
                return {}, [], [], "Error: No data locations found"

            # Extract report ID from nested structure
            report_id = reports[0].get("report", {}).get("id")
            if not report_id:
                logger.error("No report ID in first report")
                return {}, data_locations, [], "Error: Invalid report structure"

            metadata = get_multiqc_report_metadata(report_id, TOKEN)

            if not metadata:
                logger.error(f"Failed to load metadata for report {report_id}")
                return {}, data_locations, [], "Error loading metadata"

            modules = metadata.get("modules", [])
            module_options = [{"label": mod, "value": mod} for mod in modules]

            logger.debug(f"Loaded {len(modules)} modules from {len(reports)} reports")

            return metadata, data_locations, module_options, f"{len(modules)} modules available"

        except Exception as e:
            logger.error(f"Failed to load MultiQC metadata: {e}", exc_info=True)
            return {}, [], [], f"Error: {str(e)}"

    # ============================================================================
    # CALLBACK 2: Populate Plot Selector When Module Changes
    # ============================================================================

    @app.callback(
        Output({"type": "multiqc-plot-select", "index": MATCH}, "data"),
        Output({"type": "multiqc-plot-select", "index": MATCH}, "value"),
        Output({"type": "multiqc-dataset-select", "index": MATCH}, "style"),
        [
            Input({"type": "multiqc-module-select", "index": MATCH}, "value"),
        ],
        [
            State({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def populate_plot_selector(selected_module, metadata):
        """
        Populate plot dropdown when module is selected.

        Also determines if dataset selector should be shown (for multi-dataset plots).

        Args:
            selected_module: Selected module name
            metadata: MultiQC metadata with plots structure

        Returns:
            - plot_options: Dropdown data for plot selector
            - default_plot: Auto-selected first plot
            - dataset_style: Hide dataset selector (shown later if needed)
        """

        if not selected_module or not metadata:
            return [], None, {"display": "none"}

        # Get plots for selected module
        plots_dict = metadata.get("plots", {})
        module_plots = plots_dict.get(selected_module, [])

        # Extract plot names (handle both string and dict formats)
        # Format can be: ["plot1", "plot2"] or [{"plot1": ["ds1", "ds2"]}, "plot2"]
        plot_names = []
        for plot_item in module_plots:
            if isinstance(plot_item, str):
                plot_names.append(plot_item)
            elif isinstance(plot_item, dict):
                plot_names.extend(plot_item.keys())

        plot_options = [{"label": plot, "value": plot} for plot in plot_names]

        # Auto-select first plot
        default_plot = plot_names[0] if plot_names else None

        logger.debug(f"   Found {len(plot_names)} plots for {selected_module}")
        if default_plot:
            logger.info(f"   Auto-selecting: {default_plot}")

        # Hide dataset selector by default (will be shown if needed by next callback)
        return plot_options, default_plot, {"display": "none"}

    # ============================================================================
    # CALLBACK 3: Populate Dataset Selector If Plot Has Multiple Datasets
    # ============================================================================

    @app.callback(
        Output({"type": "multiqc-dataset-select", "index": MATCH}, "data"),
        Output({"type": "multiqc-dataset-select", "index": MATCH}, "value"),
        Output(
            {"type": "multiqc-dataset-select", "index": MATCH},
            "style",
            allow_duplicate=True,
        ),
        [
            Input({"type": "multiqc-plot-select", "index": MATCH}, "value"),
        ],
        [
            State({"type": "multiqc-module-select", "index": MATCH}, "value"),
            State({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def populate_dataset_selector(selected_plot, selected_module, metadata):
        """
        Show and populate dataset selector if plot has multiple datasets.

        Some MultiQC plots have multiple datasets (e.g., different metrics).
        This callback checks if current plot has datasets and shows selector.

        Args:
            selected_plot: Selected plot name
            selected_module: Selected module name
            metadata: MultiQC metadata with plots structure

        Returns:
            - dataset_options: Dropdown data for dataset selector
            - default_dataset: Auto-selected first dataset
            - dataset_style: Show or hide dataset selector
        """

        if not selected_plot or not selected_module or not metadata:
            return [], None, {"display": "none"}

        # Check if this plot has multiple datasets
        plots_dict = metadata.get("plots", {})
        module_plots = plots_dict.get(selected_module, [])

        datasets = []
        for plot_item in module_plots:
            if isinstance(plot_item, dict) and selected_plot in plot_item:
                datasets = plot_item[selected_plot]
                break

        if not datasets or not isinstance(datasets, list):
            # No datasets or single dataset - hide selector
            logger.info(f"   No multiple datasets for {selected_plot}")
            return [], None, {"display": "none"}

        # Multiple datasets - show selector
        dataset_options = [{"label": ds, "value": ds} for ds in datasets]
        default_dataset = datasets[0] if datasets else None

        logger.debug(f"   Found {len(datasets)} datasets, auto-selecting: {default_dataset}")

        return dataset_options, default_dataset, {"display": "block"}

    # ============================================================================
    # CALLBACK 4: Render MultiQC Plot
    # ============================================================================

    @app.callback(
        Output({"type": "multiqc-plot-container", "index": MATCH}, "children"),
        Output({"type": "multiqc-trace-metadata", "index": MATCH}, "data", allow_duplicate=True),
        [
            Input({"type": "multiqc-module-select", "index": MATCH}, "value"),
            Input({"type": "multiqc-plot-select", "index": MATCH}, "value"),
            Input({"type": "multiqc-dataset-select", "index": MATCH}, "value"),
            Input("interactive-values-store", "data"),  # Sample filtering
        ],
        [
            State({"type": "multiqc-s3-store", "index": MATCH}, "data"),
            State({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
            State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
            State("theme-store", "data"),
        ],
        prevent_initial_call=True,  # Required when using allow_duplicate
        background=USE_BACKGROUND_CALLBACKS,
    )
    def render_multiqc_plot(
        selected_module,
        selected_plot,
        selected_dataset,
        filter_values,
        data_locations,
        metadata,
        component_metadata,
        interactive_metadata_list,
        theme,
    ):
        """
        Render MultiQC plot with optional sample filtering.

        Background callback for expensive plot generation.
        Integrates with interactive components for sample filtering.

        Args:
            selected_module: Selected module name
            selected_plot: Selected plot name
            selected_dataset: Selected dataset (optional)
            filter_values: Filter state from interactive-values-store
            data_locations: List of data paths (S3 or local FS)
            metadata: MultiQC metadata
            component_metadata: This component's metadata
            interactive_metadata_list: All interactive component metadata
            theme: Current theme (light/dark)

        Returns:
            - graph: dcc.Graph component with Plotly figure
            - trace_metadata: Analysis of plot structure for filtering
        """
        task_id = str(uuid.uuid4())[:8]
        logger.info("=" * 80)
        logger.info(f"   Module: {selected_module}")
        logger.info(f"   Plot: {selected_plot}")
        logger.info(f"   Dataset: {selected_dataset}")
        logger.info(f"   Filters: {filter_values is not None}")

        # GUARD: Check required selections
        if not selected_module or not selected_plot:
            logger.info("   Waiting for module/plot selection")
            raise PreventUpdate

        if not data_locations:
            logger.error("   No data locations available")
            error_fig = {
                "data": [],
                "layout": {"title": "Error: No data locations"},
            }
            return dcc.Graph(figure=error_fig), {}

        try:
            normalized_locations = _normalize_multiqc_paths(data_locations)

            # Extract sample filtering from interactive components
            filtered_samples = None
            if filter_values and interactive_metadata_list:
                filtered_samples = _extract_sample_filters(
                    filter_values, interactive_metadata_list, component_metadata
                )
                if filtered_samples:
                    logger.info(
                        f"[{task_id}] Applying sample filter: {len(filtered_samples)} samples"
                    )

            current_theme = theme if theme else "light"

            fig = create_multiqc_plot(
                s3_locations=normalized_locations,
                module=selected_module,
                plot=selected_plot,
                dataset_id=selected_dataset,
                theme=current_theme,
            )

            if not fig:
                logger.error(f"[{task_id}] Plot generation returned None")
                return dcc.Graph(figure=_create_error_figure("Error generating plot")), {}

            if filtered_samples:
                fig = filter_samples_in_plot(fig, filtered_samples)

            trace_metadata = analyze_multiqc_plot_structure(fig)

            logger.debug(f"[{task_id}] MultiQC plot rendered successfully")

            graph = dcc.Graph(
                figure=fig,
                config={"displayModeBar": "hover", "responsive": True},
                style={"height": "100%", "width": "100%"},
            )

            return graph, trace_metadata

        except Exception as e:
            logger.error(f"[{task_id}] Failed to render plot: {e}", exc_info=True)
            return dcc.Graph(
                figure=_create_error_figure(
                    f"Error: {str(e)}", "Failed to generate plot. Check logs for details."
                )
            ), {}

    # ============================================================================
    # CALLBACK 5: Patch MultiQC Plot with Interactive Filtering (VIEW MODE)
    # ============================================================================
    # This callback handles interactive filtering of MultiQC plots on dashboards.
    # It listens to the interactive-values-store and patches the MultiQC figure
    # when interactive components (filters) change their values.

    @app.callback(
        Output({"type": "multiqc-graph", "index": MATCH}, "figure", allow_duplicate=True),
        Input("interactive-values-store", "data"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        State({"type": "multiqc-graph", "index": MATCH}, "figure"),
        State({"type": "multiqc-trace-metadata", "index": MATCH}, "data"),
        State("local-store", "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
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
    ):
        """Patch MultiQC plots when interactive filtering is applied (only for joined workflows).

        Uses existing figure and patches it directly without regenerating from S3.

        RESET SUPPORT: Empty interactive_values reloads unfiltered data.
        """
        # ===========================================================================
        # DEBUG LOGGING: Trace callback execution for troubleshooting
        # ===========================================================================
        logger.info("=" * 80)
        logger.info("-" * 40)

        # Log callback inputs for debugging
        logger.debug(
            f"  interactive_values: {type(interactive_values)} - {bool(interactive_values)}"
        )
        logger.debug(f"  stored_metadata: {type(stored_metadata)} - {bool(stored_metadata)}")
        logger.debug(f"  current_figure: {type(current_figure)} - {bool(current_figure)}")
        logger.debug(f"  trace_metadata: {type(trace_metadata)} - {bool(trace_metadata)}")
        logger.debug(f"  local_data: {type(local_data)} - {bool(local_data)}")
        logger.debug(
            f"  interactive_metadata_list: {len(interactive_metadata_list) if interactive_metadata_list else 0} items"
        )
        logger.debug(
            f"  interactive_metadata_ids: {len(interactive_metadata_ids) if interactive_metadata_ids else 0} items"
        )

        # Log key stored_metadata fields if available
        if stored_metadata:
            logger.info(f"  📌 Component type: {stored_metadata.get('component_type', 'unknown')}")
            logger.info(
                f"  📌 interactive_patching_enabled: {stored_metadata.get('interactive_patching_enabled', False)}"
            )
            logger.info(
                f"  📌 workflow_id: {stored_metadata.get('workflow_id') or stored_metadata.get('wf_id')}"
            )
            logger.info(
                f"  📌 dc_id: {stored_metadata.get('dc_id') or stored_metadata.get('data_collection_id')}"
            )
            logger.info(f"  📌 selected_module: {stored_metadata.get('selected_module')}")
            logger.info(f"  📌 selected_plot: {stored_metadata.get('selected_plot')}")
        else:
            logger.warning("  ⚠️ No stored_metadata available!")

        logger.info("-" * 40)

        # Early exit if no stored metadata (interactive_values can be empty for reset)
        if not stored_metadata:
            logger.debug("No stored metadata - skipping")
            return dash.no_update

        # RESET SUPPORT: Allow empty interactive_values to reload unfiltered data
        if not interactive_values:
            logger.info(
                "🔄 RESET DETECTED: Empty interactive values - reloading unfiltered MultiQC data"
            )
            interactive_values = {"interactive_components_values": []}

        # Get authentication token
        token = local_data.get("access_token") if local_data else None
        if not token:
            logger.warning("No access token available for MultiQC patching")
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
        workflow_id = stored_metadata.get("workflow_id") or stored_metadata.get("wf_id")
        interactive_patching_enabled = stored_metadata.get("interactive_patching_enabled", False)

        logger.info(
            f"Processing MultiQC component - module: {selected_module}, "
            f"plot: {selected_plot}, s3_locations count: {len(s3_locations)}, "
            f"patching enabled: {interactive_patching_enabled}"
        )

        # Skip if patching is not enabled or basic requirements not met
        if not interactive_patching_enabled:
            logger.debug("Interactive patching not enabled for this component")
            return dash.no_update

        if not selected_module or not selected_plot or not s3_locations:
            logger.debug("Missing required data for MultiQC patching")
            return dash.no_update

        if not workflow_id:
            logger.debug("No workflow_id for this component")
            return dash.no_update

        # Get the MultiQC data collection ID to check for joins
        multiqc_dc_id = stored_metadata.get("dc_id") or stored_metadata.get("data_collection_id")
        if not multiqc_dc_id:
            logger.warning("No dc_id found for MultiQC component")
            return dash.no_update

        # MIGRATED: Check if pre-computed join exists OR use link-based resolution
        result_dc_id = get_result_dc_for_workflow(workflow_id, token)
        use_link_resolution = False

        if not result_dc_id:
            # No pre-computed join - try link-based resolution as fallback
            logger.info(
                f"No pre-computed joins for workflow {workflow_id} - "
                "checking for DC links as fallback"
            )
            use_link_resolution = True
        else:
            logger.info(f"Pre-computed join detected for workflow {workflow_id}: {result_dc_id}")

        # Build interactive_components_dict in the format expected by filtering
        # Structure: {component_index: {"index": ..., "value": [...], "metadata": {...}}}
        interactive_components_dict = {}
        has_active_filters = False  # Track if any filters have actual values

        if "interactive_components_values" in interactive_values:
            for component_data in interactive_values["interactive_components_values"]:
                component_index = component_data.get("index")
                component_value = component_data.get("value", [])

                # Check if this component has any active filter values
                if component_value and len(component_value) > 0:
                    comp_metadata = component_data.get("metadata", {})
                    component_type = comp_metadata.get("interactive_component_type", "")
                    default_state = comp_metadata.get("default_state", {})

                    # For RangeSlider and DateRangePicker, check if current value equals default range
                    if component_type in ["RangeSlider", "DateRangePicker"]:
                        default_range = default_state.get("default_range")
                        if default_range and component_value == default_range:
                            logger.debug(
                                f"Component {component_index} ({component_type}) at default range "
                                f"{default_range} - NOT counting as active filter"
                            )
                        else:
                            has_active_filters = True
                            logger.debug(
                                f"Component {component_index} ({component_type}) changed from default "
                                f"{default_range} to {component_value} - IS active filter"
                            )
                    else:
                        has_active_filters = True
                        logger.debug(
                            f"Component {component_index} ({component_type}) has value "
                            f"{component_value} - IS active filter"
                        )

                if component_index:
                    interactive_components_dict[component_index] = component_data
                    comp_metadata = component_data.get("metadata", {})
                    logger.info(
                        f"Interactive component {component_index}: "
                        f"dc_id={comp_metadata.get('dc_id')}, "
                        f"column={comp_metadata.get('column_name')}, "
                        f"value={component_data.get('value')}"
                    )

        # Early exit if no interactive components exist
        if not interactive_components_dict:
            logger.debug("No interactive components - skipping patching")
            return dash.no_update

        # Check if figure has been previously filtered
        figure_was_patched = False
        if current_figure and isinstance(current_figure, dict):
            layout = current_figure.get("layout", {})
            figure_was_patched = layout.get("_depictio_filter_applied", False)

        # Early exit if no filters are active AND figure hasn't been patched before
        if not has_active_filters and not figure_was_patched:
            logger.debug("No active filters on initial load - skipping patching")
            return dash.no_update

        # If user is clearing filters (no active filters but was previously patched),
        # we need to restore the original unfiltered data
        if not has_active_filters and figure_was_patched:
            logger.info("🔄 RESET MODE: Clearing filters - restoring original unfiltered data")

        try:
            # Extract metadata DC ID and column from interactive components
            metadata_dc_id = None
            source_column = None
            join_column = "sample"  # Default join column

            logger.debug(
                "Extracting metadata DC from interactive components (pre-computed join migration)"
            )
            for comp_data in interactive_components_dict.values():
                comp_dc_id = comp_data.get("metadata", {}).get("dc_id")
                comp_column = comp_data.get("metadata", {}).get("column_name")
                if comp_dc_id and comp_dc_id != multiqc_dc_id:
                    metadata_dc_id = comp_dc_id
                    if comp_column:
                        source_column = comp_column
                    logger.info(
                        f"Found metadata DC from interactive component: {metadata_dc_id}, "
                        f"column: {source_column}"
                    )
                    break

            if not metadata_dc_id:
                logger.error(
                    f"Could not find metadata DC from interactive components. "
                    f"multiqc_dc_id={multiqc_dc_id}"
                )
                return dash.no_update

            logger.info(
                f"Using metadata_dc_id={metadata_dc_id}, join_column={join_column} "
                "for MultiQC patching"
            )

            # Get project_id from stored_metadata for link resolution
            # project_id is passed to components during dashboard rendering
            project_id = stored_metadata.get("project_id") if stored_metadata else None
            if project_id:
                logger.debug(f"📌 Found project_id in stored_metadata: {project_id}")
            else:
                logger.warning(
                    "⚠️ No project_id in stored_metadata - link resolution will be skipped"
                )

            # ============================================================================
            # LINK-BASED RESOLUTION PATH (fallback when no pre-computed join)
            # ============================================================================
            if use_link_resolution and project_id:
                # Collect filter values from interactive components
                filter_values = []
                for comp_data in interactive_components_dict.values():
                    value = comp_data.get("value", [])
                    if value:
                        filter_values.extend(value if isinstance(value, list) else [value])

                if not filter_values and not has_active_filters and figure_was_patched:
                    # RESET MODE: Get all samples via link resolution without filter

                    # Use link to get ALL samples (no filter - resolve with all metadata values)
                    # First try local metadata, then fetch from API as fallback
                    sample_mappings = metadata.get("sample_mappings", {})

                    # If local sample_mappings is empty/incomplete, fetch from API
                    # (aggregates from ALL MultiQC reports for the DC)
                    if not sample_mappings and project_id:
                        logger.info(
                            "Local sample_mappings empty - fetching aggregated mappings from API"
                        )
                        sample_mappings = get_multiqc_sample_mappings(
                            project_id=project_id,
                            dc_id=multiqc_dc_id,
                            token=token,
                        )

                    if sample_mappings:
                        # Return all known sample variants
                        selected_samples = []
                        for variants in sample_mappings.values():
                            selected_samples.extend(variants)
                        logger.info(
                            f"✅ RESET via sample_mappings: {len(selected_samples)} samples "
                            f"(from {len(sample_mappings)} canonical IDs)"
                        )
                    else:
                        logger.warning("No sample_mappings available for reset")
                        return dash.no_update

                elif filter_values:
                    # FILTER MODE: Use link resolution API
                    resolved = resolve_link_values(
                        project_id=project_id,
                        source_dc_id=metadata_dc_id,
                        source_column=source_column or join_column,
                        filter_values=filter_values,
                        target_dc_id=multiqc_dc_id,
                        token=token,
                    )

                    if resolved and resolved.get("resolved_values"):
                        selected_samples = resolved["resolved_values"]
                        logger.info(
                            f"✅ Link resolution success: {len(filter_values)} values -> "
                            f"{len(selected_samples)} resolved samples "
                            f"(resolver: {resolved.get('resolver_used', 'unknown')})"
                        )
                    else:
                        # Link resolution failed - try fallback to local sample_mappings
                        logger.info(
                            "Link resolution returned no results - "
                            "falling back to local sample_mappings"
                        )
                        sample_mappings = metadata.get("sample_mappings", {})
                        selected_samples = expand_canonical_samples_to_variants(
                            filter_values, sample_mappings
                        )

                        if not selected_samples:
                            logger.warning("No samples resolved via link or local mappings")
                            return dash.no_update

                else:
                    logger.debug("No filter values and no reset needed - skipping patching")
                    return dash.no_update

            # ============================================================================
            # PRE-COMPUTED JOIN PATH (original behavior)
            # ============================================================================
            else:
                # RESET HANDLING: Load ALL samples when filters are cleared
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
                        logger.error(
                            f"Join column '{join_column}' not found in metadata. "
                            f"Available columns: {df.columns}"
                        )
                        return dash.no_update

                    canonical_samples = df[join_column].unique().to_list()
                    logger.info(
                        f"✅ RESET: Loaded {len(canonical_samples)} total samples (unfiltered)"
                    )
                else:
                    # Normal filtering mode: Get filtered samples
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

                # Expand canonical IDs to all MultiQC variants using stored mappings
                sample_mappings = metadata.get("sample_mappings", {})
                selected_samples = expand_canonical_samples_to_variants(
                    canonical_samples, sample_mappings
                )

            if not selected_samples:
                logger.warning("No samples found after expansion")
                return dash.no_update

            # Check if we have a current figure to patch
            if not current_figure:
                logger.warning("No current figure available for patching")
                return dash.no_update

            # Check if we have trace metadata for proper patching
            if not trace_metadata or not trace_metadata.get("original_data"):
                logger.warning("No trace metadata available - cannot perform proper patching")
                return dash.no_update

            # Use existing figure and patch it directly (no regeneration)
            logger.info(f"Patching existing figure with {len(selected_samples)} selected samples")
            logger.debug(
                f"Trace metadata available: {len(trace_metadata.get('original_data', []))} traces"
            )

            # Apply patching to filter the plot with the resolved sample names
            patched_figures = patch_multiqc_figures(
                [current_figure], selected_samples, metadata, trace_metadata
            )

            # Return the patched figure
            if patched_figures:
                patched_fig = patched_figures[0]
                # Mark the figure as having been patched
                if "layout" not in patched_fig:
                    patched_fig["layout"] = {}
                patched_fig["layout"]["_depictio_filter_applied"] = has_active_filters
                logger.info(
                    f"✅ Successfully patched MultiQC figure (filter_applied={has_active_filters})"
                )
                return patched_fig
            else:
                logger.warning("No data available after filtering")
                return dash.no_update

        except Exception as e:
            logger.error(f"Error patching MultiQC plot: {e}", exc_info=True)
            return dash.no_update
