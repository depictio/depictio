"""
Map Component - Core Rendering Callbacks.

Batch rendering callback for all map components, following the same pattern
as figure_component/callbacks/core.py with parallel data loading and
filter integration via interactive-values-store.
"""

import concurrent.futures
import hashlib
import json
import time
from typing import Any

import dash
from bson import ObjectId
from dash import ALL, Input, Output, State, html

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.modules.map_component.utils import render_map
from depictio.dash.utils import extend_filters_via_links

LoadKey = tuple[str, str, str]


def _build_metadata_index(
    interactive_metadata_list: list | None,
    interactive_metadata_ids: list | None,
) -> dict[str, dict]:
    """Build mapping from component index to full metadata."""
    metadata_by_index: dict[str, dict] = {}
    if not interactive_metadata_list or not interactive_metadata_ids:
        return metadata_by_index
    for idx, meta_id in enumerate(interactive_metadata_ids):
        if idx < len(interactive_metadata_list):
            index = meta_id["index"]
            metadata_by_index[index] = interactive_metadata_list[idx]
    return metadata_by_index


def _enrich_filter_components(
    lightweight_components: list[dict],
    metadata_by_index: dict[str, dict],
) -> list[dict]:
    """Enrich lightweight filter components with full metadata."""
    enriched = []
    for comp in lightweight_components:
        source = comp.get("source")
        if source in ("scatter_selection", "table_selection", "map_selection"):
            selection_metadata = {
                "dc_id": comp.get("dc_id"),
                "column_name": comp.get("column_name"),
                "interactive_component_type": "MultiSelect",
                "source": source,
            }
            enriched.append({**comp, "metadata": selection_metadata})
        else:
            comp_index = comp.get("index")
            full_metadata = metadata_by_index.get(str(comp_index), {}) if comp_index else {}
            enriched.append({**comp, "metadata": full_metadata})
    return enriched


def _group_filters_by_dc(components: list[dict]) -> dict[str, list[dict]]:
    """Group filter components by data collection ID."""
    filters_by_dc: dict[str, list[dict]] = {}
    for component in components:
        dc = str(component.get("metadata", {}).get("dc_id", ""))
        if dc:
            filters_by_dc.setdefault(dc, []).append(component)
    return filters_by_dc


def _filter_active_components(components: list[dict]) -> list[dict]:
    """Filter out components with empty or null values."""
    active = []
    for c in components:
        value = c.get("value")
        metadata = c.get("metadata", {})
        if metadata.get("interactive_component_type") == "DateRangePicker":
            if (
                value
                and isinstance(value, list)
                and len(value) == 2
                and value[0] is not None
                and value[1] is not None
            ):
                active.append(c)
        elif value not in [None, [], "", False]:
            active.append(c)
    return active


def _extract_filters_for_map(
    dc_id: str,
    filters_data: dict | None,
    interactive_metadata_list: list | None,
    interactive_metadata_ids: list | None,
    project_metadata: dict | None,
    access_token: str | None = None,
) -> list[dict]:
    """Extract active filters for a specific map's data collection.

    Map components skip their own ``map_selection`` filters so the map always
    renders all points.  Plotly's client-side selected/unselected styling
    handles the visual feedback.  Other filter sources (interactive widgets,
    scatter_selection, table_selection) are still applied.
    """
    if not filters_data or not filters_data.get("interactive_components_values"):
        return []

    metadata_by_index = _build_metadata_index(interactive_metadata_list, interactive_metadata_ids)
    lightweight_components = filters_data.get("interactive_components_values", [])
    enriched = _enrich_filter_components(lightweight_components, metadata_by_index)

    # Exclude map_selection filters — the map should not filter itself.
    # This keeps all points visible; selection styling is handled client-side.
    enriched = [c for c in enriched if c.get("source") != "map_selection"]

    filters_by_dc = _group_filters_by_dc(enriched)

    relevant_filters = filters_by_dc.get(dc_id, [])

    # Include filters resolved via DC links
    link_resolved = extend_filters_via_links(
        target_dc_id=dc_id,
        filters_by_dc=filters_by_dc,
        project_metadata=project_metadata,
        access_token=access_token,
        component_type="map",
    )
    if link_resolved:
        relevant_filters.extend(link_resolved)

    return _filter_active_components(relevant_filters)


