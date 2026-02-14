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
from depictio.dash.modules.image_component.utils import build_image
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

        logger.info("=" * 80)
        logger.info("🚀 DUPLICATE COMPONENT CALLBACK FIRED")
        logger.info("=" * 80)

        # 1. Validate trigger
        if not ctx.triggered:
            raise PreventUpdate

        triggered = ctx.triggered[0]
        if not triggered["value"]:
            raise PreventUpdate

        trigger_id = ctx.triggered_id
        source_component_id = trigger_id["index"]

        # DEBUG: Log pattern matching results
        logger.info(
            f"🔍 Duplicate callback fired for component {source_component_id}. "
            f"ALL pattern results - left_layout: {len(left_layout)} items, "
            f"right_layout: {len(right_layout)} items, "
            f"left_items: {len(left_items)} items, "
            f"right_items: {len(right_items)} items"
        )

        # DEFENSIVE CHECK: If ALL pattern matched 0 grids, raise PreventUpdate
        # This happens when grids are created dynamically by route callback after callback registration
        # CHECK BEFORE EXTRACTION - we need to check the original list length
        if len(left_layout) == 0 and len(right_layout) == 0:
            logger.warning(
                f"⚠️ Pattern matching found no grids for duplicate operation. "
                f"Grids may not be rendered yet or pattern matching failed. "
                f"Component {source_component_id} duplication requires page refresh."
            )
            raise PreventUpdate

        # Store original counts BEFORE extraction (needed for proper return value wrapping)
        original_left_count = len(left_layout)
        original_right_count = len(right_layout)

        # Extract layouts and items from ALL pattern (returns list with one grid each)
        left_layout = left_layout[0] if left_layout else []
        right_layout = right_layout[0] if right_layout else []
        left_items = left_items[0] if left_items else []
        right_items = right_items[0] if right_items else []

        # DEBUG: Log extracted values
        logger.info(
            f"📦 After extraction - left_layout: {len(left_layout) if isinstance(left_layout, list) else 'not a list'}, "
            f"right_layout: {len(right_layout) if isinstance(right_layout, list) else 'not a list'}"
        )

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

        logger.debug(f"🔨 Building fresh component: {component_type}, new_id: {new_component_id}")

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
        elif component_type == "image":
            duplicated_meta["build_frame"] = True
            fresh_component = build_image(**duplicated_meta)
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
            # ALL pattern always expects list - return empty list if grid doesn't exist, list with no_update if it does
            updated_right_layout = [] if original_right_count == 0 else [no_update]
            updated_left_items = [left_items + [wrapped_component]]
            updated_right_items = [] if original_right_count == 0 else [no_update]
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

            # ALL pattern always expects list - return empty list if grid doesn't exist, list with no_update if it does
            updated_left_layout = [] if original_left_count == 0 else [no_update]
            updated_right_layout = [current_layouts + [new_layout_entry]]
            updated_left_items = [] if original_left_count == 0 else [no_update]
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

        # DEBUG: Log return values
        logger.info(
            f"🔙 Returning - updated_left_layout: {type(updated_left_layout).__name__} "
            f"(len={len(updated_left_layout) if isinstance(updated_left_layout, list) else 'N/A'}), "
            f"updated_right_layout: {type(updated_right_layout).__name__} "
            f"(len={len(updated_right_layout) if isinstance(updated_right_layout, list) else 'N/A'}), "
            f"updated_left_items: {type(updated_left_items).__name__}, "
            f"updated_right_items: {type(updated_right_items).__name__}"
        )

        # Return updated layouts AND items (4 outputs total)
        return updated_left_layout, updated_right_layout, updated_left_items, updated_right_items
