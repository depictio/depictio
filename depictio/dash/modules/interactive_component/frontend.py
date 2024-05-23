# Import necessary libraries
import httpx

from dash import html, dcc, Input, Output, State, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
from depictio.dash.utils import return_mongoid

# Depictio imports
from depictio.dash.modules.interactive_component.utils import (
    agg_functions,
    build_interactive,
    build_interactive_frame,
)
from depictio.dash.utils import (
    UNSELECTED_STYLE,
    get_columns_from_data_collection,
)
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN, logger


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
        logger.info(f"Wf tag : {wf_tag}")
        logger.info(f"Dc tag : {dc_tag}")
        logger.info(f"Cols json : {cols_json}")
        column_type = cols_json[column_value]["type"]

        # Get the workflow and data collection IDs from the tags
        workflow_id, data_collection_id = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_tag)

        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers=headers,
        ).json()

        # join_tables_for_wf = httpx.get(
        #     f"{API_BASE_URL}/depictio/api/v1/datacollections/get_join_tables/{workflow_id}",
        #     headers=headers,
        # )

        # # Get the join tables for the selected workflow - used in store for metadata management
        # if join_tables_for_wf.status_code == 200:
        #     join_tables_for_wf = join_tables_for_wf.json()
        #     if data_collection_id in join_tables_for_wf:
        #         join_details = join_tables_for_wf[data_collection_id]
        #         dc_specs["config"]["join"] = join_details

        interactive_kwargs = {
            "index": id["index"],
            "title": input_value,
            "wf_id": workflow_id,
            "dc_id": data_collection_id,
            "dc_config": dc_specs["config"],
            "column_name": column_value,
            "column_type": column_type,
            "interactive_component_type": aggregation_value,
            "cols_json": cols_json,
        }
        new_interactive_component = build_interactive(**interactive_kwargs)

        return new_interactive_component


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
                build_interactive_frame(index=id["index"]),
                # dbc.Card(
                #     dbc.CardBody(
                #         id={
                #             "type": "input-body",
                #             "index": id["index"],
                #         },
                #         style={"width": "100%"},
                #     ),
                #     style={"width": "600px"},
                #     id={
                #         "type": "interactive-component",
                #         "index": id["index"],
                #     },
                # ),
                id={
                    "type": "component-container",
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
