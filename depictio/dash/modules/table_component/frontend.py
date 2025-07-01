# Import necessary libraries
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import httpx
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL

# Depictio imports
from depictio.dash.modules.table_component.utils import build_table, build_table_frame
from depictio.dash.utils import UNSELECTED_STYLE, get_columns_from_data_collection

# TODO: interactivity when selecting table rows


def register_callbacks_table_component(app):
    # @app.callback(
    #     Output({"type": "table-aggrid", "index": MATCH}, "getRowsResponse"),
    #     Input("interactive-values-store", "data"),
    #     Input({"type": "table-aggrid", "index": MATCH}, "getRowsRequest"),
    #     State({"type": "stored-metadata-component", "index": MATCH}, "data"),
    #     State("local-store", "data"),
    #     State("url", "pathname"),
    #     prevent_initial_call=True,
    # )
    # def infinite_scroll_component(interactive_values, request, stored_metadata, local_store, pathname):
    #     # simulate slow callback
    #     # time.sleep(2)

    #     dashboard_id = pathname.split("/")[-1]

    #     logger.info(f"Interactive values: {interactive_values}")
    #     if dashboard_id not in interactive_values:
    #         interactive_values_data = None
    #     else:
    #         if "interactive_components_values" not in interactive_values[dashboard_id]:
    #             interactive_values_data = None
    #         else:
    #             interactive_values_data = interactive_values[dashboard_id]["interactive_components_values"]

    #         # Make sure all the interactive values are in the correct format
    #         interactive_values_data = [e for e in interactive_values_data if e["metadata"]["component_type"] == "interactive"]
    #     logger.info(f"Interactive values data: {interactive_values_data}")
    #     logger.info(f"Request: {request}")
    #     logger.info(f"Stored metadata: {stored_metadata}")
    #     logger.info(f"Local store: {local_store}")

    #     # if local_store is None:
    #     #     raise dash.exceptions.PreventUpdate

    #     TOKEN = local_store["access_token"]

    #     # if request is None:
    #     #     return dash.no_update

    #     # if stored_metadata_all is not None:
    #     logger.info(f"Stored metadata: {stored_metadata}")

    #     workflow_id = stored_metadata["wf_id"]
    #     data_collection_id = stored_metadata["dc_id"]

    #     dc_specs = httpx.get(
    #         f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
    #         headers={
    #             "Authorization": f"Bearer {TOKEN}",
    #         },
    #     ).json()

    #     # Initialize metadata list by converting filterModel
    #     if request:
    #         if "filterModel" in request:
    #             # if request["filterModel"]:
    #             metadata = convert_filter_model_to_metadata(request["filterModel"])
    #     else:
    #         metadata = list()

    #     logger.info(f"Metadata generated from filter model: {metadata}")

    #     if interactive_values_data:
    #         # Combine both metadata and stored metadata
    #         metadata += interactive_values_data

    #     # logger.info(f"Metadata: {metadata}")
    #     # logger.info(f"Stored metadata: {stored_metadata}")

    #     # if dc_specs["config"]["type"] == "Table":
    #     df = load_deltatable_lite(workflow_id, data_collection_id, metadata=metadata, TOKEN=TOKEN)

    #     from dash import ctx
    #     import polars as pl

    #     triggered_id = ctx.triggered_id
    #     logger.info(f"Triggered ID: {triggered_id}")

    #     if request is None:
    #         partial = df[:100]
    #     else:
    #         partial = df[request["startRow"] : request["endRow"]]
    #     return {"rowData": partial.to_dicts(), "rowCount": df.shape[0]}
    #     # else:
    #     #     return dash.no_update
    #     # else:
    #     #     return dash.no_update

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
