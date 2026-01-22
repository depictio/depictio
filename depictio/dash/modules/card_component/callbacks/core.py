"""
Card Component - Core Rendering Callbacks

This module contains callbacks that are essential for rendering cards in view mode.
These callbacks are always loaded at app startup.

Callbacks:
- update_aggregation_options: Populate aggregation dropdown based on column type
- reset_aggregation_value: Reset aggregation value when column changes
- render_card_value_background: Compute and render card value (two-stage optimization)
- patch_card_with_filters: Update card value when filters change
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
import uuid
from typing import TYPE_CHECKING, Any

import dash
from bson import ObjectId
from dash import ALL, MATCH, Input, Output, State, no_update

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.background_callback_helpers import (
    log_background_callback_status,
    should_use_background_for_component,
)
from depictio.dash.modules.card_component.utils import (
    agg_functions,
    compute_value,
    get_adaptive_trend_colors,
)
from depictio.dash.utils import (
    get_columns_from_data_collection,
    get_component_data,
    get_result_dc_for_workflow,
)

if TYPE_CHECKING:
    import polars as pl

# Use centralized background callback configuration
USE_BACKGROUND_CALLBACKS = should_use_background_for_component("card")


def _enrich_filters_with_metadata(
    filters_data: dict[str, Any] | None,
    interactive_metadata_list: list[dict[str, Any]],
    interactive_metadata_ids: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Enrich lightweight filter store data with full metadata from interactive components.

    This function combines the lightweight filter values (index + value only) with
    their full metadata (column_name, dc_id, component_type, etc.) from the
    interactive-stored-metadata stores.

    Args:
        filters_data: Lightweight filter data containing interactive_components_values
        interactive_metadata_list: Full metadata from all interactive component stores
        interactive_metadata_ids: IDs of all interactive component metadata stores

    Returns:
        List of enriched component dicts with index, value, and full metadata
    """
    # Create index -> metadata mapping
    metadata_by_index: dict[str, dict[str, Any]] = {}
    if interactive_metadata_list and interactive_metadata_ids:
        for i, meta_id in enumerate(interactive_metadata_ids):
            if i < len(interactive_metadata_list):
                index = meta_id["index"]
                metadata_by_index[index] = interactive_metadata_list[i]

    # Enrich lightweight store data with full metadata
    lightweight_components = (
        filters_data.get("interactive_components_values", []) if filters_data else []
    )

    enriched_components: list[dict[str, Any]] = []
    for component in lightweight_components:
        index = component.get("index")
        value = component.get("value")
        full_metadata = metadata_by_index.get(index, {})

        if full_metadata:
            enriched_components.append(
                {
                    "index": index,
                    "value": value,
                    "metadata": full_metadata,
                }
            )
        else:
            logger.warning(f"No metadata found for component {index[:8]}... - skipping")

    logger.debug(
        f"Enriched {len(enriched_components)}/{len(lightweight_components)} components with metadata"
    )

    return enriched_components


def _build_dc_load_registry(
    trigger_data_list: list[dict[str, Any] | None],
    filters_data: dict[str, Any],
) -> tuple[dict[tuple[str, str, str], list[dict[str, Any]]], dict[int, tuple[str, str, str]]]:
    """
    Build registry of unique data collection loads for parallel execution.

    Scans all cards to identify unique (workflow_id, dc_id, filters_hash) combinations
    to avoid redundant data loading when multiple cards share the same data source
    and filter configuration.

    Args:
        trigger_data_list: List of card trigger data containing wf_id, dc_id
        filters_data: Enriched filter data with interactive_components_values

    Returns:
        Tuple of:
        - dc_load_registry: Maps (wf_id, dc_id, filters_hash) -> filter metadata list
        - card_to_load_key: Maps card index -> load key tuple
    """
    dc_load_registry: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    card_to_load_key: dict[int, tuple[str, str, str]] = {}

    for i, trigger_data in enumerate(trigger_data_list):
        if not trigger_data or not isinstance(trigger_data, dict):
            continue

        wf_id = trigger_data.get("wf_id")
        dc_id = trigger_data.get("dc_id")

        if not all([wf_id, dc_id]):
            continue

        # Get filters for this card
        card_dc_str = str(dc_id)
        metadata_list = filters_data.get("interactive_components_values", [])

        # Group filters by DC
        filters_by_dc: dict[str, list[dict[str, Any]]] = {}
        if metadata_list:
            for component in metadata_list:
                component_dc = str(component.get("metadata", {}).get("dc_id"))
                if component_dc not in filters_by_dc:
                    filters_by_dc[component_dc] = []
                filters_by_dc[component_dc].append(component)

        # Get relevant filters for card's DC
        relevant_filters = filters_by_dc.get(card_dc_str, [])

        # Determine if filters are active
        has_active_filters = any(
            c.get("value") not in [None, [], "", False] for c in relevant_filters
        )

        if has_active_filters:
            active_filters = [
                c for c in relevant_filters if c.get("value") not in [None, [], "", False]
            ]
            metadata_to_pass = active_filters
        else:
            metadata_to_pass = []

        # Create stable hash of filters for deduplication
        filter_signature = sorted(
            [
                (c.get("metadata", {}).get("column_name"), str(c.get("value")))
                for c in metadata_to_pass
            ]
        )
        filters_hash = hashlib.md5(
            json.dumps(filter_signature, sort_keys=True).encode()
        ).hexdigest()[:8]

        load_key = (str(wf_id), str(dc_id), filters_hash)

        # Register this unique load
        if load_key not in dc_load_registry:
            dc_load_registry[load_key] = metadata_to_pass

        # Map card to its load key
        card_to_load_key[i] = load_key

    return dc_load_registry, card_to_load_key


