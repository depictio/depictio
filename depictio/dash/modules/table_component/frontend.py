# Import necessary libraries
import dash_bootstrap_components as dbc
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
        prevent_initial_call=True,
    )
    def infinite_scroll_component(
        request, interactive_values, stored_metadata, local_store, pathname
    ):
        """
        INFINITE ROW MODEL CALLBACK WITH PAGINATION
        Handles lazy loading of table data based on scroll position and user interactions.
        This implements the dash-ag-grid infinite row model pattern with pagination enabled
        as shown in the documentation example.
        """
        from bson import ObjectId
        from dash import no_update

        from depictio.api.v1.deltatables_utils import load_deltatable_lite

        # LOGGING: Track infinite scroll requests
        logger.info("🔄 INFINITE SCROLL REQUEST RECEIVED")
        logger.info(f"📊 Request details: {request}")

        # Validate inputs
        if not local_store or not stored_metadata:
            logger.warning(
                "❌ Missing required data for infinite scroll - local_store or stored_metadata"
            )
            return no_update

        if request is None:
            logger.info("⏸️ No data request - skipping infinite scroll callback")
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

        # Handle dashboard-specific interactive values
        dashboard_id = pathname.split("/")[-1]
        interactive_values_data = None

        if interactive_values and dashboard_id in interactive_values:
            if "interactive_components_values" in interactive_values[dashboard_id]:
                interactive_values_data = interactive_values[dashboard_id][
                    "interactive_components_values"
                ]
                # Filter for interactive components only
                interactive_values_data = [
                    e
                    for e in interactive_values_data
                    if e["metadata"]["component_type"] == "interactive"
                ]
                logger.info(
                    f"🎛️ Table {table_index}: {len(interactive_values_data)} interactive filters applied"
                )

        # Prepare metadata for server-side filtering (interactive components only)
        metadata = []

        # Note: AG Grid filters will be applied after data loading
        # This is more efficient than converting to depictio metadata format
        if filter_model:
            logger.info(
                f"🔍 AG Grid filters will be applied server-side: {list(filter_model.keys())}"
            )

        # Add interactive component filters to metadata for initial data loading
        if interactive_values_data:
            metadata.extend(interactive_values_data)
            logger.info(f"✅ Combined metadata: {len(metadata)} interactive filters total")

        # # SIMULATE SLOW LOADING: Add delay to demonstrate infinite scrolling with pagination
        # # Following documentation example pattern
        # import time

        # time.sleep(1.0)  # Increased delay to better demonstrate spinner loading behavior

        try:
            # LOAD DATA: Server-side data loading with filters
            logger.info(f"💾 Loading delta table data for {workflow_id}:{data_collection_id}")
            df = load_deltatable_lite(
                ObjectId(workflow_id),
                ObjectId(data_collection_id),
                metadata=metadata if metadata else None,
                TOKEN=TOKEN,
            )

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
            return response

        except Exception as e:
            logger.error(f"❌ Error in infinite scroll callback for table {table_index}: {str(e)}")
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
        ],
        prevent_initial_call=True,
    )
    def design_table_component(workflow_id, data_collection_id, n_clicks, id, data):
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
        }
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
