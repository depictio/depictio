"""
Table Component Core Callbacks

View mode callbacks for table component:
- Theme switching for AG Grid
- Infinite scroll with filtering, sorting, and interactive component integration
"""

import polars as pl
from dash import ALL, MATCH, Input, Output, State, ctx, no_update

from depictio.api.v1.configs.logging_init import logger

# AG Grid filter operators mapping to Polars operations
OPERATORS = {
    "greaterThanOrEqual": "ge",
    "lessThanOrEqual": "le",
    "lessThan": "lt",
    "greaterThan": "gt",
    "notEqual": "ne",
    "equals": "eq",
}


def apply_ag_grid_filter(df: pl.DataFrame, filter_model: dict, col: str) -> pl.DataFrame:
    """
    Apply AG Grid filter to a Polars DataFrame.
    Based on dash-ag-grid documentation examples.
    """
    filter_type = filter_model.get("filterType")

    if filter_type == "text":
        filter_value = filter_model.get("filter", "")
        filter_operator = filter_model.get("type", "contains")

        if filter_operator == "contains":
            df = df.filter(pl.col(col).cast(pl.Utf8).str.contains(filter_value, literal=False))
        elif filter_operator == "notContains":
            df = df.filter(~pl.col(col).cast(pl.Utf8).str.contains(filter_value, literal=False))
        elif filter_operator == "equals":
            df = df.filter(pl.col(col) == filter_value)
        elif filter_operator == "notEqual":
            df = df.filter(pl.col(col) != filter_value)
        elif filter_operator == "startsWith":
            df = df.filter(pl.col(col).cast(pl.Utf8).str.starts_with(filter_value))
        elif filter_operator == "endsWith":
            df = df.filter(pl.col(col).cast(pl.Utf8).str.ends_with(filter_value))

    elif filter_type == "number":
        filter_value = filter_model.get("filter")
        filter_operator = filter_model.get("type", "equals")

        if filter_operator in OPERATORS:
            df = df.filter(getattr(pl.col(col), OPERATORS[filter_operator])(filter_value))

    elif filter_type == "date":
        date_from = filter_model.get("dateFrom")
        date_to = filter_model.get("dateTo")
        filter_operator = filter_model.get("type", "equals")

        if filter_operator == "equals" and date_from:
            df = df.filter(pl.col(col) == date_from)
        elif filter_operator == "notEqual" and date_from:
            df = df.filter(pl.col(col) != date_from)
        elif filter_operator == "greaterThan" and date_from:
            df = df.filter(pl.col(col) > date_from)
        elif filter_operator == "greaterThanOrEqual" and date_from:
            df = df.filter(pl.col(col) >= date_from)
        elif filter_operator == "lessThan" and date_from:
            df = df.filter(pl.col(col) < date_from)
        elif filter_operator == "lessThanOrEqual" and date_from:
            df = df.filter(pl.col(col) <= date_from)
        elif filter_operator == "inRange" and date_from and date_to:
            df = df.filter((pl.col(col) >= date_from) & (pl.col(col) <= date_to))

    elif filter_type == "set":
        # Set filter - include only specific values
        values = filter_model.get("values", [])
        if values:
            df = df.filter(pl.col(col).is_in(values))

    return df


def apply_ag_grid_sorting(df: pl.DataFrame, sort_model: list) -> pl.DataFrame:
    """
    Apply AG Grid sorting to a Polars DataFrame.
    """
    if not sort_model:
        return df

    # Build list of column/descending pairs for Polars sort
    sort_cols = []
    sort_descending = []

    for sort in sort_model:
        col_id = sort["colId"]
        sort_order = sort["sort"]  # 'asc' or 'desc'

        sort_cols.append(col_id)
        sort_descending.append(sort_order == "desc")

    return df.sort(sort_cols, descending=sort_descending)


