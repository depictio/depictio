"""
Duplicate component callback for dual-panel DashGridLayout.

Handles component duplication by creating fresh components from metadata.
Adapted from old implementation (GitHub lines 2361-2703).
"""

import copy
import uuid

from dash import ALL, Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_check_project_permission,
    api_call_get_dashboard,
    api_call_save_dashboard,
)
from depictio.dash.component_metadata import get_dual_panel_dimensions
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.dash.modules.card_component.utils import build_card
from depictio.dash.modules.figure_component.utils import build_figure
from depictio.dash.modules.interactive_component.utils import build_interactive
from depictio.dash.modules.table_component.utils import build_table


def register_duplicate_component_callback(app):
    """Register the duplicate component callback."""

    @app.callback(
        # Update both grid itemLayouts and items (ALL pattern - returns list with one grid each)
        Output({"type": "left-panel-grid", "index": ALL}, "itemLayout", allow_duplicate=True),
        Output({"type": "right-panel-grid", "index": ALL}, "itemLayout", allow_duplicate=True),
        Output({"type": "left-panel-grid", "index": ALL}, "items", allow_duplicate=True),
        Output({"type": "right-panel-grid", "index": ALL}, "items", allow_duplicate=True),
        # Inputs
        Input({"type": "duplicate-box-button", "index": ALL}, "n_clicks"),
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
    def duplicate_component(
        duplicate_clicks,
        left_layout,
        right_layout,
        left_items,
        right_items,
        card_metadata,
        interactive_metadata,
        pathname,
        local_data,
    ):
        """Duplicate component by appending to itemLayout."""

        # 1. Validate trigger
        if not ctx.triggered:
            raise PreventUpdate

        triggered = ctx.triggered[0]
        if not triggered["value"]:
            raise PreventUpdate

        trigger_id = ctx.triggered_id
        source_component_id = trigger_id["index"]

        # Extract layouts and items from ALL pattern (returns list with one grid each)
        left_layout = left_layout[0] if left_layout else []
        right_layout = right_layout[0] if right_layout else []
        left_items = left_items[0] if left_items else []
        right_items = right_items[0] if right_items else []

        # 2. PERMISSION CHECK (from old implementation)
        TOKEN = local_data.get("access_token")

        # Extract dashboard_id from pathname (e.g., /dashboard-edit/{id})
        dashboard_id = pathname.split("/")[-1]

        # Fetch dashboard data to get project_id
        dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
        project_id = dashboard_data.get("project_id")

        has_permission = api_call_check_project_permission(
            project_id, TOKEN, required_permission="editor"
        )
        if not has_permission:
            logger.warning(
                f"🚫 User lacks editor permission to duplicate component {source_component_id}"
            )
            raise PreventUpdate

        # 3. Find source component metadata
        all_metadata = (card_metadata or []) + (interactive_metadata or [])
        source_meta = next((m for m in all_metadata if m.get("index") == source_component_id), None)

        if not source_meta:
            logger.error(f"❌ Source metadata not found for {source_component_id}")
            raise PreventUpdate

        # 4. Create duplicate metadata (from old: copy.deepcopy + update_nested_ids)
        # Generate new UUID (old: generate_unique_index())
        new_component_id = str(uuid.uuid4())

        # Deep copy metadata (old pattern: copy.deepcopy)
        duplicated_meta = copy.deepcopy(source_meta)
        duplicated_meta["index"] = new_component_id

        # CRITICAL: Pass reference_value as initial value for cards to display immediately
        # Cards need the value parameter to show content instead of loader
        # But we still remove reference_value from metadata to allow re-rendering later
        reference_value = duplicated_meta.get("reference_value")
        if "reference_value" in duplicated_meta:
            del duplicated_meta["reference_value"]

        # 5. Build fresh component from duplicated metadata (instead of cloning complex tree)
        component_type = source_meta.get("component_type")
        is_left_panel = component_type == "interactive"

        dims = get_dual_panel_dimensions(component_type)
        new_box_id = f"box-{new_component_id}"

        logger.info(f"🔨 Building fresh component: {component_type}, new_id: {new_component_id}")

        # Build fresh component from duplicated metadata using module build functions
        if component_type == "card":
            # Set value in metadata so card displays content immediately (not in kwargs to avoid conflict)
            duplicated_meta["value"] = reference_value
            duplicated_meta["build_frame"] = True
            fresh_component = build_card(**duplicated_meta)
        elif component_type == "figure":
            duplicated_meta["build_frame"] = True
            fresh_component = build_figure(**duplicated_meta)
        elif component_type == "interactive":
            # CRITICAL: Set build_frame=True to create all Store components (interactive-trigger, etc.)
            # Without this, callbacks fail with "nonexistent object" errors
            duplicated_meta["build_frame"] = True
            fresh_component = build_interactive(**duplicated_meta)
        elif component_type == "table":
            duplicated_meta["build_frame"] = True
            fresh_component = build_table(**duplicated_meta)
        else:
            logger.error(f"❌ Unknown component type: {component_type}")
            raise PreventUpdate

        # Wrap component with edit mode buttons and container
        wrapped_component = enable_box_edit_mode(
            box=fresh_component,
            component_data=duplicated_meta,
            dashboard_id=dashboard_id,
        )

        if is_left_panel:
            # Stack vertically in left panel
            current_layouts = left_layout or []
            max_y = max([layout["y"] + layout["h"] for layout in current_layouts], default=0)

            new_layout_entry = {
                "i": new_box_id,
                "x": 0,
                "y": max_y,
                **dims,
                "static": False,
            }

            updated_left_layout = [current_layouts + [new_layout_entry]]
            updated_right_layout = [no_update]
            updated_left_items = [left_items + [wrapped_component]]
            updated_right_items = [no_update]
            panel_name = "left"
        else:
            # Stack in right panel
            current_layouts = right_layout or []
            max_y = max([layout["y"] + layout["h"] for layout in current_layouts], default=0)

            new_layout_entry = {
                "i": new_box_id,
                "x": 0,
                "y": max_y,
                **dims,
                "static": False,
            }

            updated_left_layout = [no_update]
            updated_right_layout = [current_layouts + [new_layout_entry]]
            updated_left_items = [no_update]
            updated_right_items = [right_items + [wrapped_component]]
            panel_name = "right"

        logger.info(
            f"📋 Duplicating {source_component_id} → {new_component_id} in {panel_name} panel"
        )

        # 6. Save to database
        dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)

        # Add metadata
        dashboard_data["stored_metadata"].append(duplicated_meta)

        # Update layout data (parallel to old state_stored_draggable_layouts)
        # Note: unwrap from list since database expects raw itemLayout array
        if is_left_panel:
            if updated_left_layout[0] != no_update:
                dashboard_data["left_panel_layout_data"] = updated_left_layout[0]  # type: ignore[index]
        else:
            if updated_right_layout[0] != no_update:
                dashboard_data["right_panel_layout_data"] = updated_right_layout[0]  # type: ignore[index]

        api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN)

        logger.info(
            f"✅ Successfully duplicated component {source_component_id} → {new_component_id} and saved to database"
        )

        # Return updated layouts AND items (4 outputs total)
        return updated_left_layout, updated_right_layout, updated_left_items, updated_right_items
