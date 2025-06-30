# Import necessary libraries
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import httpx
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger

# Depictio imports
from depictio.dash.modules.interactive_component.utils import (
    agg_functions,
    build_interactive,
    build_interactive_frame,
)
from depictio.dash.utils import (
    UNSELECTED_STYLE,
    get_columns_from_data_collection,
    get_component_data,
)


def register_callbacks_interactive_component(app):
    @app.callback(
        Output({"type": "input-dropdown-method", "index": MATCH}, "data"),
        [
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "input-dropdown-method", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
        ],
        prevent_initial_call=True,
    )
    def update_aggregation_options(column_value, wf_tag, dc_tag, id, local_data, pathname):
        """
        Callback to update aggregation dropdown options based on the selected column
        """
        if not local_data:
            return []

        TOKEN = local_data["access_token"]

        cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
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
        Output({"type": "btn-done-edit", "index": MATCH}, "disabled", allow_duplicate=True),
        [
            Input({"type": "input-title", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
        ],
        prevent_initial_call=True,
    )
    def disable_done_button(column_name, column_value, aggregation):
        """
        Callback to disable the done button if any of the inputs are None
        """
        if column_value and aggregation:
            return False
        return True

    @app.callback(
        Output({"type": "input-body", "index": MATCH}, "children"),
        Output({"type": "interactive-description", "index": MATCH}, "children"),
        Output({"type": "columns-description", "index": MATCH}, "children"),
        [
            Input({"type": "input-title", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "input-dropdown-method", "index": MATCH}, "id"),
            State("current-edit-parent-index", "data"),  # Retrieve parent_index
            State("local-store", "data"),
            State("url", "pathname"),
            # Input("interval", "n_intervals"),
        ],
        # prevent_initial_call=True,
    )
    def update_card_body(
        input_value,
        column_value,
        aggregation_value,
        workflow_id,
        data_collection_id,
        id,
        parent_index,
        local_data,
        pathname,
    ):
        """
        Callback to update card body based on the selected column and aggregation
        """

        if not local_data:
            return []

        TOKEN = local_data["access_token"]

        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        dashboard_id = pathname.split("/")[-1]
        # input_id = id["index"]

        component_data = get_component_data(
            input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
        )

        # Check if value was already assigned
        value = None

        # Get the columns from the selected data collection
        cols_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)
        logger.info(f"cols_json: {cols_json}")

        from dash import dash_table

        data_columns_df = [
            {"column": c, "description": cols_json[c]["description"]}
            for c in cols_json
            if cols_json[c]["description"] is not None
        ]

        columns_description_df = dash_table.DataTable(
            # id={
            #     "type": "columns-description",
            #     "index": input_id,
            # },
            columns=[
                {"name": "Column", "id": "column"},
                {"name": "Description", "id": "description"},
            ],
            data=data_columns_df,
            # Small font size, helvetica, no border, center text
            style_cell={
                "fontSize": 12,
                "fontFamily": "Helvetica",
                "border": "0px",
                "textAlign": "center",
            },
            style_header={"fontWeight": "bold"},
        )

        # If any of the input values are None, return an empty list
        if (
            input_value is None
            or column_value is None
            or aggregation_value is None
            or workflow_id is None
            or data_collection_id is None
        ):
            if not component_data:
                return ([], None, columns_description_df)
            else:
                input_value = component_data.get("title", "")
                column_value = component_data["column_name"]
                aggregation_value = component_data["interactive_component_type"]
                value = component_data.get("value", None)
                logger.info(f"component_data: {component_data}")
                logger.info(f"input_value: {input_value}")
                logger.info(f"column_value: {column_value}")
                logger.info(f"aggregation_value: {aggregation_value}")
                logger.info(f"value: {value}")

        # Get the type of the selected column
        column_type = cols_json[column_value]["type"]

        interactive_description = html.Div(
            children=[
                html.Hr(),
                dmc.Tooltip(
                    children=dmc.Stack(
                        [
                            dmc.Badge(
                                children="Interactive component description",
                                leftSection=DashIconify(
                                    icon="mdi:information", color="grey", width=20
                                ),
                                color="gray",
                                radius="lg",
                            ),
                        ]
                    ),
                    label=agg_functions[str(column_type)]["input_methods"][aggregation_value][
                        "description"
                    ],
                    multiline=True,
                    width=300,
                    transition="pop",
                    transitionDuration=300,
                    justify="flex-end",
                    withArrow=True,
                    openDelay=500,
                    closeDelay=500,
                    color="gray",
                ),
            ]
        )

        # Get the type of the selected column, the aggregation method and the function name
        # cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
        # logger.info(f"Wf tag : {wf_tag}")
        # logger.info(f"Dc tag : {dc_tag}")
        logger.info(f"Cols json : {cols_json}")
        column_type = cols_json[column_value]["type"]

        # Get the workflow and data collection IDs from the tags
        # workflow_id, data_collection_id = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_tag, TOKEN=TOKEN)

        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
            headers=headers,
        ).json()
        logger.info(f"dc_specs : {dc_specs}")

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
            "access_token": TOKEN,
            "stepper": True,
            "parent_index": parent_index,
        }

        if value:
            interactive_kwargs["value"] = value

        new_interactive_component = build_interactive(**interactive_kwargs)

        return (
            new_interactive_component,
            interactive_description,
            columns_description_df,
        )


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
                        html.Div(
                            id={
                                "type": "interactive-description",
                                "index": id["index"],
                            },
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
        dmc.Center(
            dmc.Stack(
                [
                    dbc.Row([left_column, right_column]),
                    html.Hr(),
                    # dmc.Space(h=5),
                    dbc.Row(
                        dmc.Stack(
                            [
                                dmc.Title("Data Collection - Columns description", order=5),
                                html.Div(
                                    id={
                                        "type": "columns-description",
                                        "index": id["index"],
                                    }
                                ),
                            ]
                        )
                    ),
                ]
            ),
        ),
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
