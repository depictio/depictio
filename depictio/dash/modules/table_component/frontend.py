# Import necessary libraries
from dash import html, dcc, Input, Output, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx

# Depictio imports
from depictio.dash.modules.table_component.utils import build_table, build_table_frame
from depictio.dash.utils import return_mongoid

from depictio.api.v1.configs.config import API_BASE_URL, TOKEN

from depictio.dash.utils import (
    UNSELECTED_STYLE,
    get_columns_from_data_collection,
)

# TODO: interactivity when selecting table rows


def register_callbacks_table_component(app):
    # Callback to update card body based on the selected column and aggregation
    @app.callback(
        Output({"type": "table-body", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-table", "index": MATCH}, "n_clicks"),
            Input({"type": "btn-table", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def design_table_component(wf_tag, dc_tag, n_clicks, id):
        """
        Callback to update card body based on the selected column and aggregation
        """

        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        # Get the workflow and data collection ids from the tags selected
        workflow_id, data_collection_id = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_tag)

        # Get the data collection specs
        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers=headers,
        ).json()

        cols_json = get_columns_from_data_collection(wf_tag, dc_tag)

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
                    leftIcon=DashIconify(icon="material-symbols:table-rows-narrow-rounded", color="white"),
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
            leftIcon=DashIconify(icon="octicon:table-24", color="white"),
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
