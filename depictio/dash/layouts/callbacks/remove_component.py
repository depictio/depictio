"""
Remove component callback for dual-panel DashGridLayout.

Handles component deletion by updating itemLayout state directly.
Adapted from old implementation (GitHub lines 1872-1957).
"""

from dash import ALL, Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_check_project_permission,
    api_call_get_dashboard,
    api_call_save_dashboard,
)


def register_remove_component_callback(app):
    """Register the remove component callback."""

    @app.callback(
        # Update both grid itemLayouts and items to keep them synchronized
        Output({"type": "left-panel-grid", "index": ALL}, "itemLayout", allow_duplicate=True),
        Output({"type": "right-panel-grid", "index": ALL}, "itemLayout", allow_duplicate=True),
        Output({"type": "left-panel-grid", "index": ALL}, "items", allow_duplicate=True),
        Output({"type": "right-panel-grid", "index": ALL}, "items", allow_duplicate=True),
        # Inputs
        Input({"type": "remove-box-button", "index": ALL}, "n_clicks"),
        # States - Get current layouts, items, and metadata
        State({"type": "left-panel-grid", "index": ALL}, "itemLayout"),
        State({"type": "right-panel-grid", "index": ALL}, "itemLayout"),
        State({"type": "left-panel-grid", "index": ALL}, "items"),
        State({"type": "right-panel-grid", "index": ALL}, "items"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def remove_component_from_dashboard(
        remove_clicks,
        left_layout,
        right_layout,
        left_items,
        right_items,
        card_metadata,
        interactive_metadata,
        pathname,
        local_data,
    ):
        """Remove component by filtering both itemLayout and items to keep DashGridLayout synchronized."""

        # 1. Validate trigger (guard against spurious calls)
        if not ctx.triggered:
            raise PreventUpdate

        # Find clicked button index
        triggered = ctx.triggered[0]
        if not triggered["value"]:  # No actual click
            raise PreventUpdate

        trigger_id = ctx.triggered_id
        component_id = trigger_id["index"]

        # Extract layouts and items from ALL pattern (returns list with one grid each)
        left_layout = left_layout[0] if left_layout else []
        right_layout = right_layout[0] if right_layout else []
        left_items = left_items[0] if left_items else []
        right_items = right_items[0] if right_items else []

        # Helper function to get ID from Dash component
        def get_component_id(item):
            """Extract ID from Dash component structure (handles both object and dict formats)."""
            if hasattr(item, "id"):
                return item.id
            elif isinstance(item, dict) and "props" in item and "id" in item["props"]:
                return item["props"]["id"]
            return None

        # 2. PERMISSION CHECK (from old implementation)
        TOKEN = local_data.get("access_token")

        # Extract dashboard_id from pathname (e.g., /dashboard-edit/{id})
        dashboard_id = pathname.split("/")[-1]

        # Fetch dashboard data to get project_id
        dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
        project_id = dashboard_data.get("project_id")

        # Verify user has editor permission
        has_permission = api_call_check_project_permission(
            project_id, TOKEN, required_permission="editor"
        )
        if not has_permission:
            logger.warning(f"🚫 User lacks editor permission to remove component {component_id}")
            raise PreventUpdate

        # 3. Determine panel (interactive → left, others → right)
        all_metadata = (card_metadata or []) + (interactive_metadata or [])
        component_meta = next((m for m in all_metadata if m.get("index") == component_id), None)

        if not component_meta:
            logger.error(f"❌ Component metadata not found for {component_id}")
            raise PreventUpdate

        component_type = component_meta.get("component_type")
        is_left_panel = component_type == "interactive"

        # 4. Remove from appropriate itemLayout AND items (must stay synchronized)
        # Note: Filtering creates a new list which triggers re-renders, but the render callback
        # will return existing values (see fix in render_card_value_background) to prevent loaders
        box_id = f"box-{component_id}"

        if is_left_panel:
            # Filter left layout and items
            updated_left_layout = [
                [item for item in (left_layout or []) if item.get("i") != box_id]
            ]
            updated_right_layout = [no_update]  # ALL pattern requires list even for no_update

            # Filter left items (items have 'id' property matching box_id)
            updated_left_items = [
                [item for item in (left_items or []) if get_component_id(item) != box_id]
            ]
            updated_right_items = [no_update]

            panel_name = "left"
        else:
            # Filter right layout and items
            updated_left_layout = [no_update]  # ALL pattern requires list even for no_update
            updated_right_layout = [
                [item for item in (right_layout or []) if item.get("i") != box_id]
            ]

            # Filter right items (items have 'id' property matching box_id)
            updated_left_items = [no_update]
            updated_right_items = [
                [item for item in (right_items or []) if get_component_id(item) != box_id]
            ]

            panel_name = "right"

        logger.info(f"🗑️  Removing component {component_id} from {panel_name} panel")

        # 5. Save to database (remove metadata + update layout)
        dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)

        # Remove metadata
        dashboard_data["stored_metadata"] = [
            m for m in dashboard_data.get("stored_metadata", []) if m.get("index") != component_id
        ]

        # Update layout data (parallel to old state_stored_draggable_layouts update)
        # Note: unwrap from list since database expects raw itemLayout array
        if is_left_panel:
            if updated_left_layout[0] != no_update:
                dashboard_data["left_panel_layout_data"] = updated_left_layout[0]  # type: ignore[index]
        else:
            if updated_right_layout[0] != no_update:
                dashboard_data["right_panel_layout_data"] = updated_right_layout[0]  # type: ignore[index]

        # Save
        api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN)

        logger.info(f"✅ Successfully removed component {component_id} and saved to database")

        # Return updated layouts AND items (4 outputs total - must stay synchronized)
        return updated_left_layout, updated_right_layout, updated_left_items, updated_right_items
