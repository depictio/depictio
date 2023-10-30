# Import necessary libraries
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import pandas as pd
from dash_iconify import DashIconify


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
    load_gridfs_file,
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
        print(cols_json)

        if column_value is None:
            return []

        column_type = cols_json["columns_specs"][column_value]["type"]

        # Get the type of the selected column
        # column_type = df[column_value].dtype
        # print(column_value, column_type, type(column_type))

        if column_type in ["object", "category"]:
            nb_unique = cols_json["columns_specs"][column_value]["nunique"]
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
        Output({"type": "input-body", "index": MATCH}, "children"),
        [
            Input({"type": "input-title", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
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

        df = load_gridfs_file(wf_id, dc_id)
        cols_json = get_columns_from_data_collection(wf_id, dc_id)

        # Get the type of the selected column
        # column_type = str(df[column_value].dtype)
        column_type = cols_json["columns_specs"][column_value]["type"]

        # Get the pandas function for the selected aggregation
        func_name = agg_functions[column_type]["input_methods"][aggregation_value][
            "component"
        ]
        # print(func_name)

        # if callable(func_name):
        #     # If the function is a lambda function
        #     v = func_name(df[column_value])
        # else:
        #     # If the function is a pandas function
        #     v = getattr(df[column_value], func_name)()
        #     print(v, type(v))
        #     if type(v) is pd.core.series.Series and func_name != "mode":
        #         v = v.iloc[0]
        #     elif type(v) is pd.core.series.Series and func_name == "mode":
        #         if v.shape[0] == df[column_value].nunique():
        #             v = "All values are represented equally"
        #         else:
        #             v = v.iloc[0]

        # if type(v) is np.float64:
        #     v = round(v, 2)
        # v = "{:,.2f}".format(round(v, 2))
        # v = "{:,.2f}".format(round(v, 2)).replace(",", " ")

        card_title = html.H5(f"{input_value}")

        # TODO: solve this in a better way
        if aggregation_value in ["Select", "MultiSelect", "SegmentedControl"]:
            # data = cols_json["columns_specs"][column_value]["unique"]
            data = df[column_value].unique()

            new_card_body = [card_title, func_name(data=data)]
            # print(new_card_body)

            return new_card_body
        elif aggregation_value in ["TextInput"]:
            new_card_body = [
                card_title,
                func_name(placeholder="Your selected value"),
            ]
            # print(new_card_body)

            return new_card_body

        elif aggregation_value in ["Slider", "RangeSlider"]:
            min_value = cols_json["columns_specs"][column_value]["min"]
            max_value = cols_json["columns_specs"][column_value]["max"]

            # min_value = df[column_value].min()
            # max_value = df[column_value].max()
            kwargs = dict()
            if aggregation_value == "Slider":
                marks = dict()

                # TODO: solve this in a better way
                # if cols_json["columns_specs"][column_value]["nunique"] < 50:
                if df[column_value].nunique() < 30:
                    marks = {str(elem): str(elem) for elem in df[column_value].unique()}
                else:
                    bins = pd.cut(df[column_value], bins=10, precision=2)

                    marks = {
                        str(elem): str(elem)
                        for elem in bins.value_counts().index.categories.values
                    }
                step = None
                included = False
                kwargs = dict(marks=marks, step=step, included=included)

            new_card_body = [
                card_title,
                func_name(min=min_value, max=max_value, **kwargs),
            ]
            # print(new_card_body)
            return new_card_body


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
