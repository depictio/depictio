# Import necessary libraries
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import pandas as pd
from dash_iconify import DashIconify
from CLI_client.cli import list_workflows


# Depictio imports
from depictio.dash.modules.interactive_component.utils import (
    agg_functions,
)
from depictio.dash.utils import (
    SELECTED_STYLE,
    UNSELECTED_STYLE,
    list_data_collections_for_dropdown,
    list_workflows_for_dropdown,
    get_columns_from_data_collection,
    load_deltatable,
)


def register_callbacks_interactive_component(app):
    # Callback to update aggregation dropdown options based on the selected column
    @app.callback(
        Output({"type": "input-dropdown-method", "index": MATCH}, "data"),
        [
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        ],
        prevent_initial_call=True,
    )
    def update_aggregation_options(column_value, wf_id, dc_id):
        cols_json = get_columns_from_data_collection(wf_id, dc_id)
        # print(cols_json)

        if column_value is None:
            return []

        column_type = cols_json[column_value]["type"]

        # Get the type of the selected column
        # column_type = df[column_value].dtype
        # print(column_value, column_type, type(column_type))

        if column_type in ["object", "category"]:
            nb_unique = cols_json[column_value]["specs"]["nunique"]
        else:
            nb_unique = 0

        # Get the aggregation functions available for the selected column type
        agg_functions_tmp_methods = agg_functions[str(column_type)]["input_methods"]
        # print(agg_functions_tmp_methods)

        # Create a list of options for the dropdown
        options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]
        # print(options)

        if nb_unique > 5:
            options = [e for e in options if e["label"] != "SegmentedControl"]

        return options

    # Callback to reset aggregation dropdown value based on the selected column
    @app.callback(
        Output({"type": "input-dropdown-method", "index": MATCH}, "value"),
        Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def reset_aggregation_value(column_value):
        return None

    # Callback to update card body based on the selected column and aggregation
    @app.callback(
        # Output({"type": "title-input-body", "index": MATCH}, "children"),
        # Output({"type": "interactive-component-div", "index": MATCH}, "children"),
        Output({"type": "input-body", "index": MATCH}, "children"),
        [
            Input({"type": "input-title", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "input-dropdown-method", "index": MATCH}, "id")
            # Input("interval", "n_intervals"),
        ],
        prevent_initial_call=True,
    )
    def update_card_body(
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

        df = load_deltatable(wf_id, dc_id)
        cols_json = get_columns_from_data_collection(wf_id, dc_id)
        column_type = cols_json[column_value]["type"]
        func_name = agg_functions[column_type]["input_methods"][aggregation_value][
            "component"
        ]

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



        # Common Store Component
        store_component = dcc.Store(
            id={"type": "stored-metadata-component", "index": id["index"]},
            data={
                "component_type": "interactive_component",
                "interactive_component_type": aggregation_value,
                "index": id["index"],
                "wf_id": wf_id,
                "dc_id": dc_id,
                "dc_config" : dc_specs["config"],
                "column_value": column_value,
                "type": column_type,
            },
            storage_type="memory",
        )

        # Handling different aggregation values
        if aggregation_value in ["Select", "MultiSelect", "SegmentedControl"]:
            data = df[column_value].unique()
            interactive_component = func_name(
                data=data, id={"type": "interactive-component", "index": id["index"]}
            )

        elif aggregation_value == "TextInput":
            interactive_component = func_name(
                placeholder="Your selected value",
                id={"type": "interactive-component", "index": id["index"]},
            )

        elif aggregation_value in ["Slider", "RangeSlider"]:
            min_value, max_value = (
                cols_json[column_value]["specs"]["min"],
                cols_json[column_value]["specs"]["max"],
            )
            kwargs = {
                "min": min_value,
                "max": max_value,
                "id": {"type": "interactive-component", "index": id["index"]},
            }
            if aggregation_value == "Slider":
                marks = (
                    {str(elem): str(elem) for elem in df[column_value].unique()}
                    if df[column_value].nunique() < 30
                    else {}
                )
                kwargs.update({"marks": marks, "step": None, "included": False})
            interactive_component = func_name(**kwargs)

        if not input_value:
            card_title = html.H5(f"{aggregation_value} on {column_value}")
        else:
            card_title = html.H5(f"{input_value}")

        return [card_title, interactive_component, store_component]


def design_interactive(id, df):
    interactive_row = [
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
                                            label="Interactive component title",
                                            id={
                                                "type": "input-title",
                                                "index": id["index"],
                                            },
                                        ),
                                        dmc.Select(
                                            label="Select your column",
                                            id={
                                                "type": "input-dropdown-column",
                                                "index": id["index"],
                                            },
                                            data=[
                                                {"label": e, "value": e}
                                                for e in df.columns
                                            ],
                                            value=None,
                                        ),
                                        dmc.Select(
                                            label="Select your interactive component",
                                            id={
                                                "type": "input-dropdown-method",
                                                "index": id["index"],
                                            },
                                            value=None,
                                        ),
                                    ],
                                ),
                                id={
                                    "type": "input",
                                    "index": id["index"],
                                },
                            ),
                        ],
                        width="auto",
                    ),
                    dbc.Col(
                        [
                            html.H5("Resulting interactive component"),
                            html.Div(
                                dbc.Card(
                                    dbc.CardBody(
                                        # children = [
                                        #     html.Div(
                                        #         id={
                                        #             "type": "title-input-body",
                                        #             "index": id["index"],
                                        #         },
                                        #     ),
                                        #     html.Div(
                                        #         id={
                                        #             "type": "interactive-component-div",
                                        #             "index": id["index"],
                                        #         },
                                        #     ),
                                        # ],
                                        id={
                                            "type": "input-body",
                                            "index": id["index"],
                                        },
                                        style={"width": "100%"},
                                    ),
                                    style={"width": "600px"},
                                    id={
                                        "type": "card",
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
    return interactive_row


def create_stepper_interactive_button(n):
    """
    Create the stepper interactive button

    Args:
        n (_type_): _description_

    Returns:
        _type_: _description_
    """

    button = dbc.Col(
        dmc.Button(
            "Interactive",
            id={
                "type": "btn-option",
                "index": n,
                "value": "Interactive",
            },
            n_clicks=0,
            # style={
            #     "display": "inline-block",
            #     "width": "250px",
            #     "height": "100px",
            # },
            style=UNSELECTED_STYLE,
            size="xl",
            color="indigo",
            leftIcon=DashIconify(icon="bx:slider-alt", color="white"),
        )
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Interactive",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
