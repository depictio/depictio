"""
Map Component - Selection Callbacks.

Handles both Plotly map (selectedData/clickData) and dash-leaflet
(EditControl draw, GeoJSON click) selection events. Updates
interactive-values-store for cross-component filtering.
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


def register_leaflet_selection_callback(app):
    """Register callback for dash-leaflet selection via EditControl and GeoJSON click.

    Handles:
    - EditControl draw (rectangle/polygon) → point-in-polygon filtering
    - GeoJSON scatter click → single point selection
    - Shape deletion → clear selection

    Args:
        app: Dash application instance.
    """

    logger.info("Registering leaflet selection callback")

    @app.callback(
        Output("interactive-values-store", "data", allow_duplicate=True),
        Input({"type": "leaflet-edit-control", "index": ALL}, "geojson"),
        Input({"type": "leaflet-scatter", "index": ALL}, "clickData"),
        State({"type": "leaflet-edit-control", "index": ALL}, "id"),
        State({"type": "leaflet-scatter", "index": ALL}, "id"),
        State({"type": "leaflet-trigger", "index": ALL}, "data"),
        State({"type": "leaflet-trigger", "index": ALL}, "id"),
        State({"type": "leaflet-scatter-data", "index": ALL}, "data"),
        State({"type": "leaflet-scatter-data", "index": ALL}, "id"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "id"),
        State("interactive-values-store", "data"),
        prevent_initial_call=True,
    )
    def update_store_from_leaflet_selection(
        edit_geojson_list: list[dict | None],
        click_data_list: list[dict | None],
        edit_control_ids: list[dict[str, str]],
        scatter_ids: list[dict[str, str]],
        trigger_data_list: list[dict | None],
        trigger_ids: list[dict[str, str]],
        scatter_data_list: list[list[dict] | None],
        scatter_data_ids: list[dict[str, str]],
        metadata_list: list[dict[str, Any] | None],
        metadata_ids: list[dict[str, str]],
        current_store: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Update interactive-values-store from leaflet map interactions."""
        current_store = initialize_store(current_store)
        existing_values = filter_existing_values(current_store, SOURCE_TYPE)

        triggered = ctx.triggered_id
        if not triggered:
            raise dash.exceptions.PreventUpdate

        triggered_type = triggered.get("type", "") if isinstance(triggered, dict) else ""
        triggered_index = triggered.get("index", "") if isinstance(triggered, dict) else ""

        logger.info(f"Leaflet selection triggered: type={triggered_type}, index={triggered_index}")

        # Find the matching trigger_data for this component
        trigger_data = None
        for td, tid in zip(trigger_data_list, trigger_ids):
            if tid.get("index") == triggered_index:
                trigger_data = td
                break

        # Also try matching via metadata
        metadata_by_index = build_metadata_lookup(metadata_list, metadata_ids)

        if not trigger_data:
            # Try to find via edit-control or scatter index
            for td, tid in zip(trigger_data_list, trigger_ids):
                if td:
                    trigger_data = td
                    break

        if not trigger_data:
            raise dash.exceptions.PreventUpdate

        selection_enabled = trigger_data.get("selection_enabled", False)
        selection_column = trigger_data.get("selection_column")

        if not selection_enabled or not selection_column:
            raise dash.exceptions.PreventUpdate

        selected_values: list[str] = []

        if triggered_type == "leaflet-scatter":
            # Single point click on GeoJSON scatter layer
            for i, scatter_id in enumerate(scatter_ids):
                if scatter_id.get("index") == triggered_index:
                    click_data = click_data_list[i] if i < len(click_data_list) else None
                    if click_data and isinstance(click_data, dict):
                        props = click_data.get("properties", {})
                        value = props.get(selection_column)
                        if value is not None:
                            selected_values = [str(value)]
                            logger.info(
                                f"Leaflet scatter click: selected '{value}' from column '{selection_column}'"
                            )
                    break

        elif triggered_type == "leaflet-edit-control":
            # Box/lasso draw — find points inside drawn shapes
            for i, edit_id in enumerate(edit_control_ids):
                if edit_id.get("index") == triggered_index:
                    edit_geojson = edit_geojson_list[i] if i < len(edit_geojson_list) else None
                    if not edit_geojson:
                        # Shape deleted — clear selection
                        return merge_selection_values(existing_values, [])

                    drawn_features = edit_geojson.get("features", [])
                    if not drawn_features:
                        return merge_selection_values(existing_values, [])

                    # Get scatter data from the leaflet-scatter-data store
                    scatter_data = _get_scatter_data_for_index(
                        triggered_index, scatter_data_list, scatter_data_ids
                    )
                    if not scatter_data:
                        logger.warning(
                            f"Leaflet edit-control: no scatter data found for index={triggered_index}"
                        )
                        raise dash.exceptions.PreventUpdate

                    selected_values = _points_in_drawn_shapes(
                        scatter_data, drawn_features, selection_column
                    )
                    logger.info(
                        f"Leaflet draw selection: {len(drawn_features)} shapes, "
                        f"{len(scatter_data)} points tested, {len(selected_values)} selected"
                    )
                    break

        if not selected_values:
            # Check if we had previous selections to clear
            had_previous = any(
                v.get("source") == SOURCE_TYPE
                for v in current_store.get("interactive_components_values", [])
            )
            if had_previous:
                logger.info("Leaflet selection: clearing previous selection")
                return merge_selection_values(existing_values, [])
            raise dash.exceptions.PreventUpdate

        # Find dc_id from metadata
        metadata = metadata_by_index.get(triggered_index, {})
        # Selection targets the scatter overlay DC (metadata), not the map's primary DC
        dc_id = metadata.get("dc_id") or trigger_data.get("scatter_overlay_dc_id")

        selection_entry = create_selection_entry(
            component_index=triggered_index,
            values=selected_values,
            source_type=SOURCE_TYPE,
            column_name=selection_column,
            dc_id=dc_id,
        )

        return merge_selection_values(existing_values, [selection_entry])


def _get_scatter_data_for_index(
    index: str,
    scatter_data_list: list[list[dict] | None],
    scatter_data_ids: list[dict[str, str]],
) -> list[dict] | None:
    """Retrieve scatter overlay point data from leaflet-scatter-data store."""
    for i, sd_id in enumerate(scatter_data_ids):
        if sd_id.get("index") == index and i < len(scatter_data_list):
            return scatter_data_list[i]
    return None


def _points_in_drawn_shapes(
    scatter_data: list[dict],
    drawn_features: list[dict],
    selection_column: str,
) -> list[str]:
    """Find scatter points inside drawn polygon/rectangle shapes.

    Uses shapely for point-in-polygon tests.
    """
    try:
        from shapely.geometry import Point, shape
    except ImportError:
        logger.warning("shapely not installed — cannot perform spatial selection")
        return []

    # Build union of all drawn shapes
    drawn_polygons = []
    for feature in drawn_features:
        geom = feature.get("geometry")
        if geom and geom.get("type") in ("Polygon", "MultiPolygon"):
            try:
                drawn_polygons.append(shape(geom))
            except Exception:
                continue

    if not drawn_polygons:
        return []

    # Test each scatter point against drawn shapes
    selected = []
    for point_data in scatter_data:
        lat = point_data.get("lat")
        lon = point_data.get("lon")
        if lat is None or lon is None:
            continue
        pt = Point(lon, lat)
        for poly in drawn_polygons:
            if poly.contains(pt):
                props = point_data.get("properties", {})
                value = props.get(selection_column)
                if value is not None:
                    selected.append(str(value))
                break

    return selected
