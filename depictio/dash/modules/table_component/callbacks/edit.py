"""
Edit mode callbacks for table component.

Handles saving table metadata from edit page.
Tables have minimal configuration (just WF/DC), so the save callback
fetches fresh DC specs and columns rather than reading form inputs.
"""

from datetime import datetime

import httpx
from dash import ALL, Input, Output, State, ctx
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.utils import get_columns_from_data_collection

from .save_utils import save_table_to_dashboard


def register_table_edit_callback(app):
    """Register edit mode save callback for table component."""

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "btn-save-edit-table", "index": ALL}, "n_clicks"),
        State("edit-page-context", "data"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def save_table_from_edit(btn_clicks, edit_context, local_store, current_pathname):
        """
        Save edited table component.

        Tables have minimal configuration (WF/DC only), so we read WF/DC from
        component_data, fetch fresh DC specs and columns, and save complete metadata.

        Args:
            btn_clicks: List of n_clicks from save buttons (pattern-matching)
            edit_context: Edit page context with dashboard_id, component_id, component_data
            local_store: Local storage with access token
            current_pathname: Current URL pathname (for app_prefix detection)

        Returns:
            str: Redirect pathname to dashboard after save

        Raises:
            PreventUpdate: If no valid trigger or missing data
        """
        logger.info("=" * 80)
        logger.info("🚀 TABLE EDIT SAVE CALLBACK TRIGGERED")
        logger.info(f"   ctx.triggered_id: {ctx.triggered_id}")
        logger.info(f"   btn_clicks: {btn_clicks}")

        # GUARD: Validate trigger
        if not ctx.triggered_id or not any(btn_clicks):
            logger.warning("⚠️ TABLE EDIT SAVE - No trigger or clicks")
            raise PreventUpdate

        # GUARD: Validate edit context
        if not edit_context:
            logger.error("⚠️ TABLE EDIT SAVE - No edit context")
            raise PreventUpdate

        # Extract context
        dashboard_id = edit_context["dashboard_id"]
        component_id = edit_context["component_id"]
        component_data = edit_context["component_data"]

        logger.info(f"💾 TABLE EDIT SAVE - Component: {component_id}")
        logger.info(f"   Dashboard: {dashboard_id}")
        logger.info(f"   Component type: {component_data.get('component_type')}")

        # Extract WF/DC from existing component
        wf_id = component_data.get("wf_id")
        dc_id = component_data.get("dc_id")

        if not wf_id or not dc_id:
            logger.error("❌ TABLE EDIT SAVE - Missing WF/DC in component data")
            raise PreventUpdate

        logger.info(f"   WF: {wf_id}, DC: {dc_id}")

        TOKEN = local_store["access_token"]

        # Fetch fresh DC specs and columns (ensures current structure)
        try:
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
                timeout=30.0,
            )
            response.raise_for_status()
            dc_specs = response.json()

            cols_json = get_columns_from_data_collection(wf_id, dc_id, TOKEN)

            logger.info(f"   ✓ Fetched DC specs: {dc_specs.get('collection_name', 'unknown')}")
            logger.info(f"   ✓ Fetched columns: {len(cols_json)} columns")

        except Exception as e:
            logger.error(f"❌ TABLE EDIT SAVE - Failed to fetch DC data: {e}")
            raise PreventUpdate

        # Build complete component metadata
        updated_metadata = {
            "index": component_id,  # Keep actual ID
            "component_type": "table",
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_specs["config"],
            "cols_json": cols_json,
            "parent_index": None,
            "last_updated": datetime.now().isoformat(),
        }

        logger.info("   Updated metadata keys: " + str(list(updated_metadata.keys())))

        # Detect app prefix from current URL
        app_prefix = "dashboard"  # default to viewer
        if current_pathname and "/dashboard-edit/" in current_pathname:
            app_prefix = "dashboard-edit"

        logger.info(f"   App prefix: {app_prefix}")

        # Use shared save helper
        redirect_url = save_table_to_dashboard(dashboard_id, updated_metadata, TOKEN, app_prefix)

        logger.info(f"✅ TABLE EDIT SAVE - Redirecting to {redirect_url}")
        logger.info("=" * 80)

        return redirect_url

    logger.info("✅ Table edit save callback registered")
