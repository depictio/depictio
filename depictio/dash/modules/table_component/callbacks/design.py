"""
Design mode callbacks for table component.

Handles live preview when WF/DC selection changes in stepper or edit page.
Provides minimal design UI focused on data source selection (WF/DC).
"""

import httpx
from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.table_component.utils import build_table
from depictio.dash.utils import get_columns_from_data_collection


def register_design_callbacks(app):
    """Register design mode callbacks for table component."""

    @app.callback(
        Output({"type": "table-body", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        ],
        [
            State({"type": "table-body", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
        ],
        prevent_initial_call=False,  # Allow initial call to populate table when WF/DC already selected
    )
    def design_table_component(wf_id, dc_id, table_id, local_data, pathname):
        """
        Live preview callback for table design.

        Automatically updates table preview when WF/DC selection changes.
        No button click needed - tables display immediately upon data source selection.
        Follows the minimal design approach - tables only need data source selection.

        Args:
            wf_id: Workflow ID from hidden select (step 2) - triggers update
            dc_id: Data collection ID from hidden select (step 2) - triggers update
            table_id: Table component ID dict from State
            local_data: Local store containing access token
            pathname: Current URL path (to detect stepper vs edit)

        Returns:
            Table preview content for table-body container
        """

        # GUARD: Validate local_data
        if not local_data:
            logger.warning("design_table_component: No local_data available")
            return []

        # GUARD: Validate WF/DC selection
        if not wf_id or not dc_id:
            logger.info("design_table_component: Waiting for WF/DC selection")
            return []

        TOKEN = local_data["access_token"]

        logger.info("=" * 80)
        logger.info(f"🎨 DESIGN TABLE - Component: {table_id['index']}")
        logger.info(f"   WF: {wf_id}, DC: {dc_id}")
        logger.info(f"   Pathname: {pathname}")

        # Fetch DC specs
        try:
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
                timeout=30.0,
            )
            response.raise_for_status()
            dc_specs = response.json()
            logger.info(f"   ✓ Fetched DC specs: {dc_specs.get('collection_name', 'unknown')}")
        except Exception as e:
            logger.error(f"❌ Failed to fetch DC specs: {e}")
            return []

        # Get columns
        try:
            cols_json = get_columns_from_data_collection(wf_id, dc_id, TOKEN)
            logger.info(f"   ✓ Fetched columns: {len(cols_json)} columns")
        except Exception as e:
            logger.error(f"❌ Failed to get columns: {e}")
            return []

        # Determine if stepper mode (add flow) or edit mode
        is_stepper_mode = "/component/add/" in pathname
        logger.info(f"   Mode: {'stepper (add)' if is_stepper_mode else 'edit'}")

        # Build table
        table_kwargs = {
            "index": table_id["index"],
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_specs["config"],
            "cols_json": cols_json,
            "access_token": TOKEN,
            "stepper": is_stepper_mode,
            "build_frame": False,  # Return just content for preview area
        }

        try:
            new_table = build_table(**table_kwargs)
            logger.info("✅ DESIGN TABLE - Preview built successfully")
            logger.info("=" * 80)
            return new_table
        except Exception as e:
            logger.error(f"❌ Failed to build table: {e}")
            import traceback

            logger.error(f"   Traceback: {traceback.format_exc()}")
            logger.info("=" * 80)
            return []
