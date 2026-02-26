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
import uuid
from typing import Any

import dash
from bson import ObjectId
from dash import ALL, Input, Output, State

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


def register_core_callbacks(app):
    """Register core rendering callbacks for map component."""

    @app.callback(
        Output({"type": "map-graph", "index": ALL}, "figure"),
        Output({"type": "map-metadata", "index": ALL}, "data"),
        Input({"type": "map-trigger", "index": ALL}, "data"),
        Input("interactive-values-store", "data"),
        State({"type": "map-trigger", "index": ALL}, "id"),
        State({"type": "map-metadata", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        State("project-metadata-store", "data"),
        State("local-store", "data"),
        State("theme-store", "data"),
        prevent_initial_call=False,
    )
    def render_maps_batch(
        trigger_data_list,
        filters_data,
        trigger_ids,
        existing_metadata_list,
        stored_metadata_list,
        interactive_metadata_list,
        interactive_metadata_ids,
        project_metadata,
        local_data,
        theme_data,
    ):
        """Batch rendering of all map components."""
        batch_task_id = str(uuid.uuid4())[:8]

        if not trigger_data_list or not trigger_ids:
            raise dash.exceptions.PreventUpdate

        current_theme = theme_data or "light"
        access_token = local_data.get("access_token") if local_data else None

        if not access_token:
            logger.error("No access_token for map rendering")
            num_maps = len(trigger_ids)
            empty = {"data": [], "layout": {"title": "Auth Error"}}
            return [empty] * num_maps, [{}] * num_maps

        # Build load registry (dedup DC loads)
        dc_load_registry: dict[LoadKey, list[dict]] = {}
        map_to_load_key: dict[int, LoadKey | None] = {}

        for i, trigger_data in enumerate(trigger_data_list):
            if not trigger_data or not isinstance(trigger_data, dict):
                map_to_load_key[i] = None
                continue

            wf_id = trigger_data.get("wf_id")
            dc_id = trigger_data.get("dc_id")
            if not wf_id or not dc_id:
                map_to_load_key[i] = None
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
                all_figures.append({"data": [], "layout": {"title": "Data not available"}})
                all_metadata.append({})
                continue

            df = dc_cache[load_key]

            try:
                prev_metadata = existing_metadata_list[i] if i < len(existing_metadata_list) else {}
                fig, data_info = render_map(
                    df,
                    trigger_data,
                    current_theme,
                    existing_metadata=prev_metadata,
                    active_selection_values=map_selection_values,
                    access_token=access_token,
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
                logger.error(f"[{batch_task_id}-{i}] Map render failed: {e}", exc_info=True)
                all_figures.append({"data": [], "layout": {"title": f"Error: {e}"}})
                all_metadata.append({})

        return all_figures, all_metadata