def register_core_callbacks(app):
    """Register core view mode callbacks for table component."""
    from depictio.api.v1.configs.logging_init import logger as core_logger

    core_logger.info("🔧 Registering table component core callbacks (theme + infinite scroll)")

    @app.callback(
        Output({"type": "table-aggrid", "index": MATCH}, "className"),
        Input("theme-store", "data"),
        prevent_initial_call=False,
    )
    def update_table_ag_grid_theme(theme_data):
        """Update AG Grid theme class based on current theme."""
        theme = theme_data or "light"
        if theme == "dark":
            return "ag-theme-alpine-dark"
        else:
            return "ag-theme-alpine"

    @app.callback(
        Output({"type": "table-aggrid", "index": MATCH}, "getRowsResponse"),
        [
            Input({"type": "table-aggrid", "index": MATCH}, "getRowsRequest"),
            Input("interactive-values-store", "data"),
        ],
        [
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
            State("local-store", "data"),
            State("url", "pathname"),
            State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
            State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        ],
        prevent_initial_call=False,  # Allow callback to fire on mount for initial data load
    )
    def infinite_scroll_component(
        request,
        interactive_values,
        stored_metadata,
        local_store,
        pathname,
        interactive_metadata_list,
        interactive_metadata_ids,
    ):
        """
        INFINITE SCROLL CALLBACK WITH INTERACTIVE COMPONENT SUPPORT

        This callback handles ALL tables using infinite row model and includes:
        - Interactive component filtering via iterative_join
        - AG Grid server-side filtering and sorting
        - Efficient pagination for all dataset sizes
        - Cache invalidation when interactive values change
        """
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import (
            iterative_join,
            load_deltatable_lite,
            return_joins_dict,
        )

        logger.info("🚀 TABLE INFINITE SCROLL CALLBACK FIRED!")

        # CACHE INVALIDATION: Detect if triggered by interactive component changes
        triggered_by_interactive = ctx.triggered and any(
            "interactive-values-store" in str(trigger["prop_id"]) for trigger in ctx.triggered
        )

        logger.debug(f"🔄 Infinite scroll callback triggered - {ctx.triggered}")

        # Detailed analysis of interactive values
        if interactive_values and "interactive_components_values" in interactive_values:
            components_count = len(interactive_values["interactive_components_values"])
            logger.debug(f"🎯 Table: {components_count} interactive components detected")
        else:
            logger.debug("🎯 Table: No interactive values")

        # LOGGING: Track infinite scroll requests and trigger source
        logger.debug(f"📊 Request: {request}")
        logger.debug(f"🎯 Triggered by: {ctx.triggered_id if ctx.triggered else 'Unknown'}")

        # Validate inputs
        if not local_store or not stored_metadata:
            logger.warning(
                "❌ Missing required data for infinite scroll - local_store or stored_metadata"
            )
            return no_update

        # Handle missing request (initial load or interactive changes)
        if request is None:
            if triggered_by_interactive:
                # Interactive component changed - always process immediately
                logger.info("🔄 Interactive component changed - processing data immediately")
            else:
                # Initial load - AG Grid hasn't sent first request yet
                logger.info("🆕 INITIAL LOAD: Creating synthetic request for first page")

            # Create a synthetic request for the first page
            request = {
                "startRow": 0,
                "endRow": 100,  # Standard first page size
                "filterModel": {},
                "sortModel": [],
            }
            logger.info("✅ Created synthetic request to load initial data")

        # Extract authentication token
        TOKEN = local_store["access_token"]

        # Extract table metadata
        workflow_id = stored_metadata["wf_id"]
        data_collection_id = stored_metadata["dc_id"]
        table_index = stored_metadata["index"]

        # LOGGING: Track data request parameters
        start_row = request.get("startRow", 0)
        end_row = request.get("endRow", 100)
        requested_rows = end_row - start_row
        filter_model = request.get("filterModel", {})
        sort_model = request.get("sortModel", [])

        logger.info(
            f"📈 Table {table_index}: Loading rows {start_row}-{end_row} ({requested_rows} rows)"
        )
        logger.info(
            f"🔍 Active filters: {len(filter_model)} filter(s) - {list(filter_model.keys()) if filter_model else 'none'}"
        )
        logger.info(
            f"🔤 Active sorts: {len(sort_model)} sort(s) - {[(s['colId'], s['sort']) for s in sort_model] if sort_model else 'none'}"
        )

        # CRITICAL: Enrich lightweight store data with full metadata from States
        # Pattern from card callback - fixes missing metadata issue

        # Step 1: Build metadata mapping (index → full metadata)
        metadata_by_index = {}
        if interactive_metadata_list and interactive_metadata_ids:
            for i, meta_id in enumerate(interactive_metadata_ids):
                if i < len(interactive_metadata_list):
                    index = meta_id["index"]
                    metadata_by_index[index] = interactive_metadata_list[i]
                    logger.debug(f"Mapped metadata for interactive component {index}")

        # Step 2: Extract lightweight components from store
        lightweight_components = (
            interactive_values.get("interactive_components_values", [])
            if interactive_values
            else []
        )

        logger.debug(
            f"Table {table_index}: Enrichment starting - {len(lightweight_components)} lightweight components, "
            f"{len(metadata_by_index)} metadata entries available"
        )

        # Step 3: Enrich lightweight data with full metadata
        interactive_components_dict = {}

        for component in lightweight_components:
            index = component.get("index")
            value = component.get("value")

            if not index:
                continue

            # Get full metadata from mapping
            full_metadata = metadata_by_index.get(index)

            if full_metadata:
                # Build enriched component data
                enriched_component = {
                    "index": index,
                    "value": value,
                    "component_type": "interactive",  # Type is known
                    "metadata": full_metadata,  # Full metadata added
                }

                interactive_components_dict[index] = enriched_component

                logger.debug(
                    f"✅ Enriched component {index}: DC={full_metadata.get('dc_id')}, "
                    f"Column={full_metadata.get('column_name')}, "
                    f"Type={full_metadata.get('interactive_component_type')}"
                )
            else:
                logger.warning(f"⚠️ Component {index} has value but no metadata - skipping")

        logger.info(
            f"📊 Table {table_index}: Enrichment complete - {len(interactive_components_dict)} components enriched"
        )

        # CRITICAL FIX: Prepare metadata for iterative join INCLUDING all interactive components
        # When interactive components exist, we need to include their metadata for proper joining
        stored_metadata_for_join = []

        # Always include the table metadata
        table_metadata = dict(stored_metadata)  # Convert to regular dict
        table_metadata["component_type"] = "table"  # Ensure component type is set
        stored_metadata_for_join.append(table_metadata)

        # CRITICAL: Include metadata from all interactive components for join calculation
        if interactive_components_dict:
            for component_index, component_data in interactive_components_dict.items():
                if component_data.get("metadata"):
                    interactive_meta = dict(component_data["metadata"])
                    interactive_meta["component_type"] = "interactive"
                    stored_metadata_for_join.append(interactive_meta)
                    logger.info(
                        f"🔗 Added interactive metadata for join: dc_id={interactive_meta.get('dc_id')}"
                    )

        logger.info(
            f"🔗 Total metadata for join calculation: {len(stored_metadata_for_join)} components"
        )
        logger.info(
            f"🔗 Data collections involved: {[meta.get('dc_id') for meta in stored_metadata_for_join]}"
        )

        logger.info(f"🔗 Table {table_index}: Preparing iterative join for workflow {workflow_id}")
        logger.debug(f"📋 Interactive components dict: {interactive_components_dict}")
        logger.debug(f"📋 Table metadata: {table_metadata}")
        logger.debug(f"📋 Workflow ID type: {type(workflow_id)} -> {workflow_id}")
        logger.debug(
            f"📋 Table wf_id type: {type(table_metadata.get('wf_id'))} -> {table_metadata.get('wf_id')}"
        )

        # # SIMULATE SLOW LOADING: Add delay to demonstrate infinite scrolling with pagination
        # # Following documentation example pattern
        # import time
        # time.sleep(1.0)  # Increased delay to better demonstrate spinner loading behavior

        try:
            # ENHANCED INTERACTIVE FILTERING: Check DC compatibility before joining
            if interactive_components_dict:
                logger.info(
                    f"🔗 INFINITE SCROLL + INTERACTIVE: Processing {len(interactive_components_dict)} interactive components"
                )
                logger.info(
                    f"🎯 Interactive components: {[(k, v.get('value')) for k, v in interactive_components_dict.items()]}"
                )

                # CHECK DC COMPATIBILITY: Determine if interactive components target the same DC as the table
                table_dc_id = data_collection_id

                # Handle joined data collection IDs (format: "dc1--dc2")
                if "--" in str(table_dc_id):
                    # Table is showing joined data - extract individual DC IDs
                    table_dc_ids = set(table_dc_id.split("--"))
                    logger.info(f"📊 Table is JOINED data: {table_dc_id} → {table_dc_ids}")
                else:
                    # Single DC
                    table_dc_ids = {table_dc_id}
                    logger.info(f"📊 Table DC: {table_dc_id}")

                # Collect all interactive component DC IDs
                interactive_dc_ids = set()
                for comp_data in interactive_components_dict.values():
                    comp_dc_id = comp_data.get("metadata", {}).get("dc_id")
                    if comp_dc_id:
                        interactive_dc_ids.add(comp_dc_id)

                logger.info(
                    f"🔍 Table {table_index}: DC Extraction Complete\n"
                    f"   Interactive DCs: {interactive_dc_ids}\n"
                    f"   Components Processed: {len(interactive_components_dict)}"
                )

                # CRITICAL FIX: Get join configuration BEFORE compatibility check
                # This allows us to detect if joins exist between table and interactive DCs
                try:
                    logger.debug(
                        f"🔗 Calling return_joins_dict with wf={workflow_id}, metadata={stored_metadata_for_join}"
                    )
                    joins_dict = return_joins_dict(workflow_id, stored_metadata_for_join, TOKEN)
                    logger.info(f"🔗 Found {len(joins_dict)} join group(s) in workflow")
                    logger.debug(f"🔗 Join keys: {list(joins_dict.keys())}")
                except Exception as joins_error:
                    logger.error(f"❌ Error getting joins dict: {str(joins_error)}")
                    logger.error(f"❌ Error traceback: {joins_error.__class__.__name__}")
                    import traceback

                    logger.error(f"❌ Full traceback: {traceback.format_exc()}")
                    logger.error("🔧 Falling back to empty joins dict")
                    joins_dict = {}

                # CRITICAL FIX: Check if joins exist between table and interactive DCs
                has_join_between_dcs = False
                if joins_dict:
                    logger.debug(
                        f"🔍 Checking for joins between table_dcs={table_dc_ids} and interactive_dcs={interactive_dc_ids}"
                    )
                    for join_key_tuple in joins_dict.keys():
                        # join_key_tuple is like ('dc1', 'dc2')
                        join_dc_set = set(join_key_tuple)

                        # Check if this join connects table DC(s) with interactive DC(s)
                        # A join is relevant if it links at least one table DC with at least one interactive DC
                        if table_dc_ids & join_dc_set and interactive_dc_ids & join_dc_set:
                            has_join_between_dcs = True
                            logger.info(
                                f"✅ JOIN DETECTED: Join exists between table and interactive DCs via {join_key_tuple}"
                            )
                            break

                    if not has_join_between_dcs:
                        logger.debug("📭 No joins found that link table DCs with interactive DCs")

                # ENHANCED COMPATIBILITY CHECK: Now considers join configurations
                # DCs are compatible if:
                # 1. Interactive DCs are directly part of table DCs (subset), OR
                # 2. Table DCs are directly part of interactive DCs (single table case), OR
                # 3. A JOIN CONFIGURATION exists linking them (NEW!), OR
                # 4. No interactive filters are active
                dc_compatible = (
                    interactive_dc_ids.issubset(table_dc_ids)
                    or table_dc_ids.issubset(interactive_dc_ids)
                    or has_join_between_dcs  # NEW: Join-based compatibility
                    or not interactive_dc_ids
                )

                # Log detailed compatibility analysis
                logger.info(
                    f"🔗 Table {table_index}: DC Compatibility Check\n"
                    f"   Compatible: {dc_compatible}\n"
                    f"   Has Joins: {has_join_between_dcs}\n"
                    f"   Joins Found: {len(joins_dict)} configurations\n"
                    f"   Table DCs: {table_dc_ids}\n"
                    f"   Interactive DCs: {interactive_dc_ids}"
                )

                if dc_compatible:
                    if has_join_between_dcs:
                        logger.info(
                            "✅ DC COMPATIBLE (via JOIN): Will use iterative_join for filtering"
                        )
                    else:
                        logger.info(
                            "✅ DC COMPATIBLE (direct match): Interactive filters target same DC as table"
                        )
                else:
                    logger.warning(
                        f"⚠️ DC INCOMPATIBLE: No direct match or join between table_dcs={table_dc_ids} and interactive_dcs={interactive_dc_ids}"
                    )

                if dc_compatible:
                    logger.info("✅ DC COMPATIBLE: Applying joins and filters")

                    # CRITICAL DECISION: Choose between semi-join filtering vs full join
                    # Semi-join: Single table DC filtered by values from interactive DC (no expansion)
                    # Full join: Table shows genuinely joined data (may expand rows)
                    is_single_table_dc = len(table_dc_ids) == 1 and "--" not in str(table_dc_id)
                    is_cross_dc_filter = interactive_dc_ids != table_dc_ids and bool(
                        interactive_dc_ids
                    )

                    use_semi_join = (
                        is_single_table_dc and is_cross_dc_filter and has_join_between_dcs
                    )

                    if use_semi_join:
                        # SEMI-JOIN FILTERING: Filter single-DC table by cross-DC interactive values
                        # This prevents unwanted Cartesian product expansion
                        logger.info(
                            f"🎯 SEMI-JOIN MODE: Table shows single DC ({table_dc_id}), filtering by interactive DC ({interactive_dc_ids}) via join"
                        )
                        logger.info(
                            "💡 Using semi-join to avoid Cartesian product - table rows will be filtered, not expanded"
                        )

                        try:
                            # Step 1: Find the join configuration between table and interactive DCs
                            join_config = None
                            for join_key_tuple, join_details_list in joins_dict.items():
                                join_dc_set = set(join_key_tuple)
                                if table_dc_ids & join_dc_set and interactive_dc_ids & join_dc_set:
                                    # Found the relevant join
                                    join_config = join_details_list[0]  # Get first join details
                                    join_columns = list(join_config.values())[0]["on_columns"]
                                    logger.info(f"🔗 Join columns: {join_columns}")
                                    break

                            if not join_config:
                                raise ValueError(
                                    f"No join configuration found between {table_dc_ids} and {interactive_dc_ids}"
                                )

                            # Step 2: Load interactive DC with filters applied
                            interactive_dc_id = list(interactive_dc_ids)[
                                0
                            ]  # Get the first (and should be only) interactive DC
                            interactive_metadata = [
                                comp_data
                                for comp_data in interactive_components_dict.values()
                                if comp_data.get("metadata", {}).get("dc_id") == interactive_dc_id
                            ]

                            logger.info(
                                f"📥 Loading interactive DC {interactive_dc_id} with {len(interactive_metadata)} filter(s)"
                            )
                            interactive_df = load_deltatable_lite(
                                ObjectId(workflow_id),
                                ObjectId(interactive_dc_id),
                                metadata=interactive_metadata,
                                TOKEN=TOKEN,
                            )
                            logger.info(
                                f"📊 Interactive DC loaded: {interactive_df.shape[0]} filtered rows"
                            )

                            # Step 3: Extract unique join column values from filtered interactive DC
                            join_column = join_columns[0]  # Use first join column
                            if join_column not in interactive_df.columns:
                                raise ValueError(
                                    f"Join column '{join_column}' not found in interactive DC columns: {interactive_df.columns}"
                                )

                            filtered_join_values = interactive_df[join_column].unique().to_list()
                            logger.info(
                                f"🔍 Extracted {len(filtered_join_values)} unique values from join column '{join_column}'"
                            )
                            logger.debug(f"Sample join values: {filtered_join_values[:10]}")

                            # Step 4: Load table DC (unfiltered)
                            logger.info(f"📥 Loading table DC {table_dc_id} (unfiltered)")
                            table_df = load_deltatable_lite(
                                ObjectId(workflow_id),
                                ObjectId(table_dc_id),
                                metadata=None,  # No filters yet
                                TOKEN=TOKEN,
                            )
                            logger.info(f"📊 Table DC loaded: {table_df.shape[0]} rows")

                            # Step 5: Apply semi-join filter (filter table by join column values)
                            if join_column not in table_df.columns:
                                raise ValueError(
                                    f"Join column '{join_column}' not found in table DC columns: {table_df.columns}"
                                )

                            df = table_df.filter(pl.col(join_column).is_in(filtered_join_values))
                            logger.info(
                                f"✅ SEMI-JOIN SUCCESS: Filtered table from {table_df.shape[0]} → {df.shape[0]} rows (NO expansion)"
                            )
                            logger.info(
                                f"📉 Reduction: {table_df.shape[0] - df.shape[0]} rows removed by semi-join filter"
                            )

                        except Exception as semi_join_error:
                            logger.error(f"❌ Semi-join filtering failed: {str(semi_join_error)}")
                            logger.error(f"❌ Error type: {type(semi_join_error)}")
                            import traceback

                            logger.error(f"❌ Full traceback: {traceback.format_exc()}")

                            # Fallback: Load table without filtering
                            logger.warning("🔧 Falling back to unfiltered table data")
                            df = load_deltatable_lite(
                                ObjectId(workflow_id),
                                ObjectId(data_collection_id),
                                metadata=None,
                                TOKEN=TOKEN,
                            )
                            logger.info(
                                f"✅ Fallback: Loaded unfiltered table data ({df.shape[0]} rows)"
                            )
                    else:
                        # FULL JOIN MODE: Table genuinely shows joined data (may expand rows)
                        logger.info("🔗 FULL JOIN MODE: Using iterative_join for joined table data")
                        logger.info(
                            f"💡 Table DCs: {table_dc_ids}, Interactive DCs: {interactive_dc_ids}"
                        )

                        try:
                            df = iterative_join(
                                workflow_id, joins_dict, interactive_components_dict, TOKEN
                            )
                            logger.info(
                                f"✅ Successfully loaded FILTERED data via iterative_join (shape: {df.shape})"
                            )

                            # Verify that filtering actually occurred
                            if df.shape[0] > 0:
                                logger.info(
                                    f"🎯 Filtered dataset contains {df.shape[0]} rows after applying interactive filters"
                                )
                            else:
                                logger.warning(
                                    "⚠️ Filtered dataset is empty - interactive filters excluded all data"
                                )

                        except Exception as interactive_error:
                            # Handle column mismatch or other interactive filter errors gracefully
                            logger.error(
                                f"❌ Interactive filtering failed: {str(interactive_error)}"
                            )
                            logger.error(f"❌ Error type: {type(interactive_error)}")
                            logger.error(f"❌ Error details: {interactive_error}")

                            if "unable to find column" in str(interactive_error):
                                logger.warning(
                                    "💥 Column mismatch: Interactive components use different columns than table"
                                )
                                logger.warning(
                                    "🔧 This indicates a configuration issue - interactive components should target same data collection"
                                )

                            # Fallback: Load without interactive filters
                            logger.warning("🔧 Falling back to unfiltered data loading")
                            df = load_deltatable_lite(
                                ObjectId(workflow_id),
                                ObjectId(data_collection_id),
                                metadata=None,
                                TOKEN=TOKEN,
                            )
                            logger.info("✅ Fallback: Loaded unfiltered data successfully")
                else:
                    # DC INCOMPATIBLE: Load table data WITHOUT joins to avoid unwanted Cartesian products
                    logger.warning(
                        f"⚠️ DC INCOMPATIBLE: Interactive filters target different DCs ({interactive_dc_ids}) than table ({table_dc_id})"
                    )
                    logger.warning(
                        "🔧 Loading table data UNJOINED to prevent unwanted Cartesian product joins"
                    )
                    logger.warning(
                        "💡 Interactive filtering is DISABLED for this table - filters apply to other dashboard components only"
                    )

                    # Load table data directly without any joins
                    df = load_deltatable_lite(
                        ObjectId(workflow_id),
                        ObjectId(data_collection_id),
                        metadata=None,
                        TOKEN=TOKEN,
                    )
                    logger.info(f"✅ Loaded unjoined table data successfully (shape: {df.shape})")
            else:
                # No interactive components - check if table needs joins anyway
                logger.info(
                    f"💾 Loading delta table data (no interactive components): {workflow_id}:{data_collection_id}"
                )

                # CRITICAL: Even without interactive components, check if table requires joins
                try:
                    logger.debug(
                        f"🔗 Checking for table joins with metadata: {stored_metadata_for_join}"
                    )
                    # CRITICAL FIX: Pass workflow_id as string, not ObjectId
                    joins_dict = return_joins_dict(workflow_id, stored_metadata_for_join, TOKEN)
                    logger.info(f"🔗 Table joins result: {joins_dict}")

                    if joins_dict:
                        # Table requires joins - use iterative_join even without interactive components
                        logger.info(
                            "🔗 Table requires joins - using iterative_join for joined data"
                        )
                        df = iterative_join(
                            workflow_id, joins_dict, {}, TOKEN
                        )  # Empty interactive dict
                        logger.info(f"✅ Successfully loaded joined table data (shape: {df.shape})")
                    else:
                        # No joins needed - direct loading
                        df = load_deltatable_lite(
                            ObjectId(workflow_id),
                            ObjectId(data_collection_id),
                            metadata=None,
                            TOKEN=TOKEN,
                        )
                        logger.info(f"✅ Successfully loaded single table data (shape: {df.shape})")

                except Exception as join_error:
                    logger.warning(f"⚠️ Error checking table joins: {str(join_error)}")
                    import traceback

                    logger.warning(f"⚠️ Join error traceback: {traceback.format_exc()}")
                    # Fallback to direct loading
                    df = load_deltatable_lite(
                        ObjectId(workflow_id),
                        ObjectId(data_collection_id),
                        metadata=None,
                        TOKEN=TOKEN,
                    )
                    logger.info(f"✅ Fallback: Loaded single table data (shape: {df.shape})")

            logger.info(f"📊 Loaded initial dataset: {df.shape[0]} rows, {df.shape[1]} columns")

            # APPLY AG GRID FILTERS: Server-side filtering
            if filter_model:
                logger.info(f"🔍 Applying {len(filter_model)} AG Grid filters")
                for col, filter_def in filter_model.items():
                    try:
                        if "operator" in filter_def:
                            # Handle complex filters with AND/OR operators
                            if filter_def["operator"] == "AND":
                                df = apply_ag_grid_filter(df, filter_def["condition1"], col)
                                df = apply_ag_grid_filter(df, filter_def["condition2"], col)
                                logger.debug(f"Applied AND filter to column {col}")
                            else:  # OR operator
                                df1 = apply_ag_grid_filter(df, filter_def["condition1"], col)
                                df2 = apply_ag_grid_filter(df, filter_def["condition2"], col)
                                # Combine results using union (concatenate and remove duplicates)
                                df = pl.concat([df1, df2]).unique()
                                logger.debug(f"Applied OR filter to column {col}")
                        else:
                            # Handle simple filters
                            df = apply_ag_grid_filter(df, filter_def, col)
                            logger.debug(f"Applied simple filter to column {col}")
                    except Exception as e:
                        logger.warning(f"Failed to apply filter for column {col}: {e}")
                        continue

                logger.info(f"📊 After filtering: {df.shape[0]} rows remaining")

            # APPLY AG GRID SORTING: Server-side sorting
            if sort_model:
                logger.info(f"🔤 Applying sorting: {[(s['colId'], s['sort']) for s in sort_model]}")
                df = apply_ag_grid_sorting(df, sort_model)
                logger.info("✅ Sorting applied successfully")

            total_rows = df.shape[0]
            logger.info(
                f"📊 Final dataset after filters/sorting: {total_rows} rows, {df.shape[1]} columns"
            )

            # SLICE DATA: Extract the requested row range
            partial_df = df[start_row:end_row]
            actual_rows_returned = partial_df.shape[0]

            # Transform column names to replace dots with underscores for AgGrid compatibility
            # Do this BEFORE conversion to avoid schema issues
            if any("." in col for col in partial_df.columns):
                column_mapping = {
                    col: col.replace(".", "_") for col in partial_df.columns if "." in col
                }
                partial_df = partial_df.rename(column_mapping)
                logger.debug(
                    f"🔍 Renamed {len(column_mapping)} columns for AgGrid: {list(column_mapping.keys())}"
                )

            # Add ID field for row indexing
            partial_df = partial_df.with_columns(
                pl.Series("ID", range(start_row, start_row + len(partial_df)))
            )

            # Convert directly to dicts (AG Grid supports Polars natively - no Pandas conversion needed)
            # This avoids the Polars -> Pandas -> dict conversion chain and potential Arrow RecordBatch errors
            row_data = partial_df.to_dicts()
            logger.debug(f"✅ Converted {len(row_data)} rows to dicts using Polars native method")

            # LOGGING: Track successful data delivery
            logger.info(
                f"✅ Table {table_index}: Delivered {actual_rows_returned} rows ({start_row}-{start_row + actual_rows_returned})"
            )
            logger.info(f"📋 Response: {actual_rows_returned} rows from {total_rows} total")

            # Return data in format expected by dash-ag-grid infinite model
            response = {
                "rowData": row_data,
                "rowCount": total_rows,  # Total number of rows available
            }

            logger.info(
                f"🚀 INFINITE SCROLL + PAGINATION RESPONSE SENT - {actual_rows_returned}/{total_rows} rows"
            )

            # HYBRID SUCCESS: Log successful integration of interactive + infinite scroll
            if interactive_components_dict:
                # Check if filtering actually reduced the dataset
                active_filters = [
                    (k, v.get("value"))
                    for k, v in interactive_components_dict.items()
                    if v.get("value") is not None
                ]
                logger.info(
                    f"🎯 HYBRID SUCCESS: Interactive + infinite scroll delivered {actual_rows_returned}/{total_rows} rows"
                )
                logger.info(f"🎛️ Active interactive filters: {active_filters}")
                logger.info(
                    f"📊 Dataset after filtering: {total_rows} total rows available for pagination"
                )

                if active_filters:
                    logger.info(
                        f"✅ FILTERING CONFIRMED: {len(active_filters)} active filters reduced dataset"
                    )
                else:
                    logger.info(
                        "📭 NO ACTIVE FILTERS: Interactive components exist but no values set"
                    )
            else:
                logger.info(
                    f"📊 INFINITE SCROLL: Standard pagination delivered {actual_rows_returned}/{total_rows} rows"
                )

            return response

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"❌ Error in infinite scroll callback for table {table_index}: {error_msg}"
            )
            logger.error(f"🔧 Error details - wf_id: {workflow_id}, dc_id: {data_collection_id}")

            # Return empty response on error
            return {"rowData": [], "rowCount": 0}
