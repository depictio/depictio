# Import necessary libraries
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
from CLI_client.cli import list_workflows


# Depictio imports
from depictio.dash.modules.card_component.utils import (
    agg_functions,
)
from depictio.dash.utils import (
    SELECTED_STYLE,
    UNSELECTED_STYLE,
    list_data_collections_for_dropdown,
    list_workflows_for_dropdown,
    get_columns_from_data_collection,
)

# from depictio.dash_frontend.app import app, df

# df = pd.DataFrame()


def register_callbacks_card_component(app):
    # Callback to update aggregation dropdown options based on the selected column
    @app.callback(
        Output({"type": "card-dropdown-aggregation", "index": MATCH}, "data"),
        [
            Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        ],
        prevent_initial_call=True,
    )
    def update_aggregation_options(column_value, wf_id, dc_id):
        # print("update_aggregation_options", column_value)
        # print("\n\n")

        cols_json = get_columns_from_data_collection(wf_id, dc_id)

        if column_value is None:
            return []

        # Get the type of the selected column
        column_type = cols_json[column_value]["type"]
        # print(column_value, column_type, type(column_type))

        # Get the aggregation functions available for the selected column type
        agg_functions_tmp_methods = agg_functions[str(column_type)]["card_methods"]
        # print(agg_functions_tmp_methods)

        # Create a list of options for the dropdown
        options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]
        # print(options)

        return options

    # Callback to reset aggregation dropdown value based on the selected column
    @app.callback(
        Output({"type": "card-dropdown-aggregation", "index": MATCH}, "value"),
        Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def reset_aggregation_value(column_value):
        return None

    # Callback to update card body based on the selected column and aggregation
    @app.callback(
        Output({"type": "card-body", "index": MATCH}, "children"),
        [
            Input({"type": "card-input", "index": MATCH}, "value"),
            Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "card-dropdown-aggregation", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "card-dropdown-column", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def design_card_body(
        input_value, column_value, aggregation_value, wf_id, dc_id, id
    ):
        if (
            input_value is None
            or column_value is None
            or aggregation_value is None
            or wf_id is None
            or dc_id is None
        ):
            return []

        cols_json = get_columns_from_data_collection(wf_id, dc_id)



        import httpx

        API_BASE_URL = "http://localhost:8058"

        token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2NGE4NDI4NDJiZjRmYTdkZWFhM2RiZWQiLCJleHAiOjE3MDY4NTQzOTJ9.q3sJLcwEwes32JoeAEGQdjlaTnn6rC1xmfHs2jjwJuML1jWgWBzuv37fJDb70y7-pRaRjTojAz9iGcUPC91Zc9krbmO6fXedLVre8a4_TvsgVwZTSPXpikA_t6EeHYjVxCDh_FftGZv0hXeRbOV83ob7GykkUP5HWTuXrv_o8v4S8ccnsy3fVIIy51NZj6MuU4YL2BfPDuWdBp2d0IN2UDognt1wcwsjIt_26AQJQHwQaxDevvzlNA6RvQIcxC5Es5PSHfpaF7w4MxiZ6J-JE25EnQ7Fw1k-z7bsleb_30Qdh68Kjs-c-BOoTm_hxDF-15G9qLPhFTqJMl148oxAjw"



        token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2NGE4NDI4NDJiZjRmYTdkZWFhM2RiZWQiLCJleHAiOjE3MDY4NTQzOTJ9.q3sJLcwEwes32JoeAEGQdjlaTnn6rC1xmfHs2jjwJuML1jWgWBzuv37fJDb70y7-pRaRjTojAz9iGcUPC91Zc9krbmO6fXedLVre8a4_TvsgVwZTSPXpikA_t6EeHYjVxCDh_FftGZv0hXeRbOV83ob7GykkUP5HWTuXrv_o8v4S8ccnsy3fVIIy51NZj6MuU4YL2BfPDuWdBp2d0IN2UDognt1wcwsjIt_26AQJQHwQaxDevvzlNA6RvQIcxC5Es5PSHfpaF7w4MxiZ6J-JE25EnQ7Fw1k-z7bsleb_30Qdh68Kjs-c-BOoTm_hxDF-15G9qLPhFTqJMl148oxAjw"

        workflows = list_workflows(token)


        workflow_id = [e for e in workflows if e["workflow_tag"] == wf_id][0][
            "_id"
        ]
        data_collection_id = [
            f
            for e in workflows
            if e["_id"] == workflow_id
            for f in e["data_collections"]
            if f["data_collection_tag"] == dc_id
        ][0]["_id"]

        import httpx

        API_BASE_URL = "http://localhost:8058"



        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {token}",
            },
        ).json()

        headers = {
            "Authorization": f"Bearer {token}",
        }


        join_tables_for_wf = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/workflows/get_join_tables/{workflow_id}",
            headers=headers,
        )
        if join_tables_for_wf.status_code == 200:
            join_tables_for_wf = join_tables_for_wf.json()
            if data_collection_id in join_tables_for_wf:
                join_details = join_tables_for_wf[data_collection_id]
                dc_specs["config"]["join"] = join_details
                



        # Get the type of the selected column
        column_type = cols_json[column_value]["type"]

        v = cols_json[column_value]["specs"][aggregation_value]

        try:
            v = round(float(v), 2)
        except:
            pass

        store_component = dcc.Store(
            id={
                "type": "stored-metadata-component",
                "index": id["index"],
            },
            data={
                "index": id["index"],
                "component_type": "card",
                "title": input_value,
                "wf_id": workflow_id,
                "dc_id": data_collection_id,
                "dc_config": dc_specs["config"],
                "column_value": column_value,
                "aggregation": aggregation_value,
                "type": column_type,
                
            },
        )
        print(store_component)

        if not input_value:
            card_title = html.H5(f"{aggregation_value} on {column_value}")
        else:
            card_title = html.H5(f"{input_value}")

        new_card_body = [
            card_title,
            html.P(
                f"{v}",
                id={
                    "type": "card-value",
                    "index": id["index"],
                },
            ),
            store_component,
        ]

        return new_card_body