def _load_data_collections_parallel(
    dc_load_registry: dict[tuple[str, str, str], list[dict[str, Any]]],
    access_token: str,
    batch_task_id: str,
) -> dict[tuple[str, str, str], pl.DataFrame]:
    """
    Load all unique data collections in parallel using thread pool.

    Executes data loading for all unique DC+filter combinations concurrently
    to minimize total loading time. Uses up to 4 concurrent workers.

    Args:
        dc_load_registry: Maps (wf_id, dc_id, filters_hash) -> filter metadata list
        access_token: Authentication token for API calls
        batch_task_id: Task ID for logging correlation

    Returns:
        Cache dict mapping load_key -> loaded DataFrame
    """

    def load_single_dc(
        load_key: tuple[str, str, str],
        metadata_to_pass: list[dict[str, Any]],
    ) -> tuple[tuple[str, str, str], pl.DataFrame | None]:
        """Load a single DC with filters (thread-safe operation)."""
        wf_id, dc_id, filters_hash = load_key
        try:
            data = load_deltatable_lite(
                ObjectId(wf_id),
                ObjectId(dc_id),
                metadata=metadata_to_pass,
                TOKEN=access_token,
            )
            logger.debug(
                f"   Parallel load: {dc_id[:8]}...{filters_hash} "
                f"({data.height:,} rows x {data.width} cols)"
            )
            return load_key, data
        except Exception as e:
            logger.error(f"   Parallel load failed: {dc_id[:8]}...{filters_hash}: {e}")
            return load_key, None

    dc_cache: dict[tuple[str, str, str], pl.DataFrame] = {}
    parallel_start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_key = {
            executor.submit(load_single_dc, load_key, metadata): load_key
            for load_key, metadata in dc_load_registry.items()
        }

        for future in concurrent.futures.as_completed(future_to_key):
            load_key, data = future.result()
            if data is not None:
                dc_cache[load_key] = data

    parallel_duration = (time.time() - parallel_start) * 1000
    cache_hit_rate = len(dc_cache) / len(dc_load_registry) * 100 if dc_load_registry else 0
    dedup_ratio = len(dc_cache) / len(dc_load_registry) if dc_load_registry else 1

    logger.info(
        f"[{batch_task_id}] Parallel loading complete: "
        f"{len(dc_cache)}/{len(dc_load_registry)} DCs loaded in {parallel_duration:.1f}ms "
        f"(dedup: {dedup_ratio:.1f}x, success: {cache_hit_rate:.0f}%)"
    )

    return dc_cache


