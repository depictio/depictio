# Import necessary libraries
from dash import html, dcc, Input, Output, State, MATCH
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx

# Depictio imports
from depictio.dash.utils import return_mongoid
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN

from depictio.dash.modules.card_component.utils import (
    agg_functions,
)
from depictio.dash.utils import (
    UNSELECTED_STYLE,
    get_columns_from_data_collection,
)


def register_callbacks_card_component(app):
    @app.callback(
        Output({"type": "card-dropdown-aggregation", "index": MATCH}, "data"),
        [
            Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        ],
        prevent_initial_call=True,
    )
    def update_aggregation_options(column_value, wf_tag, dc_tag):
        """
        Callback to update aggregation dropdown options based on the selected column
        """
        # Get the columns from the selected data collection
        cols_json = get_columns_from_data_collection(wf_tag, dc_tag)

        if column_value is None:
            return []

        # Get the type of the selected column
        column_type = cols_json[column_value]["type"]

        # Get the aggregation functions available for the selected column type
        agg_functions_tmp_methods = agg_functions[str(column_type)]["card_methods"]

        # Create a list of options for the dropdown
        options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]

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
    def design_card_body(input_value, column_value, aggregation_value, wf_tag, dc_tag, id):
        """
        Callback to update card body based on the selected column and aggregation
        """

        # FIXME: This is a temporary solution to get the token
        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        # If any of the input values are None, return an empty list
        if input_value is None or column_value is None or aggregation_value is None or wf_tag is None or dc_tag is None:
            return []

        # Get the columns from the selected data collection
        cols_json = get_columns_from_data_collection(wf_tag, dc_tag)

        # Get the workflow and data collection ids from the tags selected
        workflow_id, data_collection_id = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_tag)

        # Get the data collection specs
        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            headers=headers,
        ).json()

        # Get the join tables for the selected workflow - used in store for metadata management
        join_tables_for_wf = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/workflows/get_join_tables/{workflow_id}",
            headers=headers,
        )

        # If the request is successful, get the join details for the selected data collection
        if join_tables_for_wf.status_code == 200:
            join_tables_for_wf = join_tables_for_wf.json()
            if data_collection_id in join_tables_for_wf:
                join_details = join_tables_for_wf[data_collection_id]
                dc_specs["config"]["join"] = join_details

        # Get the type of the selected column and the value for the selected aggregation
        column_type = cols_json[column_value]["type"]
        v = cols_json[column_value]["specs"][aggregation_value]

        try:
            v = round(float(v), 2)
        except:
            pass

        # Metadata management - Create a store component to store the metadata of the card
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

        # Create the card body - default title is the aggregation value on the selected column
        if not input_value:
            card_title = html.H5(f"{aggregation_value} on {column_value}")
        else:
            card_title = html.H5(f"{input_value}")

        # Create the card body
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
    left_column = dbc.Col(
        [
            html.H5("Card edit menu"),
            dbc.Card(
                dbc.CardBody(
                    [
                        # Input for the card title
                        dmc.TextInput(
                            label="Card title",
                            id={
                                "type": "card-input",
                                "index": id["index"],
                            },
                        ),
                        # Dropdown for the column selection
                        dmc.Select(
                            label="Select your column",
                            id={
                                "type": "card-dropdown-column",
                                "index": id["index"],
                            },
                            data=[{"label": e, "value": e} for e in df.columns],
                            value=None,
                        ),
                        # Dropdown for the aggregation method selection
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
    )
    right_column = dbc.Col(
        [
            html.H5("Resulting card"),
            html.Div(
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
                )
            ),
        ],
        width="auto",
    )
    row = [
        dmc.Center(dbc.Row([left_column, right_column])),
    ]
    return row


def create_stepper_card_button(n, disabled=False):
    """
    Create the stepper card button
    """

    # Create the card button
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
            disabled=disabled,
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
