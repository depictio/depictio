"""
Map Component - Selection Callback.

Handles map click/lasso selection events and updates interactive-values-store
for cross-component filtering. Reuses shared selection utilities.
"""

from typing import Any

import dash
from dash import ALL, Input, Output, State, ctx

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.figure_component.callbacks.selection import (
    extract_scatter_selection_values,
)
from depictio.dash.modules.shared.selection_utils import (
    build_metadata_lookup,
    create_selection_entry,
    filter_existing_values,
    handle_reset_button,
    initialize_store,
    merge_selection_values,
    should_prevent_update,
)

BUTTON_TYPE = "reset-selection-map-button"
SOURCE_TYPE = "map_selection"


def register_map_selection_callback(app):
    """Register callback to capture map selections.

    Listens to selectedData (lasso/rectangle) and clickData (point click)
    from all map-graph components and updates interactive-values-store.

    Args:
        app: Dash application instance.
    """

    logger.info("Registering map selection callback")

    @app.callback(
        Output("interactive-values-store", "data", allow_duplicate=True),
        Input({"type": "map-graph", "index": ALL}, "selectedData"),
        Input({"type": "map-graph", "index": ALL}, "clickData"),
        Input({"type": BUTTON_TYPE, "index": ALL}, "n_clicks"),
        State({"type": "map-graph", "index": ALL}, "id"),
        State({"type": BUTTON_TYPE, "index": ALL}, "id"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "id"),
        State("interactive-values-store", "data"),
        prevent_initial_call=True,
    )
    def update_store_from_map_selection(
        selected_data_list: list[dict[str, Any] | None],
        click_data_list: list[dict[str, Any] | None],
        reset_clicks_list: list[int | None],
        map_ids: list[dict[str, str]],
        reset_button_ids: list[dict[str, str]],
        metadata_list: list[dict[str, Any] | None],
        metadata_ids: list[dict[str, str]],
        current_store: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Update interactive-values-store with map selection data."""
        current_store = initialize_store(current_store)

        # Handle reset button
        reset_result = handle_reset_button(
            ctx.triggered_id, BUTTON_TYPE, SOURCE_TYPE, current_store
        )
        if reset_result is not None:
            return reset_result

        triggered_prop = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None

        # Ignore clearing triggers from map re-render
        if "selectedData" in triggered_prop and not triggered_value:
            has_existing = any(
                v.get("source") == SOURCE_TYPE
                for v in current_store.get("interactive_components_values", [])
            )
            if has_existing:
                raise dash.exceptions.PreventUpdate

        metadata_by_index = build_metadata_lookup(metadata_list, metadata_ids)
        existing_values = filter_existing_values(current_store, SOURCE_TYPE)

        # Track existing map selections for re-render preservation
        existing_map_by_index: dict[str, dict[str, Any]] = {}
        for v in current_store.get("interactive_components_values", []):
            if v.get("source") == SOURCE_TYPE:
                existing_map_by_index[v.get("index", "")] = v

        selection_values: list[dict[str, Any]] = []
        has_any_selection = False

        for i, map_id in enumerate(map_ids):
            map_index = map_id.get("index") if isinstance(map_id, dict) else str(map_id)
            metadata = metadata_by_index.get(map_index, {})

            selection_enabled = metadata.get("selection_enabled", False)
            selection_column = metadata.get("selection_column")

            if not selection_enabled or not selection_column:
                continue

            selected_data = selected_data_list[i] if i < len(selected_data_list) else None
            click_data = click_data_list[i] if i < len(click_data_list) else None

            selection_column_index = metadata.get("selection_column_index", 0)

            # Reuse the scatter extraction logic (same customdata structure)
            values = extract_scatter_selection_values(
                selected_data, click_data, selection_column_index
            )

            # Preserve existing selection on re-render
            if not values and selected_data and map_index in existing_map_by_index:
                selection_values.append(existing_map_by_index[map_index])
                has_any_selection = True
                continue

            if values:
                has_any_selection = True
                selection_values.append(
                    create_selection_entry(
                        component_index=map_index,
                        values=values,
                        source_type=SOURCE_TYPE,
                        column_name=selection_column,
                        dc_id=metadata.get("dc_id"),
                    )
                )

        if should_prevent_update(has_any_selection, current_store, SOURCE_TYPE):
            raise dash.exceptions.PreventUpdate

        return merge_selection_values(existing_values, selection_values)
