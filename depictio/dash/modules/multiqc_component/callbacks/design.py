"""
Design mode callbacks for MultiQC component.

These callbacks are only registered in design mode (stepper + edit mode) where
the module/plot/dataset selector components exist. They handle:
- Loading MultiQC metadata and populating module dropdown
- Cascading dropdown updates (module → plots → datasets)
- Plot preview rendering based on user selections

View mode uses separate callbacks in core.py that read from stored metadata
instead of interactive selectors.
"""

import dash
from dash import ALL, MATCH, Input, Output, State, dcc
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.background_callback_helpers import should_use_background_for_component
from depictio.dash.modules.figure_component.multiqc_vis import create_multiqc_plot

# Import path normalization helper from core
from depictio.dash.modules.multiqc_component.callbacks.core import (
    _create_error_figure,
    _extract_sample_filters,
    _normalize_multiqc_paths,
)
from depictio.dash.modules.multiqc_component.utils import (
    analyze_multiqc_plot_structure,
    get_multiqc_report_metadata,
    get_multiqc_reports_for_data_collection,
)

# Use centralized background callback configuration
USE_BACKGROUND_CALLBACKS = should_use_background_for_component("multiqc")


def register_design_callbacks(app):
    """
    Register design mode callbacks for MultiQC component.

    These callbacks handle the interactive UI in stepper and edit mode where
    module/plot/dataset selectors exist. They are NOT registered in view mode
    to avoid callback errors for non-existent components.

    Args:
        app: Dash application instance
    """

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

        Triggered by WF/DC selection in design mode (stepper).

        Args:
            wf_id: Workflow ID.
            dc_id: Data collection ID.
            component_id: Component ID dict with 'index' key.
            local_data: Local store data with access_token.

        Returns:
            Tuple of (metadata, data_locations, module_options, status_text).
        """
        # Check for required workflow/data collection IDs
        if not wf_id or not dc_id:
            return {}, [], [], "Waiting for workflow/data collection selection"

        # Check for local_data and access token
        if not local_data:
            return {}, [], [], "Waiting for authentication data"

        TOKEN = local_data.get("access_token")
        if not TOKEN:
            logger.error("No access token available for MultiQC metadata loading")
            return {}, [], [], "Error: No access token available"

        try:
            reports = get_multiqc_reports_for_data_collection(dc_id, TOKEN)

            if not reports:
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
            # Prepend General Statistics as a top-level module option
            module_options = [{"label": "\u229e General Statistics", "value": "general_stats"}] + [
                {"label": mod, "value": mod} for mod in modules
            ]

            # Pre-warm in-memory cache in background so render callback finds it warm
            if data_locations:
                import threading

                def _prewarm_cache(locations):
                    try:
                        from depictio.dash.modules.figure_component.multiqc_vis import (
                            _get_or_parse_multiqc_logs,
                        )

                        _get_or_parse_multiqc_logs(locations)
                    except Exception:
                        pass  # Best-effort cache prewarm

                threading.Thread(target=_prewarm_cache, args=(data_locations,), daemon=True).start()

            return metadata, data_locations, module_options, f"{len(modules)} modules available"

        except Exception as e:
            logger.error(f"Failed to load MultiQC metadata: {e}", exc_info=True)
            return {}, [], [], f"Error: {str(e)}"

    @app.callback(
        Output({"type": "multiqc-plot-select", "index": MATCH}, "data"),
        Output({"type": "multiqc-plot-select", "index": MATCH}, "value"),
        Output({"type": "multiqc-dataset-select", "index": MATCH}, "data"),
        Output({"type": "multiqc-dataset-select", "index": MATCH}, "value"),
        Output({"type": "multiqc-dataset-select", "index": MATCH}, "style"),
        [
            Input({"type": "multiqc-module-select", "index": MATCH}, "value"),
            Input({"type": "multiqc-plot-select", "index": MATCH}, "value"),
        ],
        [
            State({"type": "multiqc-metadata-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def populate_plot_and_dataset_selectors(selected_module, selected_plot, metadata):
        """
        Populate both plot and dataset selectors in a single callback.

        When module changes: compute plot options, auto-select first plot,
        and compute datasets for that plot.
        When plot changes: only update dataset selector.

        Args:
            selected_module: Selected module name
            selected_plot: Selected plot name
            metadata: MultiQC metadata with plots structure

        Returns:
            - plot_options: Dropdown data for plot selector
            - default_plot: Auto-selected plot
            - dataset_options: Dropdown data for dataset selector
            - default_dataset: Auto-selected first dataset
            - dataset_style: Show or hide dataset selector
        """
        if not selected_module or not metadata:
            return [], None, [], None, {"display": "none"}

        # General Statistics is a top-level module option — auto-select plot and hide selectors
        if selected_module == "general_stats":
            plot_options = [{"label": "\u229e General Statistics", "value": "general_stats"}]
            return plot_options, "general_stats", [], None, {"display": "none"}

        plots_dict = metadata.get("plots", {})
        module_plots = plots_dict.get(selected_module, [])

        # Determine which input triggered this callback
        triggered = dash.ctx.triggered_id
        module_changed = (
            isinstance(triggered, dict) and triggered.get("type") == "multiqc-module-select"
        )

        # Extract plot names (handle both string and dict formats)
        plot_names = []
        for plot_item in module_plots:
            if isinstance(plot_item, str):
                plot_names.append(plot_item)
            elif isinstance(plot_item, dict):
                plot_names.extend(plot_item.keys())

        plot_options = [{"label": plot, "value": plot} for plot in plot_names]

        if module_changed:
            selected_plot = plot_names[0] if plot_names else None
        else:
            plot_options = dash.no_update

        # Compute dataset options for the (auto-)selected plot
        if not selected_plot:
            return plot_options, selected_plot, [], None, {"display": "none"}

        datasets = []
        for plot_item in module_plots:
            if isinstance(plot_item, dict) and selected_plot in plot_item:
                datasets = plot_item[selected_plot]
                break

        if not datasets or not isinstance(datasets, list):
            return plot_options, selected_plot, [], None, {"display": "none"}

        dataset_options = [{"label": ds, "value": ds} for ds in datasets]
        default_dataset = datasets[0] if datasets else None

        return plot_options, selected_plot, dataset_options, default_dataset, {"display": "block"}

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
        prevent_initial_call=True,  # Only execute when user changes selections in stepper
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
        # Guard: If no module/plot selected yet, don't render
        if not selected_module or not selected_plot:
            raise PreventUpdate

        # Guard: If no data locations, can't render
        if not data_locations:
            error_fig = {
                "data": [],
                "layout": {"title": "Error: No data locations"},
            }
            return dcc.Graph(figure=error_fig), {}

        # ---- General Statistics branch (design mode preview) ----
        if selected_module == "general_stats" or selected_plot == "general_stats":
            try:
                from depictio.dash.modules.figure_component.multiqc_vis import (
                    _get_local_path_for_s3,
                )
                from depictio.dash.modules.multiqc_component.general_stats import (
                    build_general_stats_content,
                )

                normalized_locations = _normalize_multiqc_paths(data_locations)
                raw_path = normalized_locations[0] if normalized_locations else data_locations[0]
                # Resolve S3 URI to local cached file
                parquet_path = _get_local_path_for_s3(raw_path)

                # Get the component index from the triggered callback context
                triggered_id = dash.ctx.triggered_id
                comp_idx = (
                    triggered_id.get("index", "preview")
                    if isinstance(triggered_id, dict)
                    else "preview"
                )

                children, _store_data, _columns = build_general_stats_content(
                    parquet_path=parquet_path,
                    component_id=str(comp_idx),
                    show_hidden=True,
                )

                from dash import html

                preview = html.Div(
                    children=children,
                    style={"width": "100%", "overflow": "auto"},
                )
                return preview, {}

            except Exception as e:
                logger.error(
                    f"Failed to build general stats preview: {e}",
                    exc_info=True,
                )
                return dcc.Graph(
                    figure=_create_error_figure(
                        "General Stats Error",
                        f"Failed to load general stats: {str(e)}",
                    )
                ), {}

        # ---- Regular plot branch ----
        try:
            normalized_locations = _normalize_multiqc_paths(data_locations)

            # Extract sample filtering from interactive components
            filtered_samples = None
            if filter_values and interactive_metadata_list:
                filtered_samples = _extract_sample_filters(
                    filter_values, interactive_metadata_list, component_metadata
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
                logger.error("MultiQC plot generation returned None")
                return dcc.Graph(figure=_create_error_figure("Error generating plot")), {}

            if filtered_samples:
                from depictio.dash.modules.figure_component.multiqc_vis import (
                    filter_samples_in_plot,
                )

                fig = filter_samples_in_plot(fig, filtered_samples)

            trace_metadata = analyze_multiqc_plot_structure(fig)

            graph = dcc.Graph(
                figure=fig,
                config={"displayModeBar": "hover", "responsive": True},
                style={"height": "100%", "width": "100%"},
            )

            return graph, trace_metadata

        except Exception as e:
            logger.error(f"Failed to render MultiQC plot: {e}", exc_info=True)
            return dcc.Graph(
                figure=_create_error_figure(
                    f"Error: {str(e)}", "Failed to generate plot. Check logs for details."
                )
            ), {}


__all__ = ["register_design_callbacks"]
