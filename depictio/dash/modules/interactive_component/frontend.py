# Import necessary libraries
import httpx

from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import pandas as pd
from dash_iconify import DashIconify
from depictio.dash.utils import join_deltatables, list_workflows, return_mongoid, load_deltatable_lite

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
)
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN


def register_callbacks_interactive_component(app):
    @app.callback(
        Output({"type": "input-dropdown-method", "index": MATCH}, "data"),
        [
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        ],
        prevent_initial_call=True,
    )
    def update_aggregation_options(column_value, wf_tag, dc_tag):
        """
        Callback to update aggregation dropdown options based on the selected column
        """
        cols_json = get_columns_from_data_collection(wf_tag, dc_tag)
        # print(cols_json)

        if column_value is None:
            return []

        # Get the type of the selected column
        column_type = cols_json[column_value]["type"]

        # Get the number of unique values in the selected column if it is a categorical column
        if column_type in ["object", "category"]:
            nb_unique = cols_json[column_value]["specs"]["nunique"]
        else:
            nb_unique = 0

        # Get the aggregation functions available for the selected column type
        agg_functions_tmp_methods = agg_functions[str(column_type)]["input_methods"]

        # Create a list of options for the dropdown
        options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]

        # Remove the aggregation methods that are not suitable for the selected column
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

    @app.callback(
        Output({"type": "input-body", "index": MATCH}, "children"),
        [
            Input({"type": "input-title", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "input-dropdown-method", "index": MATCH}, "id"),
            # Input("interval", "n_intervals"),
        ],
        prevent_initial_call=True,
    )
    def update_card_body(input_value, column_value, aggregation_value, wf_tag, dc_tag, id):
        """
        Callback to update card body based on the selected column and aggregation
        """
        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        # If any of the input values is None, return an empty list
        if input_value is None or column_value is None or aggregation_value is None or wf_tag is None or dc_tag is None:
            return []

        # Get the type of the selected column, the aggregation method and the function name
        cols_json = get_columns_from_data_collection(wf_tag, dc_tag)
        column_type = cols_json[column_value]["type"]
        func_name = agg_functions[column_type]["input_methods"][aggregation_value]["component"]

        # Get the workflow and data collection IDs from the tags
        workflow_id, data_collection_id = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_tag)

        # Load the delta table & get the specs
        df = load_deltatable_lite(workflow_id, data_collection_id)

        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers=headers,
        ).json()

        join_tables_for_wf = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/get_join_tables/{workflow_id}",
            headers=headers,
        )

        # Get the join tables for the selected workflow - used in store for metadata management
        if join_tables_for_wf.status_code == 200:
            join_tables_for_wf = join_tables_for_wf.json()
            if data_collection_id in join_tables_for_wf:
                join_details = join_tables_for_wf[data_collection_id]
                dc_specs["config"]["dc_specific_properties"]["join"] = join_details

        # Common Store Component
        store_component = dcc.Store(
            id={"type": "stored-metadata-component", "index": id["index"]},
            data={
                "component_type": "interactive_component",
                "interactive_component_type": aggregation_value,
                "index": id["index"],
                "wf_id": workflow_id,
                "dc_id": data_collection_id,
                "dc_config": dc_specs["config"],
                "column_value": column_value,
                "type": column_type,
            },
            storage_type="memory",
        )

        # Handling different aggregation values

        ## Categorical data

        # If the aggregation value is Select, MultiSelect or SegmentedControl
        if aggregation_value in ["Select", "MultiSelect", "SegmentedControl"]:
            data = sorted(df[column_value].dropna().unique())
            interactive_component = func_name(data=data, id={"type": "interactive-component", "index": id["index"]})

            # If the aggregation value is MultiSelect, make the component searchable and clearable
            if aggregation_value == "MultiSelect":
                kwargs = {"searchable": True, "clearable": True, "clearSearchOnChange": False}
                interactive_component = func_name(
                    data=data,
                    id={"type": "interactive-component", "index": id["index"]},
                    **kwargs,
                )

        # If the aggregation value is TextInput
        elif aggregation_value == "TextInput":
            interactive_component = func_name(
                placeholder="Your selected value",
                id={"type": "interactive-component", "index": id["index"]},
            )

        ## Numerical data

        # If the aggregation value is Slider or RangeSlider
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
            # If the number of unique values is less than 30, use the unique values as marks
            if aggregation_value == "Slider":
                marks = {str(elem): str(elem) for elem in df[column_value].unique()} if df[column_value].nunique() < 30 else {}
                kwargs.update({"marks": marks, "step": None, "included": False})
            interactive_component = func_name(**kwargs)

        # If no title is provided, use the aggregation value on the selected column
        if not input_value:
            card_title = html.H5(f"{aggregation_value} on {column_value}")
        else:
            card_title = html.H5(f"{input_value}")

        return [card_title, interactive_component, store_component]


def design_interactive(id, df):
    left_column = dbc.Col(
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
                            data=[{"label": e, "value": e} for e in df.columns],
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
    )
    right_column = dbc.Col(
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
    )

    interactive_row = [
        dmc.Center(dbc.Row([left_column, right_column])),
    ]
    return interactive_row


def create_stepper_interactive_button(n, disabled=False):
    """
    Create the stepper interactive button
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
            style=UNSELECTED_STYLE,
            size="xl",
            color="indigo",
            leftIcon=DashIconify(icon="bx:slider-alt", color="white"),
            disabled=disabled,
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
