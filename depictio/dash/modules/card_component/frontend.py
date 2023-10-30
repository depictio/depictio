# Import necessary libraries
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc


# Depictio imports
from depictio.dash.modules.card_component.utils import (
    agg_functions,
)
from depictio.dash.utils import get_columns_from_data_collection

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
        print("update_aggregation_options", column_value)
        print("\n\n")

        cols_json = get_columns_from_data_collection(wf_id, dc_id)

        if column_value is None:
            return []

        # Get the type of the selected column
        column_type = cols_json["columns_specs"][column_value]["type"]
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
            # Input("interval", "n_intervals"),
        ],
        prevent_initial_call=True,
    )
    def update_card_body(input_value, column_value, aggregation_value, wf_id, dc_id):
        if (
            input_value is None
            or column_value is None
            or aggregation_value is None
            or wf_id is None
            or dc_id is None
        ):
            return []

        cols_json = get_columns_from_data_collection(wf_id, dc_id)

        # Get the type of the selected column
        column_type = cols_json["columns_specs"][column_value]["type"]

        # Get the pandas function for the selected aggregation
        func_name = agg_functions[column_type]["card_methods"][aggregation_value][
            "pandas"
        ]
        print(column_value, aggregation_value, func_name)

        v = cols_json["columns_specs"][column_value][aggregation_value]

        # if callable(func_name):
        #     # If the function is a lambda function
        #     v = func_name(df[column_value])
        # else:
        #     # If the function is a pandas function
        #     v = getattr(df[column_value], func_name)()
        #     # print(v, type(v))
        #     if type(v) is pd.core.series.Series and func_name != "mode":
        #         v = v.iloc[0]
        #     elif type(v) is pd.core.series.Series and func_name == "mode":
        #         if v.shape[0] == df[column_value].nunique():
        #             v = "All values are represented equally"
        #         else:
        #             v = v.iloc[0]

        try:
            v = round(float(v), 2)
        except:
            pass
        # if type(v) is np.float64:
        # v = "{:,.2f}".format(round(v, 2))
        # v = "{:,.2f}".format(round(v, 2)).replace(",", " ")

        new_card_body = [html.H5(f"{input_value}"), html.P(f"{v}")]

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
