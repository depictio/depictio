# Import necessary libraries
import dash_mantine_components as dmc
import httpx
import polars as pl
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL

# Depictio imports
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import (
    get_dmc_button_color,
    is_enabled,
)
from depictio.dash.modules.table_component.utils import build_table, build_table_frame
from depictio.dash.utils import UNSELECTED_STYLE, get_columns_from_data_collection

# TODO: interactivity when selecting table rows

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
    try:
        if "filter" in filter_model:
            if filter_model["filterType"] == "date":
                crit1 = filter_model["dateFrom"]
                if "dateTo" in filter_model:
                    crit2 = filter_model["dateTo"]
            else:
                crit1 = filter_model["filter"]
                if "filterTo" in filter_model:
                    crit2 = filter_model["filterTo"]

        if "type" in filter_model:
            filter_type = filter_model["type"]

            if filter_type == "contains":
                df = df.filter(pl.col(col).str.contains(crit1, literal=False))
            elif filter_type == "notContains":
                df = df.filter(~pl.col(col).str.contains(crit1, literal=False))
            elif filter_type == "startsWith":
                df = df.filter(pl.col(col).str.starts_with(crit1))
            elif filter_type == "notStartsWith":
                df = df.filter(~pl.col(col).str.starts_with(crit1))
            elif filter_type == "endsWith":
                df = df.filter(pl.col(col).str.ends_with(crit1))
            elif filter_type == "notEndsWith":
                df = df.filter(~pl.col(col).str.ends_with(crit1))
            elif filter_type == "inRange":
                if filter_model["filterType"] == "date":
                    # Handle date range filtering
                    df = df.filter(pl.col(col).is_between(crit1, crit2))
                else:
                    df = df.filter(pl.col(col).is_between(crit1, crit2))
            elif filter_type == "blank":
                df = df.filter(pl.col(col).is_null())
            elif filter_type == "notBlank":
                df = df.filter(pl.col(col).is_not_null())
            else:
                # Handle numeric comparisons
                if filter_type in OPERATORS:
                    op = OPERATORS[filter_type]
                    if op == "eq":
                        df = df.filter(pl.col(col) == crit1)
                    elif op == "ne":
                        df = df.filter(pl.col(col) != crit1)
                    elif op == "lt":
                        df = df.filter(pl.col(col) < crit1)
                    elif op == "le":
                        df = df.filter(pl.col(col) <= crit1)
                    elif op == "gt":
                        df = df.filter(pl.col(col) > crit1)
                    elif op == "ge":
                        df = df.filter(pl.col(col) >= crit1)

        elif filter_model["filterType"] == "set":
            # Handle set filter (multi-select)
            df = df.filter(pl.col(col).cast(pl.Utf8).is_in(filter_model["values"]))

    except Exception as e:
        logger.warning(f"Failed to apply filter for column {col}: {e}")
        # Return original dataframe if filter fails
        pass

    return df


def apply_ag_grid_sorting(df: pl.DataFrame, sort_model: list) -> pl.DataFrame:
    """
    Apply AG Grid sorting to a Polars DataFrame.
    """
    if not sort_model:
        return df

    try:
        # Apply sorting - Polars uses descending parameter differently
        df = df.sort(
            [sort["colId"] for sort in sort_model],
            descending=[sort["sort"] == "desc" for sort in sort_model],
        )

        logger.debug(f"Applied sorting: {[(s['colId'], s['sort']) for s in sort_model]}")

    except Exception as e:
        logger.warning(f"Failed to apply sorting: {e}")

    return df


