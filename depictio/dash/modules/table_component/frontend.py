# Import necessary libraries
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import httpx
import polars as pl
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger

# Depictio imports
from depictio.dash.modules.table_component.utils import build_table, build_table_frame
from depictio.dash.utils import UNSELECTED_STYLE, get_columns_from_data_collection

# TODO: interactivity when selecting table rows


def apply_polars_filter(df: pl.DataFrame, filter_config: dict) -> pl.DataFrame:
    """
    Apply interactive component filters using Polars for optimal performance.

    Args:
        df: Polars DataFrame to filter
        filter_config: Filter configuration from interactive component

    Returns:
        Filtered Polars DataFrame
    """
    metadata = filter_config.get("metadata", {})
    column_name = metadata.get("column_name")
    column_type = metadata.get("column_type")
    component_type = metadata.get("interactive_component_type")
    value = filter_config.get("value")

    if not column_name or value is None:
        return df

    try:
        # Handle object/string columns
        if column_type == "object":
            if component_type in ["Select", "MultiSelect", "SegmentedControl"]:
                # Handle dropdown selections
                if isinstance(value, str):
                    value = [value]
                if value:  # Only filter if value is not empty
                    return df.filter(pl.col(column_name).is_in(value))

            elif component_type == "TextInput":
                # Handle text input with regex support
                if value.strip():  # Only filter if value is not empty
                    return df.filter(pl.col(column_name).str.contains(value, strict=False))

        # Handle numeric columns
        elif column_type in ["int64", "float64"]:
            if component_type == "RangeSlider":
                # Handle range sliders
                if isinstance(value, (list, tuple)) and len(value) == 2:
                    min_val, max_val = value
                    return df.filter(
                        (pl.col(column_name) >= min_val) & (pl.col(column_name) <= max_val)
                    )

            elif component_type == "Slider":
                # Handle single value sliders
                return df.filter(pl.col(column_name) == value)

        # Handle datetime columns (future enhancement)
        elif column_type == "datetime":
            # Add datetime filtering logic as needed
            logger.warning(f"Datetime filtering not implemented yet for column {column_name}")

    except Exception as e:
        logger.error(f"Error applying Polars filter to column {column_name}: {e}")

    return df


def register_callbacks_table_component(app):
    @app.callback(
        Output({"type": "table-aggrid", "index": MATCH}, "getRowsResponse"),
        Input("interactive-values-store", "data"),
        Input({"type": "table-aggrid", "index": MATCH}, "getRowsRequest"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def infinite_scroll_component(interactive_values, request, local_store, pathname):
        """
        Handle infinite scrolling for AG Grid tables with interactive component filtering.

        This callback:
        1. Receives getRowsRequest from AG Grid (pagination info)
        2. Gets current interactive component values for filtering
        3. Applies filters to the delta table data
        4. Returns paginated data via getRowsResponse
        """
        try:
            # Basic validation
            if not local_store:
                logger.warning("Missing local_store")
                return {"rowData": [], "rowCount": 0}

            # Get the table component index from the callback context
            from dash import callback_context as ctx

            if not ctx.triggered:
                logger.warning("No trigger context available")
                return {"rowData": [], "rowCount": 0}

            # Extract the index from the triggered component
            table_index = None
            for input_info in ctx.inputs_list[1]:  # getRowsRequest input
                if input_info["id"]["type"] == "table-aggrid":
                    table_index = input_info["id"]["index"]
                    break

            if not table_index:
                logger.warning("Could not extract table index from callback context")
                return {"rowData": [], "rowCount": 0}

            # For stepper tables (with -tmp suffix), disable infinite scrolling for now
            # Infinite scrolling works best with dashboard tables where metadata is properly stored
            if "-tmp" in table_index:
                logger.info(f"Stepper table detected ({table_index}), skipping infinite scroll")
                return {"rowData": [], "rowCount": 0}

            # For dashboard tables, the metadata should be available normally
            # This will be implemented when the table is used in dashboard context
            logger.warning(f"Dashboard table infinite scroll not yet implemented for {table_index}")
            return {"rowData": [], "rowCount": 0}

        except Exception as e:
            logger.error(f"Error in infinite_scroll_component: {e}")
            # Return empty response on error to prevent AG Grid from breaking
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


def create_stepper_table_button(n, disabled=False):
    """
    Create the stepper table button
    """

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
            color="green",
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
