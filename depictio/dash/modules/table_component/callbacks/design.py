"""
Design mode callbacks for table component.

This module provides callbacks for the table component design interface,
handling live preview updates when workflow/data collection selection changes
in the stepper or edit page.

The design mode provides a minimal interface focused on data source selection,
as tables don't require additional configuration beyond choosing the data source.

Functions:
    register_design_callbacks: Register all design mode callbacks with the Dash app.
"""

import httpx
from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.table_component.utils import build_table
from depictio.dash.utils import get_columns_from_data_collection


def _fetch_data_collection_specs(dc_id: str, token: str) -> dict | None:
    """Fetch data collection specifications from the API.

    Args:
        dc_id: Data collection ID.
        token: Authentication token.

    Returns:
        Data collection specs dictionary, or None if fetch fails.
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch DC specs: {e}")
        return None


def _fetch_column_definitions(wf_id: str, dc_id: str, token: str) -> dict | None:
    """Fetch column definitions for the data collection.

    Args:
        wf_id: Workflow ID.
        dc_id: Data collection ID.
        token: Authentication token.

    Returns:
        Column definitions dictionary, or None if fetch fails.
    """
    try:
        return get_columns_from_data_collection(wf_id, dc_id, token)
    except Exception as e:
        logger.error(f"Failed to get columns: {e}")
        return None


def register_design_callbacks(app):
    """Register design mode callbacks for table component.

    This function registers the callback that handles live preview updates
    when the user selects a workflow and data collection in the stepper
    or edit interface.

    Args:
        app: The Dash application instance.
    """

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
        prevent_initial_call=False,
    )
    def design_table_component(wf_id, dc_id, table_id, local_data, pathname):
        """Update table preview when WF/DC selection changes.

        This callback provides live preview functionality for the table design
        interface. Tables display immediately upon data source selection without
        requiring a button click, following the minimal design approach.

        Args:
            wf_id: Workflow ID from the workflow selector.
            dc_id: Data collection ID from the data collection selector.
            table_id: Table component ID dict containing the index.
            local_data: Local store data containing the access token.
            pathname: Current URL path to detect stepper vs edit mode.

        Returns:
            Table preview content for the table-body container, or empty list
            if prerequisites are not met.
        """
        if not local_data:
            logger.warning("design_table_component: No local_data available")
            return []

        if not wf_id or not dc_id:
            return []

        token = local_data["access_token"]
        component_index = table_id["index"]

        # Fetch data collection specifications
        dc_specs = _fetch_data_collection_specs(dc_id, token)
        if not dc_specs:
            return []

        # Fetch column definitions
        cols_json = _fetch_column_definitions(wf_id, dc_id, token)
        if not cols_json:
            return []

        # Determine mode
        is_stepper_mode = "/component/add/" in pathname

        # Build table
        table_kwargs = {
            "index": component_index,
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_specs["config"],
            "cols_json": cols_json,
            "access_token": token,
            "stepper": is_stepper_mode,
            "build_frame": False,
        }

        try:
            new_table = build_table(**table_kwargs)
            return new_table
        except Exception as e:
            logger.error(f"Failed to build table: {e}")
            return []