def register_callbacks_table_component(app):
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
            State("live-interactivity-toggle", "checked"),
        ],
        prevent_initial_call=False,
    )
    def infinite_scroll_component(
        request, interactive_values, stored_metadata, local_store, pathname, live_interactivity_on
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
        from dash import ctx, no_update

        from depictio.api.v1.deltatables_utils import (
            iterative_join,
            load_deltatable_lite,
            return_joins_dict,
        )

        # CACHE INVALIDATION: Detect if triggered by interactive component changes
        triggered_by_interactive = ctx.triggered and any(
            "interactive-values-store" in str(trigger["prop_id"]) for trigger in ctx.triggered
        )

        logger.info(f"🔄 INFINITE SCROLL CALLBACK TRIGGERED - {ctx.triggered}")

        # Detailed analysis of interactive values
        if interactive_values and "interactive_components_values" in interactive_values:
            components_count = len(interactive_values["interactive_components_values"])
            scatter_filters = [
                c.get("index", "")
                for c in interactive_values["interactive_components_values"]
                if c.get("index", "").startswith("filter_")
            ]
            logger.info(
                f"🎯 TABLE: {components_count} total components, {len(scatter_filters)} scatter filters: {scatter_filters}"
            )
        else:
            logger.info("🎯 TABLE: No interactive values or malformed data")

        # LOGGING: Track infinite scroll requests and trigger source
        logger.info("🔄 INFINITE SCROLL + INTERACTIVE REQUEST RECEIVED")
        logger.info(f"📊 Request details: {request}")
        logger.info(f"🎯 Triggered by: {ctx.triggered_id if ctx.triggered else 'Unknown'}")
        logger.info(f"🎛️ Interactive trigger: {triggered_by_interactive}")
        logger.info(f"📦 Interactive values: {interactive_values}")
        logger.info(f"🗃️ Stored metadata: {stored_metadata}")
        logger.info(f"🏪 Local store exists: {bool(local_store)}")

        # Validate inputs
        if not local_store or not stored_metadata:
            logger.warning(
                "❌ Missing required data for infinite scroll - local_store or stored_metadata"
            )
            return no_update

        # Check live interactivity state before processing interactive changes
        if request is None and triggered_by_interactive:
            if not live_interactivity_on:
                logger.info(
                    "⏸️ NON-LIVE MODE: Interactive values changed but live interactivity is OFF - ignoring update"
                )
                return no_update

            logger.info("🔄 LIVE MODE: Interactive values changed - processing data immediately")
            # Create a synthetic request for the first page to start the refresh process
            request = {
                "startRow": 0,
                "endRow": 100,  # Standard first page size
                "filterModel": {},
                "sortModel": [],
            }
            logger.info("🔄 Created synthetic request to trigger immediate data loading")
        elif request is None:
            logger.info("⏸️ No data request and not interactive trigger - skipping callback")
            return no_update

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

        # ITERATIVE JOIN PATTERN: Process interactive components properly
        dashboard_id = pathname.split("/")[-1]
        interactive_components_dict = {}

        # CRITICAL FIX: Extract interactive components from store data correctly
        logger.info(f"🔍 Raw interactive_values structure: {interactive_values}")

        if interactive_values:
            # Check multiple possible structures in interactive_values store
            if "interactive_components_values" in interactive_values:
                # Direct structure: interactive_values["interactive_components_values"]
                interactive_values_data = interactive_values["interactive_components_values"]
                logger.info(
                    f"📦 Found direct interactive_components_values: {len(interactive_values_data)} items"
                )

            elif (
                dashboard_id in interactive_values
                and "interactive_components_values" in interactive_values[dashboard_id]
            ):
                # Dashboard-specific structure: interactive_values[dashboard_id]["interactive_components_values"]
                interactive_values_data = interactive_values[dashboard_id][
                    "interactive_components_values"
                ]
                logger.info(
                    f"📦 Found dashboard-specific interactive_components_values: {len(interactive_values_data)} items"
                )

            elif dashboard_id in interactive_values and isinstance(
                interactive_values[dashboard_id], dict
            ):
                # Try to find interactive components in dashboard data
                interactive_values_data = []
                for key, value in interactive_values[dashboard_id].items():
                    if (
                        isinstance(value, dict)
                        and value.get("metadata", {}).get("component_type") == "interactive"
                    ):
                        interactive_values_data.append(value)
                logger.info(
                    f"📦 Extracted interactive components from dashboard structure: {len(interactive_values_data)} items"
                )

            else:
                # Fallback: try to extract from any nested structure
                interactive_values_data = []
                logger.warning(
                    f"⚠️ Unknown interactive_values structure, attempting extraction from: {list(interactive_values.keys())}"
                )

            # Convert to dictionary format expected by iterative_join
            for component_data in interactive_values_data:
                if isinstance(component_data, dict):
                    component_type = component_data.get("metadata", {}).get("component_type")
                    component_index = component_data.get("index")
                    component_value = component_data.get("value")

                    if component_type == "interactive" and component_index:
                        interactive_components_dict[component_index] = component_data
                        logger.info(
                            f"🎛️ Added interactive component {component_index}: {component_type} = {component_value}"
                        )

            logger.info(
                f"🎯 Table {table_index}: Processed {len(interactive_components_dict)} interactive components"
            )
            logger.info(
                f"🔍 Interactive component indexes: {list(interactive_components_dict.keys())}"
            )
        else:
            logger.info("📭 No interactive_values provided - using unfiltered data")

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

                logger.info(f"🎛️ Interactive DCs: {interactive_dc_ids}")

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
                if dc_compatible:
                    if has_join_between_dcs:
                        logger.info(
                            f"✅ DC COMPATIBLE (via JOIN): Table DCs={table_dc_ids}, Interactive DCs={interactive_dc_ids}"
                        )
                        logger.info(
                            "🔗 Join configuration detected - will use iterative_join for filtering"
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

    # Callback to update card body based on the selected column and aggregation
    @app.callback(
        Output({"type": "table-body", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-table", "index": MATCH}, "n_clicks"),
            Input({"type": "btn-table", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("theme-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def design_table_component(workflow_id, data_collection_id, n_clicks, id, data, theme):
        """
        Callback to update card body based on the selected column and aggregation
        """

        if not data:
            return None

        TOKEN = data["access_token"]

        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        # Get the workflow and data collection ids from the tags selected
        # workflow_id, data_collection_id = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_tag, TOKEN=TOKEN)

        # Get the data collection specs
        # Handle joined data collection IDs
        if isinstance(data_collection_id, str) and "--" in data_collection_id:
            # For joined data collections, create synthetic specs
            dc_specs = {
                "config": {"type": "table", "metatype": "joined"},
                "data_collection_tag": f"Joined data collection ({data_collection_id})",
                "description": "Virtual joined data collection",
                "_id": data_collection_id,
            }
        else:
            # Regular data collection - fetch from API
            dc_specs = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
                headers=headers,
            ).json()

        cols_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)

        # Get the join tables for the selected workflow - used in store for metadata management
        # join_tables_for_wf = httpx.get(
        #     f"{API_BASE_URL}/depictio/api/v1/workflows/get_join_tables/{workflow_id}",
        #     headers=headers,
        # )

        # # If the request is successful, get the join details for the selected data collection
        # if join_tables_for_wf.status_code == 200:
        #     join_tables_for_wf = join_tables_for_wf.json()
        #     if data_collection_id in join_tables_for_wf:
        #         join_details = join_tables_for_wf[data_collection_id]
        #         dc_specs["config"]["join"] = join_details

        table_kwargs = {
            "index": id["index"],
            "wf_id": workflow_id,
            "dc_id": data_collection_id,
            "dc_config": dc_specs["config"],
            "cols_json": cols_json,
            "access_token": TOKEN,
            "stepper": True,
            "build_frame": True,  # Use frame for editing with loading
            "theme": theme,
        }
        logger.info(f"🔄 Building table with kwargs: {table_kwargs}")
        new_table = build_table(**table_kwargs)
        return new_table


def design_table(id):
    row = [
        dmc.Center(
            dmc.Button(
                "Display Table",
                id={"type": "btn-table", "index": id["index"]},
                n_clicks=1,
                style=UNSELECTED_STYLE,
                size="xl",
                color="green",
                leftSection=DashIconify(
                    icon="material-symbols:table-rows-narrow-rounded", color="white"
                ),
            )
        ),
        html.Div(
            html.Div(
                build_table_frame(index=id["index"]),
                # dbc.CardBody(
                #     html.Div(id={"type": "table-grid", "index": id["index"]}),
                #     id={
                #         "type": "card-body",
                #         "index": id["index"],
                #     },
                # ),
                id={
                    "type": "component-container",
                    "index": id["index"],
                },
            ),
            # dbc.Card(
            #     dbc.CardBody(
            #         html.Div(id={"type": "table-grid", "index": id["index"]}),
            #         id={
            #             "type": "card-body",
            #             "index": id["index"],
            #         },
            #     ),
            #     id={
            #         "type": "component-container",
            #         "index": id["index"],
            #     },
            # )
        ),
    ]
    return row
    # return html.Div(
    #             build_table_frame(index=id["index"]),
    #             # dbc.CardBody(
    #             #     html.Div(id={"type": "table-grid", "index": id["index"]}),
    #             #     id={
    #             #         "type": "card-body",
    #             #         "index": id["index"],
    #             #     },
    #             # ),
    #             id={
    #                 "type": "component-container",
    #                 "index": id["index"],
    #             },
    #         )


def create_stepper_table_button(n, disabled=None):
    """
    Create the stepper table button

    Args:
        n (_type_): _description_
        disabled (bool, optional): Override enabled state. If None, uses metadata.
    """

    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("table")

    from depictio.dash.component_metadata import get_component_color

    dmc_color = get_dmc_button_color("table")
    hex_color = get_component_color("table")  # This returns the hex color from colors.py
    logger.info(f"Table button DMC color: {dmc_color}, hex color: {hex_color}")

    # Create the table button with outline variant and larger text
    button = dmc.Button(
        "Table",
        id={
            "type": "btn-option",
            "index": n,
            "value": "Table",
        },
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=dmc_color,
        leftSection=DashIconify(icon="octicon:table-24", color=hex_color),
        disabled=disabled,
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Table",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