def _group_filters_by_dc(
    metadata_list: list[dict[str, Any]] | None,
    dc_configs_map: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Group filter components by their data collection, filtering to table DCs only.

    Groups interactive filter components by their associated data collection ID,
    excluding non-table DC types (MultiQC, JBrowse2) that don't support filtering.

    Args:
        metadata_list: List of enriched filter component metadata
        dc_configs_map: Map of dc_id -> dc_config with type information

    Returns:
        Dict mapping dc_id (str) -> list of filter components for that DC
    """
    filters_by_dc: dict[str, list[dict[str, Any]]] = {}

    if metadata_list:
        for component in metadata_list:
            component_dc = str(component.get("metadata", {}).get("dc_id"))
            if component_dc not in filters_by_dc:
                filters_by_dc[component_dc] = []
            filters_by_dc[component_dc].append(component)

    # Filter to table DCs only
    filters_by_dc_table_only: dict[str, list[dict[str, Any]]] = {}
    for dc_key, dc_filters in filters_by_dc.items():
        if dc_filters:
            component_dc_config = dc_configs_map.get(str(dc_key), {})
            dc_type = component_dc_config.get("type", "table")
            if dc_type == "table":
                filters_by_dc_table_only[dc_key] = dc_filters

    return filters_by_dc_table_only


def _determine_filtering_path(
    card_dc_str: str,
    filters_by_dc: dict[str, list[dict[str, Any]]],
    wf_id: str,
    access_token: str,
) -> tuple[bool, str | None, dict[str, list[dict[str, Any]]]]:
    """
    Determine whether to use joined-DC or same-DC filtering path.

    Analyzes filter distribution across DCs and checks for pre-computed join
    results to determine the optimal filtering strategy.

    Args:
        card_dc_str: String ID of the card's data collection
        filters_by_dc: Dict mapping dc_id -> list of filters
        wf_id: Workflow ID for join result lookup
        access_token: Authentication token for API calls

    Returns:
        Tuple of:
        - use_joined_path: Whether to use joined-DC path
        - result_dc_id: ID of pre-computed join result (if available)
        - filters_by_dc: Potentially modified filters dict (fallback to card DC only)
    """
    has_filters_for_card_dc = card_dc_str in filters_by_dc

    # Determine if we need to perform a join
    needs_join = False
    if not has_filters_for_card_dc and len(filters_by_dc) > 0:
        needs_join = True
        logger.info("Filters on different DC(s), join required")

    logger.info(f"Card DC: {card_dc_str}")
    logger.info(f"Has filters for card DC: {has_filters_for_card_dc}")
    logger.info(f"Needs join: {needs_join}")
    logger.info(f"Filters on {len(filters_by_dc)} DC(s)")

    # Check for pre-computed join result DC
    result_dc_id = get_result_dc_for_workflow(wf_id, access_token)

    # Determine the filtering path
    use_joined_path = needs_join and result_dc_id is not None

    # If filters on multiple DCs but no join config, fall back to SAME-DC
    if len(filters_by_dc) > 1 and not use_joined_path:
        logger.warning(
            f"Filters on {len(filters_by_dc)} DCs but no join config - "
            f"falling back to SAME-DC filtering (card DC only)"
        )
        if card_dc_str in filters_by_dc:
            filters_by_dc = {card_dc_str: filters_by_dc[card_dc_str]}
        else:
            filters_by_dc = {}

    return use_joined_path, result_dc_id, filters_by_dc


def _load_data_for_card(
    use_joined_path: bool,
    result_dc_id: str | None,
    filters_by_dc: dict[str, list[dict[str, Any]]],
    has_active_filters: bool,
    wf_id: str,
    dc_id: str,
    card_dc_str: str,
    card_index: int,
    card_to_load_key: dict[int, tuple[str, str, str]],
    dc_cache: dict[tuple[str, str, str], pl.DataFrame],
    access_token: str,
) -> pl.DataFrame:
    """
    Load data for a card using either joined-DC or same-DC path.

    Handles both filtering paths:
    - Joined-DC: Loads pre-computed join result with combined filters
    - Same-DC: Uses cached data or falls back to synchronous load

    Args:
        use_joined_path: Whether to use joined-DC path
        result_dc_id: ID of pre-computed join result (if using joined path)
        filters_by_dc: Dict mapping dc_id -> list of filters
        has_active_filters: Whether any filters have non-empty values
        wf_id: Workflow ID
        dc_id: Data collection ID
        card_dc_str: String ID of the card's data collection
        card_index: Index of card in batch
        card_to_load_key: Map of card index to load key
        dc_cache: Pre-loaded data cache
        access_token: Authentication token

    Returns:
        Loaded DataFrame with filters applied
    """
    if use_joined_path:
        # JOINED-DC PATH: Load pre-computed join result DC
        logger.info(
            f"JOINED-DC FILTERING: Loading pre-computed join result DC "
            f"with filters from {len(filters_by_dc)} DC(s)"
        )

        # Combine all filters from all DCs
        combined_metadata: list[dict[str, Any]] = []
        for dc_key, dc_filters in filters_by_dc.items():
            if has_active_filters:
                active_filters = [
                    c for c in dc_filters if c.get("value") not in [None, [], "", False]
                ]
                logger.info(f"DC {dc_key}: {len(active_filters)} active filters")
                combined_metadata.extend(active_filters)
            else:
                logger.info(f"DC {dc_key}: No filters (clearing)")

        logger.info(f"Loading result DC {result_dc_id} with {len(combined_metadata)} filters")
        data = load_deltatable_lite(
            ObjectId(wf_id),
            ObjectId(result_dc_id),
            metadata=combined_metadata if combined_metadata else None,
            TOKEN=access_token,
            select_columns=None,
        )

        logger.info(f"Loaded result DC: {data.height:,} rows x {data.width} columns")
        return data

    # SAME-DC PATH: Use cached data or fall back to synchronous load
    load_key = card_to_load_key.get(card_index)

    if load_key and load_key in dc_cache:
        data = dc_cache[load_key]
        logger.info(f"SAME-DC (cached): {dc_id[:8]}... ({data.height:,} rows x {data.width} cols)")
        return data

    # Cache miss - fallback to synchronous load
    relevant_filters = filters_by_dc.get(card_dc_str, [])

    if has_active_filters:
        active_filters = [
            c for c in relevant_filters if c.get("value") not in [None, [], "", False]
        ]
        logger.info(f"SAME-DC filtering - applying {len(active_filters)} active filters")
        metadata_to_pass = active_filters
    else:
        logger.info("SAME-DC clearing filters - loading ALL unfiltered data")
        metadata_to_pass = []

    logger.warning(f"Cache miss for card {card_index} - loading synchronously: {wf_id}:{dc_id}")

    data = load_deltatable_lite(
        ObjectId(wf_id),
        ObjectId(dc_id),
        metadata=metadata_to_pass,
        TOKEN=access_token,
    )

    logger.info(f"Loaded {data.height:,} rows x {data.width} columns")
    return data


def _format_card_value(value: Any) -> tuple[str, float | None]:
    """
    Format a computed card value for display.

    Args:
        value: Raw computed value (numeric or None)

    Returns:
        Tuple of (formatted_string, numeric_value or None)
    """
    try:
        if value is not None:
            formatted = str(round(float(value), 4))
            numeric = float(value)
            return formatted, numeric
        return "N/A", None
    except (ValueError, TypeError):
        return "Error", None


def _create_comparison_components(
    reference_value: float | None,
    current_val: float | None,
    trend_colors: dict[str, str],
) -> list[Any]:
    """
    Create trend comparison UI components showing change from reference.

    Builds visual comparison indicator showing percentage change between
    the current filtered value and the unfiltered reference value.

    Args:
        reference_value: Original unfiltered value
        current_val: Current filtered value
        trend_colors: Dict with 'positive', 'negative', 'neutral' color values

    Returns:
        List of Dash components (icon + text) for the comparison, or empty list
    """
    if reference_value is None or current_val is None:
        return []

    try:
        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        ref_val = float(reference_value)

        if ref_val != 0:
            change_pct = ((current_val - ref_val) / ref_val) * 100
            if change_pct > 0:
                comparison_text = f"+{change_pct:.1f}% vs unfiltered ({ref_val})"
                comparison_color = trend_colors["positive"]
                comparison_icon = "mdi:trending-up"
            elif change_pct < 0:
                comparison_text = f"{change_pct:.1f}% vs unfiltered ({ref_val})"
                comparison_color = trend_colors["negative"]
                comparison_icon = "mdi:trending-down"
            else:
                comparison_text = f"Same as unfiltered ({ref_val})"
                comparison_color = trend_colors["neutral"]
                comparison_icon = "mdi:trending-neutral"
        else:
            comparison_text = f"Reference: {ref_val}"
            comparison_color = trend_colors["neutral"]
            comparison_icon = "mdi:information-outline"

        return [
            DashIconify(icon=comparison_icon, width=14, color=comparison_color),
            dmc.Text(
                comparison_text,
                size="xs",
                fw="normal",
                style={"margin": "0", "color": comparison_color},
            ),
        ]
    except (ValueError, TypeError) as e:
        logger.warning(f"Error creating comparison: {e}")
        return []


def register_core_callbacks(app):
    """Register core rendering callbacks for card component."""

    # Log background callback status for card component
    log_background_callback_status("card", "render_card_value_background")
    log_background_callback_status("card", "patch_card_with_filters_batch")

    # SIMPLE NOTIFICATION: Show notification when filters change (same pattern as save button)
    @app.callback(
        Output("notification-container", "sendNotifications", allow_duplicate=True),
        Input("interactive-values-store", "data"),
        prevent_initial_call=True,
    )
    def show_card_update_notification(filters_data):
        """Show notification when cards are updating from filter changes."""
        from dash_iconify import DashIconify

        # Skip on first load
        if not filters_data or filters_data.get("first_load") is True:
            raise dash.exceptions.PreventUpdate

        # Return notification dict with spinning loader
        return [
            {
                "id": "card-update",
                "title": "Updating",
                "message": "",
                "color": "blue",
                "icon": DashIconify(icon="eos-icons:loading", width=20),
                # "autoClose": 2000,  # Smoother transition with longer duration
            }
        ]

    @app.callback(
        Output({"type": "card-dropdown-aggregation", "index": MATCH}, "data"),
        [
            Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "card-dropdown-column", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
            State("project-metadata-store", "data"),  # ✅ NEW: Read from cache instead of API
        ],
        prevent_initial_call=True,
    )
    def update_aggregation_options(
        column_name, wf_tag, dc_tag, component_id, local_data, pathname, project_metadata
    ):
        """
        Callback to update aggregation dropdown options based on the selected column
        """
        logger.info("=== CARD AGGREGATION OPTIONS CALLBACK START ===")
        logger.info(f"column_name: {column_name}")
        logger.info(f"wf_tag: {wf_tag}")
        logger.info(f"dc_tag: {dc_tag}")
        logger.info(f"component_id: {component_id}")
        logger.info(f"local_data available: {local_data is not None}")
        logger.info(f"pathname: {pathname}")

        if not local_data:
            logger.error("No local_data available!")
            return []

        TOKEN = local_data["access_token"]

        # If workflow/dc tags are missing, try to get from component data (edit mode or pre-population)
        if not wf_tag or not dc_tag:
            input_id = str(component_id["index"])
            logger.info(
                f"Missing wf/dc tags - fetching component data for component_id: {input_id}"
            )

            # Extract dashboard_id from pathname
            # URL formats: /dashboard/{id}/component/add/{uuid} or /dashboard/{id}/component/edit/{uuid}
            path_parts = pathname.split("/")
            if "/component/add/" in pathname or "/component/edit/" in pathname:
                dashboard_id = path_parts[2]  # Both add and edit have dashboard_id at index 2
            else:
                dashboard_id = path_parts[-1]  # Fallback for regular dashboard URLs

            component_data = get_component_data(
                input_id=input_id, dashboard_id=dashboard_id, TOKEN=TOKEN
            )
            if component_data:
                wf_tag = component_data.get("wf_id")
                dc_tag = component_data.get("dc_id")
                logger.info(f"Retrieved from component_data - wf_tag: {wf_tag}, dc_tag: {dc_tag}")

        index = str(component_id["index"])
        logger.info(f"index: {index}")
        logger.info(f"Final wf_tag: {wf_tag}")
        logger.info(f"Final dc_tag: {dc_tag}")

        # If any essential parameters are None, return empty list
        if not wf_tag or not dc_tag:
            logger.error(
                f"Missing essential workflow/dc parameters - wf_tag: {wf_tag}, dc_tag: {dc_tag}"
            )
            return []

        # If column_name is None, return empty list (but still log the attempt)
        if not column_name:
            logger.info(
                "Column name is None - returning empty list (this is normal on initial load)"
            )
            return []

        # ✅ CACHE OPTIMIZATION: Get columns from project-metadata-store (no API call)
        logger.info("Extracting columns from project-metadata-store cache...")
        cols_json = None

        if not project_metadata:
            logger.error("❌ project-metadata-store is empty! Cache not populated yet.")
            # Fallback to API call if cache not ready (shouldn't happen with consolidated_api)
            TOKEN = local_data["access_token"]
            cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
        else:
            # Extract column_specs from project metadata cache
            project_data = project_metadata.get("project", {})
            for wf in project_data.get("workflows", []):
                # Match workflow by tag or ID
                if wf.get("workflow_tag") == wf_tag or str(wf.get("_id")) == wf_tag:
                    for dc in wf.get("data_collections", []):
                        # Match data collection by tag/name or ID
                        if dc.get("name") == dc_tag or str(dc.get("_id")) == dc_tag:
                            # Extract column_specs from last_aggregation
                            last_agg = dc.get("last_aggregation", {})
                            cols_json = last_agg.get("column_specs") or last_agg.get("columns")
                            if cols_json:
                                logger.info("✅ Extracted column_specs from cache (no API call)")
                                break
                    if cols_json:
                        break

            if not cols_json:
                logger.warning(f"⚠️ Column specs not found in cache for wf={wf_tag}, dc={dc_tag}")
                # Fallback to API call
                TOKEN = local_data["access_token"]
                cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)

        logger.info(f"cols_json keys: {list(cols_json.keys()) if cols_json else 'None'}")

        # Check if cols_json is valid and contains the column
        if not cols_json:
            logger.error("cols_json is empty or None!")
            return []

        if column_name not in cols_json:
            logger.error(f"column_name '{column_name}' not found in cols_json!")
            logger.error(f"Available columns: {list(cols_json.keys())}")
            return []

        if "type" not in cols_json[column_name]:
            logger.error(f"'type' field missing for column '{column_name}'")
            logger.error(f"Available fields: {list(cols_json[column_name].keys())}")
            return []

        # Get the type of the selected column
        column_type = cols_json[column_name]["type"]
        logger.info(f"column_type: {column_type}")

        # Get the aggregation functions available for the selected column type
        if str(column_type) not in agg_functions:
            logger.error(f"Column type '{column_type}' not found in agg_functions!")
            logger.error(f"Available types: {list(agg_functions.keys())}")
            return []

        agg_functions_tmp_methods = agg_functions[str(column_type)]["card_methods"]
        logger.info(f"agg_functions_tmp_methods: {agg_functions_tmp_methods}")

        # Create a list of options for the dropdown
        options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]
        logger.info(f"Final options to return: {options}")
        logger.info("=== CARD AGGREGATION OPTIONS CALLBACK END ===")

        return options

    # Callback to reset aggregation dropdown value based on the selected column
    @app.callback(
        Output({"type": "card-dropdown-aggregation", "index": MATCH}, "value"),
        Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def reset_aggregation_value(column_name: str | None) -> None:
        """Reset aggregation dropdown value when column selection changes."""
        return None

    # OPTION A: Batch rendering - Process ALL cards in single callback (700ms total instead of 9×700ms)
    @app.callback(
        Output({"type": "card-value", "index": ALL}, "children"),
        Output({"type": "card-metadata-initial", "index": ALL}, "data"),
        Input({"type": "card-trigger", "index": ALL}, "data"),
        State({"type": "card-trigger", "index": ALL}, "id"),
        State("project-metadata-store", "data"),
        State({"type": "card-metadata-initial", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "id"),
        State("dashboard-init-data", "data"),
        State("local-store", "data"),
        prevent_initial_call=False,
        background=USE_BACKGROUND_CALLBACKS,
    )
    def render_card_value_background(
        trigger_data_list,
        trigger_ids,
        project_metadata,
        existing_metadata_list,
        stored_metadata_list,
        stored_metadata_ids,
        dashboard_init_data,
        local_data,
    ):
        """
        BATCH RENDERING: Process ALL cards in single callback (Option A optimization).

        Instead of 9 callbacks × 700ms = 6.3s, this processes all cards in one callback = 700ms total.
        Backend work is parallelized internally, Dash framework overhead happens once instead of 9x.
        """
        import time
        import uuid

        from bson import ObjectId
        from dash import no_update

        from depictio.api.v1.deltatables_utils import load_deltatable_lite
        from depictio.dash.modules.card_component.utils import compute_value

        batch_start = time.time()
        task_id = str(uuid.uuid4())[:8]

        logger.info(f"[{task_id}] 🚀 BATCH CARD RENDER START - {len(trigger_data_list)} cards")

        # Early exit checks
        if not trigger_data_list or not any(trigger_data_list):
            logger.info("No triggers ready yet")
            return [no_update] * len(trigger_data_list), [no_update] * len(trigger_data_list)

        # Extract auth token
        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access token")
            return ["Auth Error"] * len(trigger_data_list), [{}] * len(trigger_data_list)

        # Extract delta_locations from project metadata (if available)
        # Background callbacks: project_metadata might not serialize, so use empty dict as fallback
        # load_deltatable_lite will fetch locations internally if not provided
        delta_locations = {}
        if project_metadata and isinstance(project_metadata, dict):
            project_data = project_metadata.get("project", {})
            for wf in project_data.get("workflows", []):
                for dc in wf.get("data_collections", []):
                    dc_id = str(dc.get("_id"))
                    if dc.get("delta_location"):
                        delta_locations[dc_id] = {
                            "delta_location": dc["delta_location"],
                            "size_bytes": -1,
                        }
            logger.debug(f"Using {len(delta_locations)} delta locations from project metadata")
        else:
            logger.debug(
                "No project metadata available - load_deltatable_lite will fetch locations"
            )

        # Process all cards
        all_values = []
        all_metadata = []

        for i, (trigger_data, trigger_id, existing_meta, stored_meta, stored_id) in enumerate(
            zip(
                trigger_data_list,
                trigger_ids,
                existing_metadata_list,
                stored_metadata_list,
                stored_metadata_ids,
            )
        ):
            card_start = time.time()
            component_id = trigger_id.get("index", "unknown")[:8] if trigger_id else "unknown"

            # Idempotency check
            metadata_to_use = existing_meta if existing_meta else stored_meta
            if metadata_to_use and metadata_to_use.get("reference_value") is not None:
                reference_value = metadata_to_use.get("reference_value")
                formatted_value = str(reference_value) if reference_value is not None else "N/A"
                all_values.append(formatted_value)
                all_metadata.append(metadata_to_use)
                logger.debug(f"  Card {i + 1}/{len(trigger_data_list)}: {component_id} - cached")
                continue

            # Skip if trigger not ready
            if not trigger_data or not isinstance(trigger_data, dict):
                all_values.append(no_update)
                all_metadata.append(no_update)
                continue

            try:
                # Extract params
                wf_id = trigger_data.get("wf_id")
                dc_id = trigger_data.get("dc_id")
                column_name = trigger_data.get("column_name")
                aggregation = trigger_data.get("aggregation")

                if not all([wf_id, dc_id, column_name, aggregation]):
                    all_values.append("Error")
                    all_metadata.append({"error": "Missing parameters"})
                    continue

                # Get column specs
                cols_json = {}
                if dashboard_init_data and "column_specs" in dashboard_init_data:
                    cols_json = dashboard_init_data.get("column_specs", {}).get(str(dc_id), {})

                # Load data
                if isinstance(dc_id, str) and "--" in dc_id:
                    data = load_deltatable_lite(
                        workflow_id=ObjectId(wf_id),
                        data_collection_id=dc_id,
                        TOKEN=access_token,
                        init_data=delta_locations,
                    )
                else:
                    data = load_deltatable_lite(
                        workflow_id=ObjectId(wf_id),
                        data_collection_id=ObjectId(dc_id),
                        TOKEN=access_token,
                        init_data=delta_locations,
                    )

                # Compute value (no filters at initial load)
                value = compute_value(
                    data, column_name, aggregation, cols_json=cols_json, has_filters=False
                )

                # Format value
                try:
                    if value is not None:
                        formatted_value = str(round(float(value), 4))
                    else:
                        formatted_value = "N/A"
                except (ValueError, TypeError):
                    formatted_value = "Error"

                # Create metadata
                metadata = {
                    "reference_value": value,
                    "column_name": column_name,
                    "aggregation": aggregation,
                    "wf_id": wf_id,
                    "dc_id": dc_id,
                    "cols_json": cols_json,
                    "delta_locations_available": True,
                    "has_been_patched": False,
                }

                all_values.append(formatted_value)
                all_metadata.append(metadata)

                card_duration = (time.time() - card_start) * 1000
                logger.info(
                    f"  Card {i + 1}/{len(trigger_data_list)}: {component_id} - {formatted_value} ({card_duration:.1f}ms)"
                )

            except Exception as e:
                logger.error(
                    f"  Card {i + 1}/{len(trigger_data_list)}: {component_id} - Error: {e}"
                )
                all_values.append("Error")
                all_metadata.append({"error": str(e)})

        batch_duration = (time.time() - batch_start) * 1000
        logger.info(
            f"[{task_id}] ✅ BATCH RENDER COMPLETE - {len(all_values)} cards in {batch_duration:.1f}ms"
        )

        return all_values, all_metadata

    def is_default_value(component: dict) -> bool:
        """
        Check if an interactive component's value matches its default state.

        Compares current value against stored default_state metadata to detect
        whether user has interacted with the filter.

        Args:
            component: Enriched component dict with 'value', 'metadata', etc.

        Returns:
            True if value matches default, False if user has modified it
        """
        current_value = component.get("value")
        metadata = component.get("metadata", {})
        default_state = metadata.get("default_state", {})
        component_type = metadata.get("interactive_component_type")

        # Handle Select-type components (Select, MultiSelect, SegmentedControl)
        if component_type in ["Select", "MultiSelect", "SegmentedControl"]:
            default_value = default_state.get("default_value")

            # Handle semantic equivalence: None and [] both mean "All" / no filter
            # For MultiSelect: default_value=None but component returns []
            # For Select: default_value=None and component returns None
            if default_value is None:
                return current_value is None or current_value == []

            # Otherwise do direct comparison
            return current_value == default_value

        # Handle RangeSlider
        elif component_type == "RangeSlider":
            default_range = default_state.get("default_range")

            # Validate both are lists with 2 elements
            if not isinstance(current_value, list) or not isinstance(default_range, list):
                return False
            if len(current_value) != 2 or len(default_range) != 2:
                return False

            # Compare with floating point tolerance (round to 2 decimals)
            return round(current_value[0], 2) == round(default_range[0], 2) and round(
                current_value[1], 2
            ) == round(default_range[1], 2)

        # Handle DateRangePicker
        elif component_type == "DateRangePicker":
            default_range = default_state.get("default_range")

            # Validate both are lists
            if not isinstance(current_value, list) or not isinstance(default_range, list):
                return False

            # Normalize to strings for comparison
            current_str = [str(v) for v in current_value]
            default_str = [str(v) for v in default_range]

            return current_str == default_str

        # Handle Slider (uses same structure as RangeSlider)
        elif component_type == "Slider":
            default_range = default_state.get("default_range")
            if not isinstance(default_range, list) or len(default_range) != 2:
                return False

            # Slider value is single number, compare against range
            # Default is typically max value or midpoint
            if current_value is None:
                return False
            default_value = default_range[1]  # Use max as default
            return round(float(current_value), 2) == round(float(default_value), 2)

        # Unknown component type - conservatively assume not default
        logger.warning(f"Unknown component type for default comparison: {component_type}")
        return False

    # BATCH FILTERING: ALL pattern - process all card filter updates in single callback (700ms instead of N×700ms)
    @app.callback(
        Output({"type": "card-value", "index": ALL}, "children", allow_duplicate=True),
        Output({"type": "card-comparison", "index": ALL}, "children", allow_duplicate=True),
        Output(
            {"type": "card-metadata", "index": ALL}, "data"
        ),  # No allow_duplicate - only patch writes here
        Input("interactive-values-store", "data"),
        State(
            {"type": "card-metadata-initial", "index": ALL}, "data"
        ),  # Read reference_value from initial store
        State(
            {"type": "card-metadata", "index": ALL}, "data"
        ),  # Read has_been_patched from patch store
        State(
            {"type": "stored-metadata-component", "index": ALL}, "data"
        ),  # Fallback metadata from database
        State({"type": "card-trigger", "index": ALL}, "data"),
        State({"type": "card-trigger", "index": ALL}, "id"),  # Add: Need IDs for indexing
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "id"),
        State("dashboard-init-data", "data"),  # REFACTORING: Access centralized dc_configs
        State("local-store", "data"),  # SECURITY: Access token from centralized store
        prevent_initial_call=True,
        background=USE_BACKGROUND_CALLBACKS,  # Use centralized background callback config
    )
    def patch_card_with_filters_batch(
        filters_data,
        initial_metadata_list,  # List: From card-metadata-initial (has reference_value)
        patch_metadata_list,  # List: From card-metadata (has has_been_patched)
        stored_metadata_list,  # List: Fallback metadata from database
        trigger_data_list,  # List: Card trigger data
        trigger_ids,  # List: Card trigger IDs for indexing
        interactive_metadata_list,
        interactive_metadata_ids,
        dashboard_init_data,
        local_data,
    ):
        """
        BATCH FILTERING: Process all card filter updates in single callback.

        Triggers when interactive filters change. Applies filters to data for ALL cards
        simultaneously, reducing N x 700ms to 1 x 700ms.

        This function coordinates several phases:
        1. Enrichment: Combines lightweight filter values with full metadata
        2. Parallel Loading: Pre-loads unique DC+filter combinations concurrently
        3. Per-Card Processing: Computes filtered values and comparisons for each card

        Args:
            filters_data: Interactive filter values (lightweight: index + value only)
            initial_metadata_list: List of initial card metadata with reference_value
            patch_metadata_list: List of card patch metadata
            stored_metadata_list: List of fallback metadata
            trigger_data_list: List of card trigger data
            trigger_ids: List of card trigger IDs for indexing
            interactive_metadata_list: Full metadata from all interactive components
            interactive_metadata_ids: IDs of all interactive component metadata stores
            dashboard_init_data: Dashboard initialization data
            local_data: Local store data (access_token)

        Returns:
            tuple: Lists of (formatted_values, comparison_components, metadata)
        """
        from dash import callback_context as ctx

        # Generate batch task correlation ID and start timing
        batch_task_id = str(uuid.uuid4())[:8]
        batch_start_time = time.time()

        # Log batch callback execution
        triggered_by = ctx.triggered_id if ctx.triggered else "initial"
        logger.info(
            f"[{batch_task_id}] CARD PATCH BATCH START - {len(trigger_ids)} cards, "
            f"Triggered by: {triggered_by}"
        )

        # Handle dashboards with no interactive components
        if not interactive_metadata_list or not interactive_metadata_ids:
            logger.debug("No interactive components - preventing update (no filters to apply)")
            raise dash.exceptions.PreventUpdate

        # Phase 1: Enrich lightweight store data with full metadata (shared for all cards)
        logger.debug("Enriching lightweight store data with full metadata (shared setup)")
        enriched_components = _enrich_filters_with_metadata(
            filters_data, interactive_metadata_list, interactive_metadata_ids
        )
        filters_data = {"interactive_components_values": enriched_components}

        # Extract access_token from local-store
        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access_token available in local-store")
            num_cards = len(trigger_ids)
            return (["Auth Error"] * num_cards, [[]] * num_cards, [{}] * num_cards)

        # Phase 2: Pre-load unique DC+filter combinations in parallel
        logger.info(f"[{batch_task_id}] Analyzing {len(trigger_ids)} cards for parallel loading")
        dc_load_registry, card_to_load_key = _build_dc_load_registry(
            trigger_data_list, filters_data
        )
        logger.info(
            f"[{batch_task_id}] Found {len(dc_load_registry)} unique DC loads "
            f"for {len(card_to_load_key)} cards"
        )

        dc_cache = _load_data_collections_parallel(dc_load_registry, access_token, batch_task_id)

        # Phase 3: Process each card
        all_values: list[Any] = []
        all_comparisons: list[Any] = []
        all_metadata: list[dict[str, Any]] = []

        for i, (
            initial_metadata,
            patch_metadata,
            stored_metadata,
            trigger_data,
            trigger_id,
        ) in enumerate(
            zip(
                initial_metadata_list,
                patch_metadata_list,
                stored_metadata_list,
                trigger_data_list,
                trigger_ids,
            )
        ):
            result = _process_single_card(
                card_index=i,
                batch_task_id=batch_task_id,
                total_cards=len(trigger_ids),
                initial_metadata=initial_metadata,
                patch_metadata=patch_metadata,
                stored_metadata=stored_metadata,
                trigger_data=trigger_data,
                trigger_id=trigger_id,
                enriched_components=enriched_components,
                filters_data=filters_data,
                dashboard_init_data=dashboard_init_data,
                card_to_load_key=card_to_load_key,
                dc_cache=dc_cache,
                access_token=access_token,
                is_default_value_func=is_default_value,
            )
            all_values.append(result[0])
            all_comparisons.append(result[1])
            all_metadata.append(result[2])

        # Log batch completion
        batch_duration_ms = (time.time() - batch_start_time) * 1000
        logger.info(
            f"[{batch_task_id}] CARD PATCH BATCH COMPLETE - "
            f"{len(trigger_ids)} cards in {batch_duration_ms:.1f}ms"
        )

        return all_values, all_comparisons, all_metadata


def _process_single_card(
    card_index: int,
    batch_task_id: str,
    total_cards: int,
    initial_metadata: dict[str, Any] | None,
    patch_metadata: dict[str, Any] | None,
    stored_metadata: dict[str, Any] | None,
    trigger_data: dict[str, Any] | None,
    trigger_id: dict[str, Any] | None,
    enriched_components: list[dict[str, Any]],
    filters_data: dict[str, Any],
    dashboard_init_data: dict[str, Any] | None,
    card_to_load_key: dict[int, tuple[str, str, str]],
    dc_cache: dict[tuple[str, str, str], Any],
    access_token: str,
    is_default_value_func: Any,
) -> tuple[Any, Any, dict[str, Any]]:
    """
    Process a single card in the batch filtering operation.

    Handles all the logic for computing filtered values and comparisons for one card,
    including early exits for various edge cases (metadata not ready, non-table DC types,
    missing data source, etc.).

    Args:
        card_index: Index of the card in the batch
        batch_task_id: Correlation ID for logging
        total_cards: Total number of cards in batch
        initial_metadata: Initial card metadata (has reference_value)
        patch_metadata: Card patch metadata (has has_been_patched)
        stored_metadata: Fallback metadata from database
        trigger_data: Card trigger data with wf_id, dc_id, column_name, aggregation
        trigger_id: Card trigger ID for logging
        enriched_components: List of enriched filter components
        filters_data: Dict with interactive_components_values
        dashboard_init_data: Dashboard initialization data
        card_to_load_key: Map of card index to load key
        dc_cache: Pre-loaded data cache
        access_token: Authentication token
        is_default_value_func: Function to check if component value is at default

    Returns:
        Tuple of (formatted_value, comparison_components, updated_metadata)
    """
    task_id = f"{batch_task_id}-{card_index}"
    component_id = trigger_id.get("index", "unknown")[:8] if trigger_id else "unknown"
    card_start_time = time.time()

    try:
        logger.debug(f"[{task_id}] Processing card {card_index + 1}/{total_cards}: {component_id}")

        # Check for user interaction and race conditions
        early_exit = _check_card_early_exit_conditions(
            enriched_components=enriched_components,
            initial_metadata=initial_metadata,
            patch_metadata=patch_metadata,
            stored_metadata=stored_metadata,
            trigger_data=trigger_data,
            component_id=component_id,
            task_id=task_id,
            card_start_time=card_start_time,
            is_default_value_func=is_default_value_func,
        )
        if early_exit is not None:
            return early_exit

        # Get metadata for patch operations (early_exit check guarantees these are not None)
        metadata_for_patch = initial_metadata if initial_metadata else stored_metadata
        assert metadata_for_patch is not None
        assert trigger_data is not None

        # Extract parameters
        wf_id = trigger_data.get("wf_id")
        dc_id = trigger_data.get("dc_id")
        column_name = trigger_data.get("column_name")
        aggregation = trigger_data.get("aggregation")
        reference_value = metadata_for_patch.get("reference_value")

        # Skip patching for dummy/random cards (no data source)
        if not all([wf_id, dc_id, column_name, aggregation]):
            duration_ms = (time.time() - card_start_time) * 1000
            formatted_value, _ = _format_card_value(metadata_for_patch.get("reference_value"))
            logger.info(
                f"[{task_id}] CARD PATCH COMPLETE - Component: {component_id} - "
                f"Duration: {duration_ms:.2f}ms (no data source)"
            )
            return formatted_value, [], {}

        # At this point wf_id and dc_id are guaranteed to be non-None
        wf_id_str = str(wf_id)
        dc_id_str = str(dc_id)

        # Get dc_configs for type checking
        dc_configs_map: dict[str, dict[str, Any]] = {}
        if dashboard_init_data and "dc_configs" in dashboard_init_data:
            dc_configs_map = dashboard_init_data.get("dc_configs", {})

        # Check if card's DC is non-table type (skip filtering)
        dc_config = dc_configs_map.get(dc_id_str, {})
        card_dc_type = dc_config.get("type", "table")
        if card_dc_type in ["multiqc", "jbrowse2"]:
            duration_ms = (time.time() - card_start_time) * 1000
            formatted_value, _ = _format_card_value(reference_value)
            logger.info(
                f"[{task_id}] CARD PATCH COMPLETE - Component: {component_id} - "
                f"Duration: {duration_ms:.2f}ms (non-table DC type)"
            )
            return formatted_value, [], {}

        # Group filters by DC and filter to table-only
        metadata_list = filters_data.get("interactive_components_values")
        filters_by_dc = _group_filters_by_dc(metadata_list, dc_configs_map)

        # Check for active filters
        has_active_filters = _has_active_filter_values(metadata_list)
        if has_active_filters:
            logger.info("Active filters detected - loading filtered data")
        else:
            logger.info("No active filters - loading ALL unfiltered data")

        # Determine filtering path (joined vs same-DC)
        use_joined_path, result_dc_id, filters_by_dc = _determine_filtering_path(
            dc_id_str, filters_by_dc, wf_id_str, access_token
        )

        # Load data using appropriate path
        data = _load_data_for_card(
            use_joined_path=use_joined_path,
            result_dc_id=result_dc_id,
            filters_by_dc=filters_by_dc,
            has_active_filters=has_active_filters,
            wf_id=wf_id_str,
            dc_id=dc_id_str,
            card_dc_str=dc_id_str,
            card_index=card_index,
            card_to_load_key=card_to_load_key,
            dc_cache=dc_cache,
            access_token=access_token,
        )

        logger.debug("Loaded filtered data")

        # Get column specs for optimization
        cols_json: dict[str, Any] = {}
        if dashboard_init_data and "column_specs" in dashboard_init_data:
            cols_json = dashboard_init_data.get("column_specs", {}).get(dc_id_str, {})

        # Compute new value on filtered data
        compute_start = time.time()
        current_value = compute_value(
            data, column_name, aggregation, cols_json=cols_json, has_filters=has_active_filters
        )
        compute_duration = (time.time() - compute_start) * 1000
        logger.info(
            f"[{task_id}] Computation: {compute_duration:.1f}ms "
            f"({aggregation} on {column_name}, result={current_value})"
        )

        # Format current value
        formatted_value, current_val = _format_card_value(current_value)

        # Get adaptive trend colors and create comparison
        background_color = trigger_data.get("background_color") or None
        trend_colors = get_adaptive_trend_colors(background_color)
        logger.debug(
            f"Using adaptive trend colors for background '{background_color}': {trend_colors}"
        )

        comparison_components = _create_comparison_components(
            reference_value, current_val, trend_colors
        )

        duration_ms = (time.time() - card_start_time) * 1000
        logger.info(f"CARD PATCH: Value updated successfully: {formatted_value}")
        logger.info(
            f"[{task_id}] CARD PATCH COMPLETE - Component: {component_id} - "
            f"Duration: {duration_ms:.2f}ms (success)"
        )

        # Update metadata to mark card as patched
        updated_metadata = patch_metadata.copy() if patch_metadata else {}
        updated_metadata["has_been_patched"] = True

        return formatted_value, comparison_components, updated_metadata

    except Exception as e:
        duration_ms = (time.time() - card_start_time) * 1000
        logger.error(f"CARD PATCH: Error applying filters: {e}", exc_info=True)
        logger.error(
            f"[{task_id}] CARD PATCH COMPLETE - Component: {component_id} - "
            f"Duration: {duration_ms:.2f}ms (error)"
        )
        return "Error", [], {}


def _check_card_early_exit_conditions(
    enriched_components: list[dict[str, Any]],
    initial_metadata: dict[str, Any] | None,
    patch_metadata: dict[str, Any] | None,
    stored_metadata: dict[str, Any] | None,
    trigger_data: dict[str, Any] | None,
    component_id: str,
    task_id: str,
    card_start_time: float,
    is_default_value_func: Any,
) -> tuple[Any, Any, Any] | None:
    """
    Check for early exit conditions in card processing.

    Handles various scenarios where card processing should return early:
    - First patch with default values but reference not ready (race condition)
    - Metadata or trigger data not ready
    - Reference value not populated yet

    Args:
        enriched_components: List of enriched filter components
        initial_metadata: Initial card metadata
        patch_metadata: Card patch metadata
        stored_metadata: Fallback metadata from database
        trigger_data: Card trigger data
        component_id: Component ID for logging
        task_id: Task ID for logging
        card_start_time: Start time for duration calculation
        is_default_value_func: Function to check if component value is at default

    Returns:
        Early exit result tuple if should exit, None to continue processing
    """
    if enriched_components:
        # Find components that differ from their defaults
        modified_components = [
            comp for comp in enriched_components if not is_default_value_func(comp)
        ]

        has_been_patched = (
            patch_metadata.get("has_been_patched", False) if patch_metadata else False
        )
        metadata_to_use = initial_metadata if initial_metadata else stored_metadata
        reference_value = metadata_to_use.get("reference_value") if metadata_to_use else None

        # Log debug info
        logger.debug(f"CARD PATCH DEBUG - Component: {component_id}")
        logger.debug(f"   initial_metadata type: {type(initial_metadata)}")
        logger.debug(
            f"   initial_metadata keys: {initial_metadata.keys() if initial_metadata else 'N/A'}"
        )
        logger.debug(f"   stored_metadata type: {type(stored_metadata)}")
        logger.debug(
            f"   stored_metadata has reference_value: "
            f"{stored_metadata.get('reference_value') if stored_metadata else 'N/A'}"
        )
        logger.debug(
            f"   reference_value (using {'initial' if initial_metadata else 'stored'}): "
            f"{reference_value}"
        )
        logger.debug(f"   has_been_patched: {has_been_patched}")

        if not modified_components and not has_been_patched:
            # Race condition check: reference_value must be populated before first patch
            if reference_value is None:
                duration_ms = (time.time() - card_start_time) * 1000
                logger.debug(
                    "CARD PATCH: First patch triggered but reference_value not ready - "
                    "deferring (returning no_update)"
                )
                logger.info(
                    f"[{task_id}] CARD PATCH COMPLETE - Component: {component_id} - "
                    f"Duration: {duration_ms:.2f}ms (reference not ready)"
                )
                return no_update, no_update, no_update

            logger.debug(
                f"CARD PATCH: First patch with default values - allowing to initialize card data "
                f"(components: {[c.get('metadata', {}).get('column_name', 'unknown') for c in enriched_components]})"
            )
        else:
            logger.debug(
                f"CARD PATCH: Detected user interaction on "
                f"{len(modified_components)}/{len(enriched_components)} filters "
                f"(modified: {[c.get('metadata', {}).get('column_name', 'unknown') for c in modified_components]})"
            )

    # Check if metadata and trigger_data are properly populated
    metadata_for_patch = initial_metadata if initial_metadata else stored_metadata
    if metadata_for_patch is None or trigger_data is None:
        duration_ms = (time.time() - card_start_time) * 1000
        logger.info(
            f"[{task_id}] CARD PATCH COMPLETE - Component: {component_id} - "
            f"Duration: {duration_ms:.2f}ms (metadata/trigger not ready)"
        )
        return "...", [], {}

    # Check if reference_value has been populated
    if metadata_for_patch.get("reference_value") is None:
        duration_ms = (time.time() - card_start_time) * 1000
        logger.info(
            f"[{task_id}] CARD PATCH COMPLETE - Component: {component_id} - "
            f"Duration: {duration_ms:.2f}ms (reference value not ready)"
        )
        return "...", [], {}

    return None


def _has_active_filter_values(metadata_list: list[dict[str, Any]] | None) -> bool:
    """
    Check if any filters have active (non-empty) values.

    Args:
        metadata_list: List of filter component metadata

    Returns:
        True if at least one filter has a non-empty value
    """
    if not metadata_list:
        return False

    for component in metadata_list:
        value = component.get("value")
        if value is not None and value != [] and value != "" and value is not False:
            return True
    return False
