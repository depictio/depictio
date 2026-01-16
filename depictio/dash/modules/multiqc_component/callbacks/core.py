"""
MultiQC Component - Core Rendering Callbacks

This module contains callbacks essential for rendering MultiQC components in view mode.
These callbacks are always loaded at app startup.

Phase 1: View mode only
- load_multiqc_metadata: Load MultiQC reports and populate module selector
- populate_plot_selector: Populate plot dropdown when module changes
- populate_dataset_selector: Show/hide dataset selector if plot has multiple datasets
- render_multiqc_plot: Render MultiQC plot with optional sample filtering

Callbacks handle dropdown cascade: WF/DC → Modules → Plots → Datasets (optional) → Render
"""

import os
import uuid
from typing import Any, Dict, List, Optional

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

# Use centralized background callback configuration
USE_BACKGROUND_CALLBACKS = should_use_background_for_component("multiqc")


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


def register_core_callbacks(app):
    """Register core rendering callbacks for MultiQC component."""

    logger.info("Registering MultiQC core callbacks...")

    # ============================================================================
    # CALLBACK 0: Render MultiQC Plot from Trigger (VIEW MODE)
    # ============================================================================
    # This callback handles view mode rendering where build_multiqc creates
    # a multiqc-trigger store with all the data needed to render the plot.
    # This is for EXISTING dashboard components, not design/edit mode.

    @app.callback(
        Output({"type": "multiqc-graph", "index": MATCH}, "figure"),
        Input({"type": "multiqc-trigger", "index": MATCH}, "data"),
        State("theme-store", "data"),
        background=USE_BACKGROUND_CALLBACKS,
        prevent_initial_call=False,  # Trigger on initial load
    )
    def render_multiqc_from_trigger(trigger_data, theme_data):
        """
        Render MultiQC plot for view mode (existing dashboards).

        This callback is triggered by the multiqc-trigger store created by
        build_multiqc(). It reads the stored module/plot/dataset selections
        and renders the plot directly.

        Args:
            trigger_data: Dict with s3_locations, module, plot, dataset_id, theme
            theme_data: Current theme (light/dark)

        Returns:
            Plotly Figure object
        """
        if not trigger_data:
            return {
                "data": [],
                "layout": {"title": "No data available"},
            }

        task_id = str(uuid.uuid4())[:8]
        logger.info("=" * 80)
        logger.info(f"🎨 [{task_id}] RENDER MULTIQC (VIEW MODE)")

        # Extract parameters from trigger
        s3_locations = trigger_data.get("s3_locations", [])
        selected_module = trigger_data.get("module")
        selected_plot = trigger_data.get("plot")
        selected_dataset = trigger_data.get("dataset_id")
        theme = trigger_data.get("theme", "light")

        # Override theme from theme-store if available
        # theme-store data is a string ("light" or "dark"), not a dict
        if theme_data and isinstance(theme_data, str):
            theme = theme_data
        elif theme_data and isinstance(theme_data, dict):
            theme = theme_data.get("theme", theme)

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
            }

        try:
            # Normalize paths (support both S3 and local FS)
            normalized_locations = _normalize_multiqc_paths(s3_locations)
            logger.info(f"   Normalized {len(normalized_locations)} data locations")

            # Generate plot using multiqc_vis module
            fig = create_multiqc_plot(
                s3_locations=normalized_locations,
                module=selected_module,
                plot=selected_plot,
                dataset_id=selected_dataset,
                theme=theme,
            )

            if not fig:
                logger.error("   Plot generation returned None")
                return {
                    "data": [],
                    "layout": {"title": "Error generating plot"},
                }

            logger.info(f"✅ [{task_id}] MULTIQC VIEW MODE PLOT RENDERED")
            logger.info("=" * 80)

            return fig

        except Exception as e:
            logger.error(f"❌ [{task_id}] Error rendering MultiQC plot: {e}")
            import traceback

            logger.error(traceback.format_exc())
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
            }

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
        """
        Load MultiQC reports and populate module selector.

        Triggered by:
        - Dashboard load (view mode) - reads saved WF/DC from stored metadata
        - WF/DC selection (design mode) - user selects in stepper

        Returns:
        - metadata_store: Complete MultiQC metadata (modules, plots, samples)
        - s3_store: List of data locations (S3 or local FS paths)
        - module_options: Dropdown data for module selector
        - status_text: Status message

        Flow:
        1. Fetch MultiQC reports for DC
        2. Extract data locations (s3_locations field - can be S3 or local paths)
        3. Get metadata from first report (contains modules/plots structure)
        4. Populate module dropdown options
        """
        logger.info("=" * 80)
        logger.info(f"🔍 LOAD MULTIQC METADATA - Component: {component_id['index']}")
        logger.info(f"   WF: {wf_id}, DC: {dc_id}")

        # GUARD: Validate inputs
        if not wf_id or not dc_id or not local_data:
            logger.warning("Missing WF/DC or local_data")
            return {}, [], [], "Waiting for workflow/data collection selection"

        TOKEN = local_data.get("access_token")
        if not TOKEN:
            logger.error("No access token in local-store")
            return {}, [], [], "Error: No access token"

        try:
            # Fetch MultiQC reports for this DC
            reports = get_multiqc_reports_for_data_collection(dc_id, TOKEN)

            if not reports:
                logger.warning(f"No MultiQC reports found for DC {dc_id}")
                return {}, [], [], "No MultiQC reports found"

            logger.info(f"   Found {len(reports)} MultiQC reports")

            # Extract data locations (can be S3 or local FS paths)
            data_locations = [r.get("s3_location") for r in reports if r.get("s3_location")]

            if not data_locations:
                logger.error("No data locations found in reports")
                return {}, [], [], "Error: No data locations found"

            logger.info(f"   Data locations: {len(data_locations)}")
            for loc in data_locations[:3]:  # Log first 3
                logger.debug(f"     - {loc}")

            # Get metadata from first report (contains modules/plots structure)
            report_id = reports[0].get("id")
            if not report_id:
                logger.error("No report ID in first report")
                return {}, data_locations, [], "Error: Invalid report structure"

            metadata = get_multiqc_report_metadata(report_id, TOKEN)

            if not metadata:
                logger.error(f"Failed to load metadata for report {report_id}")
                return {}, data_locations, [], "Error loading metadata"

            # Extract modules and create dropdown options
            modules = metadata.get("modules", [])
            module_options = [{"label": mod, "value": mod} for mod in modules]

            logger.info(f"   Loaded {len(modules)} modules")
            logger.debug(f"   Modules: {modules}")
            logger.info("✅ MULTIQC METADATA LOADED")
            logger.info("=" * 80)

            return (
                metadata,
                data_locations,
                module_options,
                f"{len(modules)} modules available",
            )

        except Exception as e:
            logger.error(f"❌ Failed to load MultiQC metadata: {e}")
            import traceback

            logger.error(traceback.format_exc())
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
        logger.info(f"🎯 POPULATE PLOTS - Module: {selected_module}")

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

        logger.info(f"   Found {len(plot_names)} plots for {selected_module}")
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
        logger.info(f"🎯 CHECK DATASETS - Module: {selected_module}, Plot: {selected_plot}")

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

        logger.info(f"   Found {len(datasets)} datasets, auto-selecting: {default_dataset}")

        return dataset_options, default_dataset, {"display": "block"}

    # ============================================================================
    # CALLBACK 4: Render MultiQC Plot
    # ============================================================================

    @app.callback(
        Output({"type": "multiqc-plot-container", "index": MATCH}, "children"),
        Output({"type": "multiqc-trace-metadata", "index": MATCH}, "data"),
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
        prevent_initial_call=True,
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
        logger.info(f"[{task_id}] 🎨 RENDER MULTIQC PLOT")
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
            # Normalize paths (support both S3 and local FS)
            normalized_locations = _normalize_multiqc_paths(data_locations)
            logger.info(f"   Normalized {len(normalized_locations)} data locations")

            # Extract sample filtering from interactive components
            filtered_samples = None
            if filter_values and interactive_metadata_list:
                filtered_samples = _extract_sample_filters(
                    filter_values, interactive_metadata_list, component_metadata
                )
                if filtered_samples:
                    logger.info(f"   Applying sample filter: {len(filtered_samples)} samples")

            # Generate plot using multiqc_vis module
            current_theme = theme if theme else "light"
            logger.info(f"   Theme: {current_theme}")

            fig = create_multiqc_plot(
                s3_locations=normalized_locations,
                module=selected_module,
                plot=selected_plot,
                dataset_id=selected_dataset,
                theme=current_theme,
            )

            if not fig:
                logger.error("   Plot generation returned None")
                error_fig = {
                    "data": [],
                    "layout": {"title": "Error generating plot"},
                }
                return dcc.Graph(figure=error_fig), {}

            # Apply sample filtering if specified
            if filtered_samples:
                logger.info(f"   Filtering plot to {len(filtered_samples)} samples")
                fig = filter_samples_in_plot(fig, filtered_samples)

            # Analyze plot structure for interactive filtering support
            trace_metadata = analyze_multiqc_plot_structure(fig)

            logger.info(f"✅ [{task_id}] MULTIQC PLOT RENDERED")
            logger.info("=" * 80)

            # Wrap figure in dcc.Graph
            graph = dcc.Graph(
                figure=fig,
                config={"displayModeBar": "hover", "responsive": True},
                style={"height": "100%", "width": "100%"},
            )

            return graph, trace_metadata

        except Exception as e:
            logger.error(f"❌ [{task_id}] Failed to render plot: {e}")
            import traceback

            logger.error(traceback.format_exc())

            error_layout = {
                "data": [],
                "layout": {
                    "title": f"Error: {str(e)}",
                    "annotations": [
                        {
                            "text": "Failed to generate plot. Check logs for details.",
                            "xref": "paper",
                            "yref": "paper",
                            "x": 0.5,
                            "y": 0.5,
                            "showarrow": False,
                            "font": {"size": 16},
                        }
                    ],
                },
            }

            return dcc.Graph(figure=error_layout), {}

    logger.info("✅ MultiQC core callbacks registered (5 callbacks: view mode + 4 design mode)")
