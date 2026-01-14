"""
MultiQC Component - Edit Mode Save Callback

This module contains the save callback for editing existing MultiQC components.
The callback reads State inputs from the MultiQC design UI (module/plot/dataset selectors)
and uses the shared save helper to persist changes to the dashboard.
"""

from datetime import datetime

from dash import ALL, Input, Output, State, ctx
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger

from .save_utils import save_multiqc_to_dashboard


def register_multiqc_edit_callback(app):
    """Register edit mode save callback for MultiQC component."""

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "btn-save-edit-multiqc", "index": ALL}, "n_clicks"),
        State("edit-page-context", "data"),
        State("local-store", "data"),
        State("url", "pathname"),
        # MultiQC-specific States from design UI
        State({"type": "multiqc-module-select", "index": ALL}, "value"),
        State({"type": "multiqc-plot-select", "index": ALL}, "value"),
        State({"type": "multiqc-dataset-select", "index": ALL}, "value"),
        State({"type": "multiqc-metadata-store", "index": ALL}, "data"),
        State({"type": "multiqc-s3-store", "index": ALL}, "data"),
        prevent_initial_call=True,
    )
    def save_multiqc_from_edit(
        btn_clicks,
        edit_context,
        local_store,
        current_pathname,
        module_values,
        plot_values,
        dataset_values,
        metadata_stores,
        s3_stores,
    ):
        """
        Save edited MultiQC component.

        Reads values from MultiQC design UI State inputs (module/plot/dataset selectors,
        metadata store, s3 locations store), builds complete component metadata,
        and uses the shared save_multiqc_to_dashboard() helper to persist changes.

        Args:
            btn_clicks: List of n_clicks from save buttons (pattern-matching)
            edit_context: Edit page context with dashboard_id, component_id, component_data
            local_store: Local storage with access token
            current_pathname: Current URL pathname (for app_prefix detection)
            module_values: Selected module from dropdown
            plot_values: Selected plot from dropdown
            dataset_values: Selected dataset from dropdown (optional)
            metadata_stores: MultiQC metadata (plots structure, modules list)
            s3_stores: S3/local FS data locations

        Returns:
            str: Redirect pathname to dashboard after save

        Raises:
            PreventUpdate: If no valid trigger or missing data
        """
        logger.info("=" * 80)
        logger.info("🚀 MULTIQC EDIT SAVE CALLBACK TRIGGERED")
        logger.info(f"   ctx.triggered_id: {ctx.triggered_id}")
        logger.info(f"   btn_clicks: {btn_clicks}")

        # GUARD: Validate trigger
        if not ctx.triggered_id or not any(btn_clicks):
            logger.warning("⚠️ MULTIQC EDIT SAVE - No trigger or clicks, preventing update")
            raise PreventUpdate

        # GUARD: Validate edit context
        if not edit_context:
            logger.error("⚠️ MULTIQC EDIT SAVE - No edit context")
            raise PreventUpdate

        # Extract context
        dashboard_id = edit_context["dashboard_id"]
        component_id = edit_context["component_id"]
        component_data = edit_context["component_data"]

        logger.info(f"💾 MULTIQC EDIT SAVE - Component: {component_id}")
        logger.info(f"   Dashboard: {dashboard_id}")
        logger.info(f"   Component type: {component_data.get('component_type')}")

        # Index for accessing State arrays (should be 0 for edit page with single component)
        idx = 0

        # Helper to safely extract value from State array
        def get_value(arr, idx, fallback=None):
            """Safely extract value from State array."""
            if arr and len(arr) > idx and arr[idx] is not None:
                return arr[idx]
            return fallback

        # Extract MultiQC selections from State
        selected_module = get_value(module_values, idx, component_data.get("selected_module"))
        selected_plot = get_value(plot_values, idx, component_data.get("selected_plot"))
        selected_dataset = get_value(dataset_values, idx, component_data.get("selected_dataset"))
        metadata = get_value(metadata_stores, idx, component_data.get("metadata", {}))
        s3_locations = get_value(s3_stores, idx, component_data.get("s3_locations", []))

        logger.info(f"   Module: {selected_module}")
        logger.info(f"   Plot: {selected_plot}")
        logger.info(f"   Dataset: {selected_dataset}")
        logger.info(f"   Data locations: {len(s3_locations) if s3_locations else 0} files")

        # GUARD: Validate required selections
        if not selected_module or not selected_plot:
            logger.error("❌ MULTIQC EDIT SAVE - Missing module or plot selection")
            raise PreventUpdate

        if not s3_locations:
            logger.error("❌ MULTIQC EDIT SAVE - No data locations available")
            raise PreventUpdate

        # Build complete component metadata
        # Preserve existing fields (wf_id, dc_id, layout, etc.) and update with new selections
        updated_metadata = {
            **component_data,  # Preserve all existing fields
            "index": component_id,  # Keep actual ID
            "component_type": "multiqc",
            "selected_module": selected_module,
            "selected_plot": selected_plot,
            "selected_dataset": selected_dataset,
            "s3_locations": s3_locations,  # Can be S3 URIs or local FS paths
            "metadata": metadata,  # MultiQC report metadata (modules, plots structure)
            "last_updated": datetime.now().isoformat(),
        }

        logger.info(f"   Final metadata keys: {list(updated_metadata.keys())}")

        # Get access token
        TOKEN = local_store["access_token"]

        # Detect app prefix from current URL
        app_prefix = "dashboard"  # default to viewer
        if current_pathname and "/dashboard-edit/" in current_pathname:
            app_prefix = "dashboard-edit"

        logger.info(f"   App prefix: {app_prefix}")

        # Use shared save helper
        redirect_url = save_multiqc_to_dashboard(dashboard_id, updated_metadata, TOKEN, app_prefix)

        logger.info(f"✅ MULTIQC EDIT SAVE - Redirecting to {redirect_url}")
        logger.info("=" * 80)

        return redirect_url

    logger.info("✅ MultiQC edit save callback registered")


__all__ = ["register_multiqc_edit_callback"]
