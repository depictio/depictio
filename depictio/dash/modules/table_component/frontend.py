# Import necessary libraries
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import httpx
import polars as pl
from dash_iconify import DashIconify

from dash import MATCH, Input, Output, State, dcc, html
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
    # @app.callback(
    #     Output({"type": "table-aggrid", "index": MATCH}, "className"),
    #     Input("theme-store", "data"),
    #     prevent_initial_call=False,
    # )
    # def update_table_ag_grid_theme(theme_data):
    #     """Update AG Grid theme class based on current theme."""
    #     theme = theme_data or "light"
    #     if theme == "dark":
    #         return "ag-theme-alpine-dark"
    #     else:
    #         return "ag-theme-alpine"

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
        ],
        prevent_initial_call=False,
    )
    def infinite_scroll_component(
        request, interactive_values, stored_metadata, local_store, pathname
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

        # ENHANCED APPROACH: Process interactive changes immediately
        if request is None and triggered_by_interactive:
            logger.info(
                "🔄 IMMEDIATE PROCESSING: Interactive values changed - processing data immediately"
            )
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
            # ENHANCED INTERACTIVE FILTERING: Always check for interactive components first
            if interactive_components_dict:
                logger.info(
                    f"🔗 INFINITE SCROLL + INTERACTIVE: Processing {len(interactive_components_dict)} interactive components"
                )
                logger.info(
                    f"🎯 Interactive components: {[(k, v.get('value')) for k, v in interactive_components_dict.items()]}"
                )

                # Get joins configuration for this workflow and table
                try:
                    logger.debug(
                        f"🔗 Calling return_joins_dict with wf={workflow_id}, metadata={stored_metadata_for_join}"
                    )
                    # CRITICAL FIX: Pass workflow_id as string, not ObjectId
                    joins_dict = return_joins_dict(workflow_id, stored_metadata_for_join, TOKEN)
                    logger.info(f"🔗 Joins dict result: {joins_dict}")
                    logger.debug(f"🔗 Joins dict type: {type(joins_dict)}")
                except Exception as joins_error:
                    logger.error(f"❌ Error getting joins dict: {str(joins_error)}")
                    logger.error(f"❌ Error traceback: {joins_error.__class__.__name__}")
                    import traceback

                    logger.error(f"❌ Full traceback: {traceback.format_exc()}")
                    logger.error("🔧 Falling back to empty joins dict")
                    joins_dict = {}

                # CRITICAL: Always use iterative_join for interactive component filtering
                try:
                    # ALWAYS use iterative_join when interactive components exist
                    # iterative_join handles both join scenarios AND direct filtering
                    logger.info(
                        f"🔗 Using iterative_join for interactive component filtering (joins: {bool(joins_dict)})"
                    )

                    df = iterative_join(workflow_id, joins_dict, interactive_components_dict, TOKEN)
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
                    logger.error(f"❌ Interactive filtering failed: {str(interactive_error)}")
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

            # Convert to format expected by AG Grid
            pandas_df = partial_df.to_pandas()

            # Transform column names to replace dots with underscores for AgGrid compatibility
            column_mapping = {}
            for col in pandas_df.columns:
                if "." in col:
                    new_col = col.replace(".", "_")
                    column_mapping[col] = new_col
                    logger.debug(f"🔍 DEBUG: Renaming column '{col}' to '{new_col}' for AgGrid")

            if column_mapping:
                pandas_df = pandas_df.rename(columns=column_mapping)
                logger.debug(f"🔍 DEBUG: Transformed columns: {list(pandas_df.columns)}")

            # Add ID field for SpinnerCellRenderer (following documentation example)
            pandas_df.reset_index(drop=True, inplace=True)
            pandas_df["ID"] = range(start_row, start_row + len(pandas_df))
            row_data = pandas_df.to_dict("records")

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
        dbc.Row(
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
        ),
        dbc.Row(
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

    color = get_dmc_button_color("table")
    logger.info(f"Table button color: {color}")

    # Create the table button
    button = dbc.Col(
        dmc.Button(
            "Table",
            id={
                "type": "btn-option",
                "index": n,
                "value": "Table",
            },
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color=get_dmc_button_color("table"),
            leftSection=DashIconify(icon="octicon:table-24", color="white"),
            disabled=disabled,
        )
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