def design_card(id, df):
    row = [
        dmc.Center(
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H5("Card edit menu"),
                            dbc.Card(
                                dbc.CardBody(
                                    [
                                        dmc.TextInput(
                                            label="Card title",
                                            id={
                                                "type": "card-input",
                                                "index": id["index"],
                                            },
                                        ),
                                        dmc.Select(
                                            label="Select your column",
                                            id={
                                                "type": "card-dropdown-column",
                                                "index": id["index"],
                                            },
                                            data=[
                                                {"label": e, "value": e}
                                                for e in df.columns
                                            ],
                                            value=None,
                                        ),
                                        dmc.Select(
                                            label="Select your aggregation method",
                                            id={
                                                "type": "card-dropdown-aggregation",
                                                "index": id["index"],
                                            },
                                            value=None,
                                        ),
                                        html.Div(
                                            id={
                                                # "type": "debug-print",
                                                "index": id["index"],
                                            },
                                        ),
                                    ],
                                ),
                                id={
                                    "type": "card",
                                    "index": id["index"],
                                },
                                style={"width": "100%"},
                            ),
                        ],
                        width="auto",
                    ),
                    dbc.Col(
                        [
                            html.H5("Resulting card"),
                            html.Div(
                                dbc.Card(
                                    dbc.CardBody(
                                        id={
                                            "type": "card-body",
                                            "index": id["index"],
                                        }
                                    ),
                                    style={"width": "100%"},
                                    id={
                                        "type": "interactive",
                                        "index": id["index"],
                                    },
                                ),
                                id={
                                    "type": "test-container",
                                    "index": id["index"],
                                },
                            ),
                        ],
                        width="auto",
                    ),
                ]
            )
        ),
    ]
    return row


def create_stepper_card_button(n):
    """
    Create the stepper card button

    Args:
        n (_type_): _description_

    Returns:
        _type_: _description_
    """

    button = dbc.Col(
        dmc.Button(
            "Card",
            id={
                "type": "btn-option",
                "index": n,
                "value": "Card",
            },
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color="violet",
            leftIcon=DashIconify(icon="formkit:number", color="white"),
        )
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Card",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
