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

import dash
from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.card_component.utils import agg_functions
from depictio.dash.utils import get_columns_from_data_collection, get_component_data


def register_core_callbacks(app):
    """Register core rendering callbacks for card component."""

    # Clientside callback to show loading overlay instantly when filters change
    app.clientside_callback(
        """
        function(filters_data, existing_visible) {
            // Show overlay when filters change (cards are updating)
            // With dash.ALL, we need to return an array - one value per matched component
            console.log('[CARD LOADING] Clientside callback fired, filters_data:', filters_data);
            console.log('[CARD LOADING] Existing visible states:', existing_visible);

            if (!existing_visible || !Array.isArray(existing_visible)) {
                return [];
            }

            const shouldShow = filters_data ? true : false;
            console.log('[CARD LOADING] Setting all overlays to:', shouldShow);

            // Return array with same length as matched components
            return existing_visible.map(() => shouldShow);
        }
        """,
        Output(
            {"type": "card-loading-overlay", "index": dash.ALL}, "visible", allow_duplicate=True
        ),
        Input("interactive-values-store", "data"),
        State({"type": "card-loading-overlay", "index": dash.ALL}, "visible"),
        prevent_initial_call="initial_duplicate",
    )

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
    def reset_aggregation_value(column_name):
        return None

    @app.callback(
        Output({"type": "card-value", "index": MATCH}, "children"),
        Output({"type": "card-metadata", "index": MATCH}, "data"),
        Input({"type": "card-trigger", "index": MATCH}, "data"),
        Input(
            "project-metadata-store", "data"
        ),  # ✅ MIGRATED: Read directly from project metadata cache
        State({"type": "card-metadata", "index": MATCH}, "data"),
        State("dashboard-init-data", "data"),  # REFACTORING: Access centralized column_specs
        State("local-store", "data"),  # SECURITY: Access token from centralized store
        prevent_initial_call=False,
    )
    def render_card_value_background(
        trigger_data, project_metadata, existing_metadata, dashboard_init_data, local_data
    ):
        """
        PATTERN-MATCHING: Render callback for initial card value computation.

        TWO-STAGE RENDERING OPTIMIZATION:
        - Stage 1: Renders immediately with trigger_data (before project_metadata available)
        - Stage 2: Re-renders when project-metadata-store arrives (contains delta_locations)

        This eliminates race condition where cards rendered before delta locations fetched.
        Session storage ensures delta locations persist across refreshes for instant optimization.

        PERFORMANCE OPTIMIZATION:
        - Extracts delta_locations from project-metadata-store (no separate store needed)
        - Project metadata includes full delta_locations via MongoDB $lookup join
        - For 9 cards: all share same project metadata cache

        Args:
            trigger_data: Data from card-trigger store containing all necessary params
            project_metadata: Full project metadata cache (includes delta_locations from MongoDB join)
            existing_metadata: Existing metadata from previous render (for idempotency check)
            dashboard_init_data: Dashboard initialization data with column_specs
            local_data: User authentication data from local-store

        Returns:
            tuple: (formatted_value, metadata_dict)
        """
        from bson import ObjectId
        from dash import no_update

        from depictio.api.v1.deltatables_utils import load_deltatable_lite

        logger.info(f"🔄 CARD RENDER: Starting value computation for trigger: {trigger_data}")
        # DEFENSIVE CHECK 1: Skip if trigger_data not ready (progressive loading race condition)
        # During progressive loading, the callback might fire before React fully commits the component tree
        # This prevents attempting to update components that don't exist yet in the DOM
        if not trigger_data or not isinstance(trigger_data, dict):
            logger.warning(
                "⚠️ CARD RENDER: Trigger data not ready, deferring render "
                "(Progressive loading race condition detected)"
            )
            return no_update, no_update

        # ✅ CACHE OPTIMIZATION: Extract delta_locations from project-metadata-store
        delta_locations = None
        if project_metadata:
            delta_locations = {}
            project_data = project_metadata.get("project", {})
            for wf in project_data.get("workflows", []):
                for dc in wf.get("data_collections", []):
                    dc_id = str(dc.get("_id"))
                    if dc.get("delta_location"):
                        delta_locations[dc_id] = dc["delta_location"]

        # DEFENSIVE CHECK 2: Skip if already initialized (prevents spurious re-renders during Patch operations)
        # EXCEPTION: Allow Stage 2 re-render when delta_locations becomes available
        # This enables two-stage optimization: Stage 1 (API calls) → Stage 2 (cached data)
        if existing_metadata and existing_metadata.get("reference_value") is not None:
            # Check if this is a Stage 2 opportunity (delta_locations just arrived)
            had_delta_locations = existing_metadata.get("delta_locations_available", False)
            has_delta_locations_now = delta_locations is not None and len(delta_locations) > 0

            if has_delta_locations_now and not had_delta_locations:
                # Stage 2: delta_locations just became available, allow re-render for optimization
                logger.info(
                    "🚀 CARD RENDER STAGE 2: delta_locations now available, re-rendering with optimization"
                )
                # Continue to re-render with delta_locations
            else:
                # Already fully initialized or spurious update, skip
                logger.debug(
                    "✅ CARD RENDER: Already initialized, skipping re-render "
                    "(Patch operation or spurious Store update detected)"
                )
                return no_update, no_update

        if not trigger_data:
            logger.warning("No trigger data provided")
            return "...", {}

        # Extract parameters from trigger store
        wf_id = trigger_data.get("wf_id")
        dc_id = trigger_data.get("dc_id")
        column_name = trigger_data.get("column_name")
        aggregation = trigger_data.get("aggregation")

        # SECURITY: Extract access_token from local-store (centralized, not per-component)
        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access_token available in local-store")
            return "Auth Error", {}

        # REFACTORING: Extract cols_json from dashboard-init-data (centralized store)
        cols_json = {}
        if dashboard_init_data and "column_specs" in dashboard_init_data:
            cols_json = dashboard_init_data.get("column_specs", {}).get(str(dc_id), {})
            logger.debug(f"✅ Extracted cols_json from dashboard-init-data for dc_id={dc_id}")
        else:
            logger.debug("⚠️  dashboard-init-data not available, cols_json will be empty")

        # TWO-STAGE OPTIMIZATION: Use delta_locations when available
        # Stage 1: delta_locations is None → use API calls (slower)
        # Stage 2: delta_locations populated → use cached data (faster)
        # Pass delta_locations directly to load_deltatable_lite
        init_data = None
        if delta_locations:
            init_data = delta_locations  # Pass delta_locations dict to load_deltatable_lite
            logger.info(
                f"📡 CARD RENDER STAGE 2: Using delta_locations with {len(delta_locations)} locations"
            )
        else:
            logger.debug("🔄 CARD RENDER STAGE 1: No delta_locations yet, using API calls")

        # Validate required parameters
        if not all([wf_id, dc_id, column_name, aggregation]):
            logger.error(
                f"Missing required parameters - wf_id: {wf_id}, dc_id: {dc_id}, "
                f"column_name: {column_name}, aggregation: {aggregation}"
            )
            return "Error", {"error": "Missing parameters"}

        try:
            # Load full dataset
            logger.debug(f"Loading dataset for {wf_id}:{dc_id}")
            if isinstance(dc_id, str) and "--" in dc_id:
                # Joined data collection - keep as string
                data = load_deltatable_lite(
                    workflow_id=ObjectId(wf_id),
                    data_collection_id=dc_id,
                    TOKEN=access_token,
                    init_data=init_data,  # OPTIMIZATION: Use init_data from dashboard
                )
            else:
                # Regular data collection - convert to ObjectId
                data = load_deltatable_lite(
                    workflow_id=ObjectId(wf_id),
                    data_collection_id=ObjectId(dc_id),
                    TOKEN=access_token,
                    init_data=init_data,  # OPTIMIZATION: Use init_data from dashboard
                )

            logger.debug(f"Loaded data shape: {data.shape}")

            # Compute aggregation value
            from depictio.dash.modules.card_component.utils import compute_value

            value = compute_value(data, column_name, aggregation)
            logger.debug(f"Computed value: {value}")

            # Format value
            try:
                if value is not None:
                    formatted_value = str(round(float(value), 4))
                else:
                    formatted_value = "N/A"
            except (ValueError, TypeError):
                formatted_value = "Error"

            # Store metadata for patching callback
            metadata = {
                "reference_value": value,
                "column_name": column_name,
                "aggregation": aggregation,
                "wf_id": wf_id,
                "dc_id": dc_id,
                "cols_json": cols_json,
                "delta_locations_available": delta_locations
                is not None,  # Track if delta_locations was available
            }

            logger.info(f"✅ CARD RENDER: Value computed successfully: {formatted_value}")
            return formatted_value, metadata

        except Exception as e:
            logger.error(f"❌ CARD RENDER: Error computing value: {e}", exc_info=True)
            return "Error", {"error": str(e)}

    # PATTERN-MATCHING: Patching callback for filter-based updates
    @app.callback(
        Output({"type": "card-value", "index": MATCH}, "children", allow_duplicate=True),
        Output({"type": "card-comparison", "index": MATCH}, "children", allow_duplicate=True),
        Output({"type": "card-loading-overlay", "index": MATCH}, "visible"),
        Input("interactive-values-store", "data"),
        State({"type": "card-metadata", "index": MATCH}, "data"),
        State({"type": "card-trigger", "index": MATCH}, "data"),
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "id"),
        State("dashboard-init-data", "data"),  # REFACTORING: Access centralized dc_configs
        State("local-store", "data"),  # SECURITY: Access token from centralized store
        prevent_initial_call=True,
        background=True,
    )
    def patch_card_with_filters(
        filters_data,
        metadata,
        trigger_data,
        interactive_metadata_list,
        interactive_metadata_ids,
        dashboard_init_data,
        local_data,
    ):
        """
        PATTERN-MATCHING: Patching callback for filter-based card updates.

        Triggers when interactive filters change. Applies filters to data,
        computes new value, and creates comparison with reference value.

        Args:
            filters_data: Interactive filter values (lightweight: index + value only)
            metadata: Card metadata with reference_value
            trigger_data: Original trigger data with card config
            interactive_metadata_list: Full metadata from all interactive components
            interactive_metadata_ids: IDs of all interactive component metadata stores

        Returns:
            tuple: (formatted_value, comparison_components)
        """
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import load_deltatable_lite
        from depictio.dash.modules.card_component.utils import (
            compute_value,
            get_adaptive_trend_colors,
        )

        # DEFENSIVE CHECK: Handle dashboards with no interactive components
        # When no interactive components exist, dash.ALL resolves to empty list
        if not interactive_metadata_list or not interactive_metadata_ids:
            logger.debug(
                "No interactive components - skipping card filtering (no filters to apply)"
            )
            raise dash.exceptions.PreventUpdate

        # RECONSTRUCT FULL METADATA: Combine lightweight store (index + value) with full metadata
        # Create index → metadata mapping
        metadata_by_index = {}
        if interactive_metadata_list and interactive_metadata_ids:
            for i, meta_id in enumerate(interactive_metadata_ids):
                if i < len(interactive_metadata_list):
                    index = meta_id["index"]
                    metadata_by_index[index] = interactive_metadata_list[i]

        # Enrich lightweight store data with full metadata
        lightweight_components = (
            filters_data.get("interactive_components_values", []) if filters_data else []
        )

        enriched_components = []
        for component in lightweight_components:
            index = component.get("index")
            value = component.get("value")
            full_metadata = metadata_by_index.get(index, {})

            if full_metadata:
                enriched_components.append(
                    {
                        "index": index,
                        "value": value,
                        "metadata": full_metadata,  # Full metadata from interactive-stored-metadata
                    }
                )

        # Replace filters_data with enriched version for backward compatibility
        filters_data = {"interactive_components_values": enriched_components}

        # Check if metadata and trigger_data are properly populated
        if metadata is None or trigger_data is None:
            return "...", [], False

        # Check if metadata has been populated by render_card_value_background
        reference_value = metadata.get("reference_value")
        if reference_value is None:
            return "...", [], False

        # Extract parameters
        wf_id = trigger_data.get("wf_id")
        dc_id = trigger_data.get("dc_id")
        column_name = trigger_data.get("column_name")
        aggregation = trigger_data.get("aggregation")
        reference_value = metadata.get("reference_value")

        # SECURITY: Extract access_token from local-store (centralized, not per-component)
        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access_token available in local-store")
            return "Auth Error", [], False

        # Skip patching for dummy/random cards (no data source)
        if not all([wf_id, dc_id, column_name, aggregation]):
            # Return current value formatted consistently with initial render
            current_value = metadata.get("reference_value")
            if current_value is not None:
                try:
                    formatted_value = str(round(float(current_value), 4))
                except (ValueError, TypeError):
                    formatted_value = str(current_value)
            else:
                formatted_value = "N/A"

            return formatted_value, [], False

        try:
            # Extract interactive components from filters_data
            # filters_data format: {"interactive_components_values": [component1, component2, ...]}
            metadata_list = (
                filters_data.get("interactive_components_values") if filters_data else None
            )

            # MULTI-DC SUPPORT: Group filters by DC to detect cross-DC filtering scenarios
            filters_by_dc = {}
            if metadata_list:
                for component in metadata_list:
                    component_dc = str(component.get("metadata", {}).get("dc_id"))
                    if component_dc not in filters_by_dc:
                        filters_by_dc[component_dc] = []
                    filters_by_dc[component_dc].append(component)

            # CRITICAL FIX: Filter out non-table DCs (MultiQC, JBrowse2) from filters_by_dc
            # REFACTORING: Extract dc_configs from dashboard-init-data (centralized store)
            dc_configs_map = {}
            if dashboard_init_data and "dc_configs" in dashboard_init_data:
                dc_configs_map = dashboard_init_data.get("dc_configs", {})

            filters_by_dc_table_only = {}
            for dc_key, dc_filters in filters_by_dc.items():
                if dc_filters:  # Has filters, check DC type
                    # Get dc_config from centralized dashboard-init-data
                    component_dc_config = dc_configs_map.get(str(dc_key), {})
                    dc_type = component_dc_config.get("type", "table")
                    if dc_type == "table":
                        filters_by_dc_table_only[dc_key] = dc_filters
            filters_by_dc = filters_by_dc_table_only

            # Check if card's DC is MultiQC/JBrowse2 - if so, skip filtering entirely
            # REFACTORING: Extract dc_config from dashboard-init-data (centralized store)
            dc_config = {}
            if dashboard_init_data and "dc_configs" in dashboard_init_data:
                dc_config = dashboard_init_data.get("dc_configs", {}).get(str(dc_id), {})

            card_dc_type = dc_config.get("type", "table")
            if card_dc_type in ["multiqc", "jbrowse2"]:
                # Return reference value with no comparison
                if reference_value is not None:
                    try:
                        formatted_value = str(round(float(reference_value), 4))
                    except (ValueError, TypeError):
                        formatted_value = str(reference_value)
                else:
                    formatted_value = "N/A"
                return formatted_value, [], False

            # Determine if filters have active (non-empty) values
            has_active_filters = False
            if metadata_list:
                for component in metadata_list:
                    value = component.get("value")
                    if value is not None and value != [] and value != "" and value is not False:
                        has_active_filters = True
                        break

            if has_active_filters:
                logger.info("🔍 Active filters detected - loading filtered data")
            else:
                logger.info("🔄 No active filters - loading ALL unfiltered data")

            # AUTO-DETECT: Determine if we need to join DCs
            # Two scenarios:
            # 1. Same-DC: Card's DC has filters → Apply filters directly
            # 2. Joined-DC: Card's DC is joined with DC(s) that have filters → Join needed
            card_dc_str = str(dc_id)
            has_filters_for_card_dc = card_dc_str in filters_by_dc

            # Get join config to check DC relationships
            join_config = dc_config.get("join", {})

            # Determine if we need to perform a join
            needs_join = False
            if not has_filters_for_card_dc and len(filters_by_dc) > 0:
                # Filters are on different DC(s) - need to join with card DC
                needs_join = True
                logger.info("🔍 Filters on different DC(s), join required")

            logger.info(f"🔍 Card DC: {card_dc_str}")
            logger.info(f"🔍 Has filters for card DC: {has_filters_for_card_dc}")
            logger.info(f"🔍 Needs join: {needs_join}")
            logger.info(f"🔍 Filters on {len(filters_by_dc)} DC(s)")

            from depictio.api.v1.deltatables_utils import get_join_tables, load_deltatable_lite

            # If no explicit join config but join is needed, query workflow join tables
            if needs_join and (not join_config or not join_config.get("on_columns")):
                logger.info("🔍 No explicit join config in DC - querying workflow join tables")
                workflow_join_tables = get_join_tables(wf_id, access_token)

                if workflow_join_tables and wf_id in workflow_join_tables:
                    wf_joins = workflow_join_tables[wf_id]
                    logger.debug(f"🔍 Workflow join tables: {list(wf_joins.keys())}")

                    # Search for join between card DC and any filter DC
                    # Join keys are formatted as "dc1--dc2"
                    for filter_dc in filters_by_dc.keys():
                        # Try both directions: card--filter and filter--card
                        join_key_1 = f"{card_dc_str}--{filter_dc}"
                        join_key_2 = f"{filter_dc}--{card_dc_str}"

                        if join_key_1 in wf_joins:
                            join_config = wf_joins[join_key_1]
                            logger.info(f"✅ Found join config in workflow tables: {join_key_1}")
                            logger.debug(f"   Join config: {join_config}")
                            break
                        elif join_key_2 in wf_joins:
                            join_config = wf_joins[join_key_2]
                            logger.info(f"✅ Found join config in workflow tables: {join_key_2}")
                            logger.debug(f"   Join config: {join_config}")
                            break

                    if not join_config or not join_config.get("on_columns"):
                        logger.warning(
                            "⚠️ No join config found in workflow tables for card DC and filter DCs"
                        )
                else:
                    logger.warning(f"⚠️ No workflow join tables found for workflow {wf_id}")

            # Determine the filtering path
            # JOINED-DC: Filters on different DCs + join config available
            # SAME-DC: Filters on card DC only, or multiple DCs but no join config
            use_joined_path = needs_join and join_config and join_config.get("on_columns")

            # If filters on multiple DCs but no join config, fall back to SAME-DC
            if len(filters_by_dc) > 1 and not use_joined_path:
                logger.warning(
                    f"⚠️ Filters on {len(filters_by_dc)} DCs but no join config - "
                    f"falling back to SAME-DC filtering (card DC only)"
                )
                # Keep only card DC filters
                if card_dc_str in filters_by_dc:
                    filters_by_dc = {card_dc_str: filters_by_dc[card_dc_str]}
                else:
                    filters_by_dc = {}

            if use_joined_path:
                # JOINED-DC PATH: Manual loading + merge_multiple_dataframes
                logger.info(
                    f"🔗 JOINED-DC FILTERING: Loading and joining DCs "
                    f"(card DC + {len(filters_by_dc)} filter DC(s))"
                )

                from depictio.api.v1.deltatables_utils import merge_multiple_dataframes

                # Include card's DC in the join if it's not already in filters_by_dc
                if card_dc_str not in filters_by_dc:
                    logger.info(f"📂 Adding card DC {card_dc_str} to join (no filters)")
                    filters_by_dc[card_dc_str] = []

                # Extract DC metatypes from component metadata (already cached in Store)
                dc_metatypes = {}
                for dc_key, dc_filters in filters_by_dc.items():
                    if dc_filters:
                        component_dc_config = dc_filters[0].get("metadata", {}).get("dc_config", {})
                        metatype = component_dc_config.get("metatype")
                        if metatype:
                            dc_metatypes[dc_key] = metatype
                            logger.debug(
                                f"📋 DC {dc_key} metatype: {metatype} (from cached metadata)"
                            )

                # If card DC not in dc_metatypes, get from trigger_data
                if card_dc_str not in dc_metatypes:
                    card_metatype = dc_config.get("metatype")
                    if card_metatype:
                        dc_metatypes[card_dc_str] = card_metatype
                        logger.debug(f"📋 Card DC {card_dc_str} metatype: {card_metatype}")

                # Load each DC with all columns (rely on cache for performance)
                dataframes = {}
                for dc_key, dc_filters in filters_by_dc.items():
                    if has_active_filters:
                        # Filter out components with empty values
                        active_filters = [
                            c for c in dc_filters if c.get("value") not in [None, [], "", False]
                        ]
                        logger.info(
                            f"📂 Loading DC {dc_key} with {len(active_filters)} active filters"
                        )
                        metadata_to_pass = active_filters
                    else:
                        # Clearing filters - load ALL unfiltered data
                        logger.info(f"📂 Loading DC {dc_key} with NO filters (clearing)")
                        metadata_to_pass = []

                    dc_df = load_deltatable_lite(
                        ObjectId(wf_id),
                        ObjectId(dc_key),
                        metadata=metadata_to_pass,
                        TOKEN=access_token,
                        select_columns=None,  # Load all columns, rely on cache
                    )
                    dataframes[dc_key] = dc_df
                    logger.info(f"   Loaded {dc_df.height:,} rows × {dc_df.width} columns")

                # Build join instructions for merge_multiple_dataframes
                dc_ids = sorted(filters_by_dc.keys())
                join_instructions = [
                    {
                        "left": dc_ids[0],
                        "right": dc_ids[1],
                        "how": join_config.get("how", "inner"),
                        "on": join_config.get("on_columns", []),
                    }
                ]

                logger.info(f"🔗 Joining DCs: {join_instructions}")
                logger.info(f"📋 DC metatypes for join: {dc_metatypes}")

                # Merge DataFrames with table type awareness
                data = merge_multiple_dataframes(
                    dataframes=dataframes,
                    join_instructions=join_instructions,
                    dc_metatypes=dc_metatypes,
                )

                logger.info(f"📊 Joined result: {data.height:,} rows × {data.width} columns")

            else:
                # SAME-DC PATH: Card's DC has filters, apply them directly
                relevant_filters = filters_by_dc.get(card_dc_str, [])

                if has_active_filters:
                    # Filter out components with empty values
                    active_filters = [
                        c for c in relevant_filters if c.get("value") not in [None, [], "", False]
                    ]
                    logger.info(
                        f"📄 SAME-DC filtering - applying {len(active_filters)} active filters to card DC"
                    )
                    metadata_to_pass = active_filters
                else:
                    # Clearing filters - load ALL unfiltered data
                    logger.info("📄 SAME-DC clearing filters - loading ALL unfiltered data")
                    metadata_to_pass = []

                logger.info(f"📂 Loading data: {wf_id}:{dc_id} ({len(metadata_to_pass)} filters)")

                data = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id),
                    metadata=metadata_to_pass,
                    TOKEN=access_token,
                )

                logger.info(f"📊 Loaded {data.height:,} rows × {data.width} columns")

            logger.debug("Loaded filtered data")

            # Compute new value on filtered data
            current_value = compute_value(data, column_name, aggregation)
            logger.debug(f"Computed filtered value: {current_value}")

            # Format current value
            try:
                if current_value is not None:
                    formatted_value = str(round(float(current_value), 4))
                    current_val = float(current_value)
                else:
                    formatted_value = "N/A"
                    current_val = None
            except (ValueError, TypeError):
                formatted_value = "Error"
                current_val = None

            # Get adaptive trend colors based on card background
            # Convert empty string to None for proper handling
            background_color = trigger_data.get("background_color") or None
            trend_colors = get_adaptive_trend_colors(background_color)
            logger.debug(
                f"Using adaptive trend colors for background '{background_color}': {trend_colors}"
            )

            # Create comparison components
            comparison_components = []
            if reference_value is not None and current_val is not None:
                try:
                    import dash_mantine_components as dmc
                    from dash_iconify import DashIconify

                    ref_val = float(reference_value)

                    # Calculate percentage change
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

                    # Build comparison UI
                    comparison_components = [
                        DashIconify(icon=comparison_icon, width=14, color=comparison_color),
                        dmc.Text(
                            comparison_text,
                            size="xs",
                            c=comparison_color,
                            fw="normal",
                            style={"margin": "0"},
                        ),
                    ]
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error creating comparison: {e}")

            logger.info(f"✅ CARD PATCH: Value updated successfully: {formatted_value}")
            return formatted_value, comparison_components, False

        except Exception as e:
            logger.error(f"❌ CARD PATCH: Error applying filters: {e}", exc_info=True)
            return "Error", [], False