def _compute_filters_hash(metadata_to_pass: list[dict]) -> str:
    """Compute hash for filter metadata list."""
    if not metadata_to_pass:
        return "nofilter"
    return hashlib.md5(
        json.dumps(metadata_to_pass, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]


def _load_scatter_overlay(
    component_id: str,
    trigger_data: dict,
    filters_data: dict | None,
    interactive_metadata_list: list | None,
    interactive_metadata_ids: list | None,
    project_metadata: dict | None,
    access_token: str | None,
    build_scatter_overlay_data,
) -> list[dict] | None:
    """Load and filter scatter overlay data for a tiled map component."""
    overlay_dc_id = trigger_data.get("scatter_overlay_dc_id")
    overlay_dc_tag = trigger_data.get("scatter_overlay_dc_tag")

    if not overlay_dc_id:
        if overlay_dc_tag:
            logger.warning(
                f"Tiled map {component_id}: scatter_overlay_dc_tag='{overlay_dc_tag}' present but scatter_overlay_dc_id is None — tag was not resolved during import"
            )
        else:
            logger.info(f"Tiled map {component_id}: no scatter overlay configured")
        return None

    logger.info(f"Tiled map {component_id}: loading scatter overlay dc_id={str(overlay_dc_id)[:8]}")
    wf_id = trigger_data.get("wf_id")
    if not wf_id:
        logger.warning(
            f"Tiled map {component_id}: scatter overlay skipped — no wf_id in trigger_data"
        )
        return None

    overlay_filters = _extract_filters_for_map(
        str(overlay_dc_id),
        filters_data,
        interactive_metadata_list,
        interactive_metadata_ids,
        project_metadata,
        access_token=access_token,
    )
    overlay_df = load_deltatable_lite(
        ObjectId(str(wf_id)),
        ObjectId(str(overlay_dc_id)),
        metadata=overlay_filters,
        TOKEN=access_token,
    )
    if overlay_df is None:
        logger.warning(
            f"Tiled map {component_id}: load_deltatable_lite returned None for overlay dc_id={str(overlay_dc_id)[:8]}"
        )
        return None

    scatter_overlay_data = build_scatter_overlay_data(overlay_df, trigger_data)
    if not scatter_overlay_data:
        logger.warning(
            f"Tiled map {component_id}: build_scatter_overlay_data returned empty list (check lat/lon/color column names)"
        )
    else:
        logger.info(
            f"Tiled map {component_id}: scatter overlay loaded with {len(scatter_overlay_data)} markers"
        )
    return scatter_overlay_data


def register_core_callbacks(app):
    """Register core rendering callbacks for map component."""

    # Clientside callback: update GeoJSON hideout.fill_opacity from slider
    app.clientside_callback(
        """
        function(opacityValues, currentHideouts, sliderIds) {
            if (!opacityValues || !currentHideouts || !sliderIds) {
                return window.dash_clientside.no_update;
            }
            var updated = currentHideouts.map(function(h, i) {
                if (!h) return h;
                // Match slider to geojson by index
                var geojsonIndex = null;
                // Find matching slider value for this geojson
                for (var j = 0; j < sliderIds.length; j++) {
                    if (sliderIds[j] && sliderIds[j].index === (h._geojson_index || null)) {
                        geojsonIndex = j;
                        break;
                    }
                }
                // Fallback: match by position
                if (geojsonIndex === null) geojsonIndex = i;
                if (geojsonIndex < opacityValues.length && opacityValues[geojsonIndex] !== null) {
                    return Object.assign({}, h, {fill_opacity: opacityValues[geojsonIndex]});
                }
                return h;
            });
            return updated;
        }
        """,
        Output({"type": "leaflet-geojson", "index": ALL}, "hideout"),
        Input({"type": "leaflet-opacity-slider", "index": ALL}, "value"),
        State({"type": "leaflet-geojson", "index": ALL}, "hideout"),
        State({"type": "leaflet-opacity-slider", "index": ALL}, "id"),
        prevent_initial_call=True,
    )

    # Tiled map (dash-leaflet) rendering callback — uses its own leaflet-trigger
    # type so it is fully independent of the Plotly render_maps_batch callback.
    @app.callback(
        Output({"type": "leaflet-container", "index": ALL}, "children"),
        Output({"type": "leaflet-scatter-data", "index": ALL}, "data"),
        Output({"type": "leaflet-legend", "index": ALL}, "children"),
        Input({"type": "leaflet-trigger", "index": ALL}, "data"),
        Input("theme-store", "data"),
        State({"type": "leaflet-trigger", "index": ALL}, "id"),
        State("interactive-values-store", "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        State("project-metadata-store", "data"),
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def render_tiled_maps_batch(
        trigger_data_list,
        theme_data,
        trigger_ids,
        filters_data,
        interactive_metadata_list,
        interactive_metadata_ids,
        project_metadata,
        local_data,
    ):
        """Batch rendering of tiled map (dash-leaflet) components."""
        if not trigger_data_list or not trigger_ids:
            raise dash.exceptions.PreventUpdate

        num_maps = len(trigger_ids)
        current_theme = theme_data or "light"
        access_token = local_data.get("access_token") if local_data else None

        if not access_token:
            logger.error("No access_token for tiled map rendering")
            return [html.Div("Auth Error")] * num_maps, [[]] * num_maps, [[]] * num_maps

        from depictio.dash.modules.map_component.leaflet_utils import (
            build_leaflet_map,
            build_scatter_overlay_data,
        )

        all_children = []
        all_scatter_data = []
        all_legends = []

        for i, (trigger_data, trigger_id) in enumerate(zip(trigger_data_list, trigger_ids)):
            if not trigger_data or not isinstance(trigger_data, dict):
                all_children.append(html.Div())
                all_scatter_data.append([])
                all_legends.append([])
                continue

            component_id = trigger_id.get("index", "unknown")

            try:
                # Load GeoJSON from S3 if configured
                geojson_data = None
                geojson_dc_id = trigger_data.get("geojson_dc_id")
                pmtiles_dc_id = trigger_data.get("pmtiles_dc_id")
                source_dc_id = geojson_dc_id or pmtiles_dc_id
                if source_dc_id:
                    from depictio.api.v1.deltatables_utils import load_geojson_from_s3

                    geojson_data = load_geojson_from_s3(source_dc_id, TOKEN=access_token)

                # Load scatter overlay data
                scatter_overlay_data = _load_scatter_overlay(
                    component_id,
                    trigger_data,
                    filters_data,
                    interactive_metadata_list,
                    interactive_metadata_ids,
                    project_metadata,
                    access_token,
                    build_scatter_overlay_data,
                )

                leaflet_component, legend_children = build_leaflet_map(
                    index=component_id,
                    trigger_data=trigger_data,
                    geojson_data=geojson_data,
                    scatter_overlay_data=scatter_overlay_data,
                    theme=current_theme,
                )
                all_children.append(leaflet_component)
                all_scatter_data.append(scatter_overlay_data or [])
                all_legends.append(legend_children)

            except Exception as e:
                logger.error(f"Tiled map render failed for {component_id}: {e}", exc_info=True)
                all_children.append(html.Div(f"Error: {e}"))
                all_scatter_data.append([])
                all_legends.append([])

        return all_children, all_scatter_data, all_legends

    # Clientside callback: metric switching for tiled maps
    # Updates hideout to switch color mode, and toggles pre-built legend divs
    app.clientside_callback(
        """
        function(metricValues, currentHideouts, legendChildren, metricIds, hideoutIds, legendIds) {
            if (!metricValues || !currentHideouts || !metricIds || !hideoutIds) {
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }

            // Build index-to-metric lookup
            var metricByIndex = {};
            for (var i = 0; i < metricIds.length; i++) {
                if (metricIds[i] && metricValues[i]) {
                    metricByIndex[metricIds[i].index] = metricValues[i];
                }
            }

            var updatedHideouts = [];
            var updatedLegends = [];

            for (var j = 0; j < hideoutIds.length; j++) {
                var h = currentHideouts[j];
                if (!h || !h.metrics) {
                    updatedHideouts.push(window.dash_clientside.no_update);
                    updatedLegends.push(window.dash_clientside.no_update);
                    continue;
                }

                var geojsonIndex = hideoutIds[j].index;
                var selectedName = metricByIndex[geojsonIndex];
                if (!selectedName || !h.metrics[selectedName]) {
                    updatedHideouts.push(window.dash_clientside.no_update);
                    updatedLegends.push(window.dash_clientside.no_update);
                    continue;
                }

                var metric = h.metrics[selectedName];
                var newHideout = Object.assign({}, h, {
                    color_prop: metric.property || "land_cover",
                    color_type: metric.type || "categorical"
                });

                if (metric.type === "categorical") {
                    newHideout.color_map = metric.color_map || {};
                    delete newHideout.color_stops;
                    delete newHideout.color_min;
                    delete newHideout.color_max;
                } else if (metric.type === "continuous") {
                    newHideout.color_stops = metric.color_stops || [];
                    newHideout.color_min = metric.color_min !== undefined ? metric.color_min : 0;
                    newHideout.color_max = metric.color_max !== undefined ? metric.color_max : 1;
                    delete newHideout.color_map;
                }

                updatedHideouts.push(newHideout);

                // Toggle legend visibility: show/hide pre-built legend divs by metric name
                var currentLegend = (j < legendChildren.length) ? legendChildren[j] : [];
                if (currentLegend && Array.isArray(currentLegend)) {
                    var newLegend = currentLegend.map(function(item) {
                        if (!item || !item.props) return item;
                        var itemId = item.props.id;
                        if (itemId && itemId.metric) {
                            var copy = Object.assign({}, item);
                            copy.props = Object.assign({}, item.props);
                            copy.props.style = Object.assign({}, item.props.style || {});
                            copy.props.style.display = (itemId.metric === selectedName) ? "block" : "none";
                            return copy;
                        }
                        return item;
                    });
                    updatedLegends.push(newLegend);
                } else {
                    updatedLegends.push(window.dash_clientside.no_update);
                }
            }

            return [updatedHideouts, updatedLegends];
        }
        """,
        Output({"type": "leaflet-geojson", "index": ALL}, "hideout", allow_duplicate=True),
        Output({"type": "leaflet-legend", "index": ALL}, "children", allow_duplicate=True),
        Input({"type": "leaflet-metric-selector", "index": ALL}, "value"),
        State({"type": "leaflet-geojson", "index": ALL}, "hideout"),
        State({"type": "leaflet-legend", "index": ALL}, "children"),
        State({"type": "leaflet-metric-selector", "index": ALL}, "id"),
        State({"type": "leaflet-geojson", "index": ALL}, "id"),
        State({"type": "leaflet-legend", "index": ALL}, "id"),
        prevent_initial_call=True,
    )

    # Plotly map (scatter/density/choropleth) rendering callback
    @app.callback(
        Output({"type": "map-graph", "index": ALL}, "figure"),
        Output({"type": "map-metadata", "index": ALL}, "data"),
        Input({"type": "map-trigger", "index": ALL}, "data"),
        Input("interactive-values-store", "data"),
        Input("theme-store", "data"),
        Input({"type": "map-metric-selector", "index": ALL}, "value"),
        State({"type": "map-trigger", "index": ALL}, "id"),
        State({"type": "map-metadata", "index": ALL}, "data"),
        State({"type": "map-metric-selector", "index": ALL}, "id"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        State("project-metadata-store", "data"),
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def render_maps_batch(
        trigger_data_list,
        filters_data,
        theme_data,
        metric_selector_values,
        trigger_ids,
        existing_metadata_list,
        metric_selector_ids,
        interactive_metadata_list,
        interactive_metadata_ids,
        project_metadata,
        local_data,
    ):
        """Batch rendering of all map components."""
        if not trigger_data_list or not trigger_ids:
            raise dash.exceptions.PreventUpdate

        current_theme = theme_data or "light"
        access_token = local_data.get("access_token") if local_data else None

        if not access_token:
            logger.error("No access_token for map rendering")
            raise dash.exceptions.PreventUpdate

        # Build load registry (dedup DC loads)
        dc_load_registry: dict[LoadKey, list[dict]] = {}
        map_to_load_key: dict[int, LoadKey | None] = {}
        map_to_overlay_key: dict[int, LoadKey | None] = {}

        for i, trigger_data in enumerate(trigger_data_list):
            if not trigger_data or not isinstance(trigger_data, dict):
                map_to_load_key[i] = None
                map_to_overlay_key[i] = None
                continue

            wf_id = trigger_data.get("wf_id")
            dc_id = trigger_data.get("dc_id")
            if not wf_id or not dc_id:
                map_to_load_key[i] = None
                map_to_overlay_key[i] = None
                continue

            wf_id_str = str(wf_id)
            dc_id_str = str(dc_id)

            metadata_to_pass = _extract_filters_for_map(
                dc_id_str,
                filters_data,
                interactive_metadata_list,
                interactive_metadata_ids,
                project_metadata,
                access_token=access_token,
            )

            filters_hash = _compute_filters_hash(metadata_to_pass)
            load_key: LoadKey = (wf_id_str, dc_id_str, filters_hash)

            if load_key not in dc_load_registry:
                dc_load_registry[load_key] = metadata_to_pass

            map_to_load_key[i] = load_key

            # Register scatter overlay DC for parallel loading
            overlay_dc_id = trigger_data.get("scatter_overlay_dc_id")
            if overlay_dc_id:
                overlay_dc_id_str = str(overlay_dc_id)
                overlay_filters = _extract_filters_for_map(
                    overlay_dc_id_str,
                    filters_data,
                    interactive_metadata_list,
                    interactive_metadata_ids,
                    project_metadata,
                    access_token=access_token,
                )
                overlay_hash = _compute_filters_hash(overlay_filters)
                overlay_key: LoadKey = (wf_id_str, overlay_dc_id_str, overlay_hash)
                if overlay_key not in dc_load_registry:
                    dc_load_registry[overlay_key] = overlay_filters
                map_to_overlay_key[i] = overlay_key
            else:
                map_to_overlay_key[i] = None

        # Load DCs in parallel
        dc_cache: dict[LoadKey, Any] = {}

        def load_single_dc(load_key: LoadKey, metadata: list[dict]) -> tuple[LoadKey, Any]:
            wf_id, dc_id, _ = load_key
            try:
                data = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id),
                    metadata=metadata,
                    TOKEN=access_token,
                )
                return load_key, data
            except Exception as e:
                logger.error(f"Map DC load failed: {dc_id[:8]}: {e}", exc_info=True)
                return load_key, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(load_single_dc, key, meta): key
                for key, meta in dc_load_registry.items()
            }
            for future in concurrent.futures.as_completed(futures):
                load_key, data = future.result()
                if data is not None:
                    dc_cache[load_key] = data

        # Extract active map_selection values from the store so the map can
        # highlight selected points without filtering them out of the data.
        map_selection_values: list | None = None
        if filters_data and filters_data.get("interactive_components_values"):
            for comp in filters_data["interactive_components_values"]:
                if comp.get("source") == "map_selection":
                    val = comp.get("value")
                    if val:
                        map_selection_values = val
                    break

        # Build metric selector lookup: map index → selected metric name
        metric_by_index: dict[str, str] = {}
        if metric_selector_values and metric_selector_ids:
            for val, mid in zip(metric_selector_values, metric_selector_ids):
                if val and mid:
                    metric_by_index[mid["index"]] = val

        # Process each map
        all_figures = []
        all_metadata = []

        for i, (trigger_data, trigger_id) in enumerate(zip(trigger_data_list, trigger_ids)):
            component_id = trigger_id.get("index", "unknown")[:8] if trigger_id else "unknown"

            if not trigger_data or not isinstance(trigger_data, dict):
                all_figures.append({"data": [], "layout": {}})
                all_metadata.append({})
                continue

            load_key = map_to_load_key.get(i)
            if not load_key or load_key not in dc_cache:
                all_figures.append({"data": [], "layout": {}})
                all_metadata.append({})
                continue

            df = dc_cache[load_key]

            try:
                prev_metadata = existing_metadata_list[i] if i < len(existing_metadata_list) else {}

                # Load scatter overlay DF if configured
                overlay_key = map_to_overlay_key.get(i)
                overlay_df = dc_cache.get(overlay_key) if overlay_key else None

                # Resolve active metric from SegmentedControl
                map_index = trigger_id.get("index", "") if trigger_id else ""
                selected_metric = metric_by_index.get(map_index)
                if selected_metric:
                    multi_cols = (trigger_data.get("dict_kwargs") or {}).get(
                        "multi_color_columns", []
                    )
                    for mc in multi_cols:
                        if mc.get("name") == selected_metric:
                            trigger_data = {**trigger_data}  # shallow copy
                            trigger_data["_active_color_column"] = mc.get("column")
                            trigger_data["_active_colorscale"] = mc.get("colorscale")
                            trigger_data["_active_color_discrete_map"] = mc.get(
                                "color_discrete_map"
                            )
                            break

                fig, data_info = render_map(
                    df,
                    trigger_data,
                    current_theme,
                    existing_metadata=prev_metadata,
                    active_selection_values=map_selection_values,
                    access_token=access_token,
                    scatter_overlay_df=overlay_df,
                )

                # Convert to dict for serialization
                if hasattr(fig, "to_json"):
                    fig_dict = json.loads(fig.to_json())
                else:
                    fig_dict = fig

                metadata = {
                    "index": component_id,
                    "map_type": trigger_data.get("map_type", "scatter_map"),
                    "rendered_at": time.time(),
                    **data_info,
                }

                all_figures.append(fig_dict)
                all_metadata.append(metadata)

            except Exception as e:
                logger.error(f"Map render failed for component {component_id}: {e}", exc_info=True)
                all_figures.append({"data": [], "layout": {"title": f"Error: {e}"}})
                all_metadata.append({})

        return all_figures, all_metadata
