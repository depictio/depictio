# Import necessary libraries
import dash_mantine_components as dmc
import httpx
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import get_component_color, get_dmc_button_color, is_enabled
from depictio.dash.modules.card_component.utils import agg_functions, build_card, build_card_frame

# Depictio imports
from depictio.dash.utils import (
    UNSELECTED_STYLE,
    get_columns_from_data_collection,
    get_component_data,
    load_depictio_data_mongo,
)


def register_callbacks_card_component(app):
    @app.callback(
        Output({"type": "card-dropdown-aggregation", "index": MATCH}, "data"),
        [
            Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            # State("local-store-components-metadata", "data"),
            State({"type": "card-dropdown-column", "index": MATCH}, "id"),
            State("current-edit-parent-index", "data"),  # Add parent index for edit mode
            State("local-store", "data"),
            State("url", "pathname"),
        ],
        prevent_initial_call=True,
    )
    # def update_aggregation_options(column_name, wf_dc_store, component_id, local_data, pathname):
    def update_aggregation_options(
        column_name, wf_tag, dc_tag, component_id, parent_index, local_data, pathname
    ):
        """
        Callback to update aggregation dropdown options based on the selected column
        """
        logger.info("=== CARD AGGREGATION OPTIONS CALLBACK START ===")
        logger.info(f"column_name: {column_name}")
        logger.info(f"wf_tag: {wf_tag}")
        logger.info(f"dc_tag: {dc_tag}")
        logger.info(f"component_id: {component_id}")
        logger.info(f"parent_index: {parent_index}")
        logger.info(f"local_data available: {local_data is not None}")
        logger.info(f"pathname: {pathname}")

        if not local_data:
            logger.error("No local_data available!")
            return []

        TOKEN = local_data["access_token"]

        # In edit mode, we might need to get workflow/dc IDs from component data
        if parent_index is not None and (not wf_tag or not dc_tag):
            logger.info(
                f"Edit mode detected - fetching component data for parent_index: {parent_index}"
            )
            dashboard_id = pathname.split("/")[-1]
            component_data = get_component_data(
                input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
            )
            if component_data:
                wf_tag = component_data.get("wf_id")
                dc_tag = component_data.get("dc_id")
                logger.info(f"Retrieved from component_data - wf_tag: {wf_tag}, dc_tag: {dc_tag}")

        index = str(component_id["index"])
        logger.info(f"index: {index}")
        logger.info(f"Final wf_tag: {wf_tag}")
        logger.info(f"Final dc_tag: {dc_tag}")

        # If any essential parameters are None, return empty list
        if not wf_tag or not dc_tag:
            logger.error(
                f"Missing essential workflow/dc parameters - wf_tag: {wf_tag}, dc_tag: {dc_tag}"
            )
            return []

        # If column_name is None, return empty list (but still log the attempt)
        if not column_name:
            logger.info(
                "Column name is None - returning empty list (this is normal on initial load)"
            )
            return []

        # Get the columns from the selected data collection
        logger.info("Fetching columns from data collection...")
        cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
        logger.info(f"cols_json keys: {list(cols_json.keys()) if cols_json else 'None'}")

        # Check if cols_json is valid and contains the column
        if not cols_json:
            logger.error("cols_json is empty or None!")
            return []

        if column_name not in cols_json:
            logger.error(f"column_name '{column_name}' not found in cols_json!")
            logger.error(f"Available columns: {list(cols_json.keys())}")
            return []

        if "type" not in cols_json[column_name]:
            logger.error(f"'type' field missing for column '{column_name}'")
            logger.error(f"Available fields: {list(cols_json[column_name].keys())}")
            return []

        # Get the type of the selected column
        column_type = cols_json[column_name]["type"]
        logger.info(f"column_type: {column_type}")

        # Get the aggregation functions available for the selected column type
        if str(column_type) not in agg_functions:
            logger.error(f"Column type '{column_type}' not found in agg_functions!")
            logger.error(f"Available types: {list(agg_functions.keys())}")
            return []

        agg_functions_tmp_methods = agg_functions[str(column_type)]["card_methods"]
        logger.info(f"agg_functions_tmp_methods: {agg_functions_tmp_methods}")

        # Create a list of options for the dropdown
        options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]
        logger.info(f"Final options to return: {options}")
        logger.info("=== CARD AGGREGATION OPTIONS CALLBACK END ===")

        return options

    # Callback to reset aggregation dropdown value based on the selected column
    @app.callback(
        Output({"type": "card-dropdown-aggregation", "index": MATCH}, "value"),
        Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def reset_aggregation_value(column_name):
        return None

    @app.callback(
        Output({"type": "btn-done-edit", "index": MATCH}, "disabled", allow_duplicate=True),
        [
            Input({"type": "card-input", "index": MATCH}, "value"),
            Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "card-dropdown-aggregation", "index": MATCH}, "value"),
        ],
        prevent_initial_call=True,
    )
    def disable_done_button(title, column_name, aggregation):
        if column_name and aggregation:
            return False
        return True

    # Callback to update card body based on the selected column and aggregation
    @app.callback(
        Output({"type": "card-body", "index": MATCH}, "children"),
        Output({"type": "aggregation-description", "index": MATCH}, "children"),
        Output({"type": "card-columns-description", "index": MATCH}, "children"),
        [
            Input({"type": "card-input", "index": MATCH}, "value"),
            Input({"type": "card-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "card-dropdown-aggregation", "index": MATCH}, "value"),
            # Input({"type": "card-color-picker", "index": MATCH}, "value"),  # Disabled color picker
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            # State("local-store-components-metadata", "data"),
            State("current-edit-parent-index", "data"),  # Retrieve parent_index
            State({"type": "card-dropdown-column", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
        ],
        # prevent_initial_call=True,
    )
    # def design_card_body(input_value, column_name, aggregation_value, wf_dc_store, id, local_data, pathname):
    def design_card_body(
        input_value,
        column_name,
        aggregation_value,
        # color_value,  # Disabled color picker
        wf_id,
        dc_id,
        parent_index,
        id,
        local_data,
        pathname,
    ):
        """
        Callback to update card body based on the selected column and aggregation
        """

        input_id = str(id["index"])

        logger.info(f"input_id: {input_id}")
        logger.info(f"pathname: {pathname}")

        logger.info(f"input_value: {input_value}")
        logger.info(f"column_name: {column_name}")
        logger.info(f"aggregation_value: {aggregation_value}")

        color_value = None  # Default value since color picker is disabled

        if not local_data:
            return ([], None)

        TOKEN = local_data["access_token"]
        logger.info(f"TOKEN: {TOKEN}")

        dashboard_id = pathname.split("/")[-1]
        logger.info(f"dashboard_id: {dashboard_id}")

        component_data = get_component_data(
            input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
        )

        if not component_data:
            if not wf_id or not dc_id:
                # if not wf_dc_store:
                return ([], None)

        else:
            wf_id = component_data["wf_id"]
            dc_id = component_data["dc_id"]
            logger.info(f"wf_tag: {wf_id}")
            logger.info(f"dc_tag: {dc_id}")

        logger.info(f"component_data: {component_data}")

        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        # Get the columns from the selected data collection
        cols_json = get_columns_from_data_collection(wf_id, dc_id, TOKEN)
        logger.info(f"cols_json: {cols_json}")

        data_columns_df = [
            {"column": c, "description": cols_json[c]["description"]}
            for c in cols_json
            if cols_json[c]["description"] is not None
        ]

        # Create DMC Table instead of DataTable for better theming
        table_rows = []
        for row in data_columns_df:
            table_rows.append(
                dmc.TableTr(
                    [
                        dmc.TableTd(
                            row["column"],
                            style={"textAlign": "center", "fontSize": "11px", "maxWidth": "150px"},
                        ),
                        dmc.TableTd(
                            row["description"],
                            style={"textAlign": "center", "fontSize": "11px", "maxWidth": "150px"},
                        ),
                    ]
                )
            )

        columns_description_df = dmc.Table(
            [
                dmc.TableThead(
                    [
                        dmc.TableTr(
                            [
                                dmc.TableTh(
                                    "Column",
                                    style={
                                        "textAlign": "center",
                                        "fontSize": "11px",
                                        "fontWeight": "bold",
                                    },
                                ),
                                dmc.TableTh(
                                    "Description",
                                    style={
                                        "textAlign": "center",
                                        "fontSize": "11px",
                                        "fontWeight": "bold",
                                    },
                                ),
                            ]
                        )
                    ]
                ),
                dmc.TableTbody(table_rows),
            ],
            striped="odd",
            withTableBorder=True,
        )

        # If any of the input values are None, return an empty list
        if column_name is None or aggregation_value is None or wf_id is None or dc_id is None:
            if not component_data:
                return ([], None, columns_description_df)
            else:
                column_name = component_data["column_name"]
                aggregation_value = component_data["aggregation"]
                input_value = component_data["title"]
                logger.info("COMPOENNT DATA")
                logger.info(f"column_name: {column_name}")
                logger.info(f"aggregation_value: {aggregation_value}")
                logger.info(f"input_value: {input_value}")

        # Get the type of the selected column
        column_type = cols_json[column_name]["type"]

        aggregation_description = html.Div(
            children=[
                html.Hr(),
                dmc.Tooltip(
                    children=dmc.Badge(
                        children="Aggregation description",
                        leftSection=DashIconify(icon="mdi:information", color="white", width=20),
                        color="gray",
                        radius="lg",
                    ),
                    label=agg_functions[str(column_type)]["card_methods"][aggregation_value][
                        "description"
                    ],
                    multiline=True,
                    w=300,
                    # transition="pop",
                    # transitionDuration=300,
                    transitionProps={
                        "name": "pop",
                        "duration": 300,
                    },
                    withinPortal=False,
                    # justify="flex-end",
                    withArrow=True,
                    openDelay=500,
                    closeDelay=500,
                    color="gray",
                ),
            ]
        )

        # Get the workflow and data collection ids from the tags selected
        # workflow_id, data_collection_id = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_tag, TOKEN=TOKEN)

        # stored_metadata_interactive = []
        # if stored_metadata:
        #     stored_metadata_interactive = [e for e in stored_metadata if e["component_type"] == "interactive" and e["wf_id"] == workflow_id and e["dc_id"] == data_collection_id]

        if dashboard_id:
            dashboard_data = load_depictio_data_mongo(dashboard_id, TOKEN=TOKEN)
            logger.info(f"dashboard_data: {dashboard_data}")
            relevant_metadata = [
                m
                for m in dashboard_data["stored_metadata"]
                if m["wf_id"] == wf_id and m["component_type"] == "interactive"
            ]
            logger.info(f"BUILD CARD - relevant_metadata: {relevant_metadata}")

        # Get the data collection specs
        # Handle joined data collection IDs
        if isinstance(dc_id, str) and "--" in dc_id:
            # For joined data collections, create synthetic specs
            dc_specs = {
                "config": {"type": "table", "metatype": "joined"},
                "data_collection_tag": f"Joined data collection ({dc_id})",
                "description": "Virtual joined data collection",
                "_id": dc_id,
            }
        else:
            # Regular data collection - fetch from API
            dc_specs = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
                headers=headers,
            ).json()

        # Get the type of the selected column and the value for the selected aggregation
        column_type = cols_json[column_name]["type"]
        # v = cols_json[column_name]["specs"][aggregation_value]

        dashboard_data

        card_kwargs = {
            "index": id["index"],
            "title": input_value,
            "wf_id": wf_id,
            "dc_id": dc_id,
            "dc_config": dc_specs["config"],
            "column_name": column_name,
            "column_type": column_type,
            "aggregation": aggregation_value,
            # "value": v,
            "access_token": TOKEN,
            "stepper": True,  # Show border during editing
            "build_frame": False,  # Don't build frame - return just the content for the card-body container
            "color": color_value,
            "cols_json": cols_json,  # Pass cols_json for reference values
        }

        if relevant_metadata:
            card_kwargs["dashboard_metadata"] = relevant_metadata

        logger.info(f"card_kwargs: {card_kwargs}")

        if parent_index:
            card_kwargs["parent_index"] = parent_index

        new_card_body = build_card(**card_kwargs)

        return new_card_body, aggregation_description, columns_description_df


def design_card(id, df):
    left_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title("Card edit menu", order=5, style={"textAlign": "center"}),
                dmc.Card(
                    dmc.CardSection(
                        dmc.Stack(
                            [
                                # Input for the card title
                                dmc.TextInput(
                                    label="Card title",
                                    id={
                                        "type": "card-input",
                                        "index": id["index"],
                                    },
                                    value="",
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
                                # dmc.Stack(  # Disabled color picker
                                #     [
                                #         dmc.Text("Color customization", size="sm", fw="bold"),
                                #         dmc.ColorInput(
                                #             label="Pick any color from the page",
                                #             w=250,
                                #             id={
                                #                 "type": "card-color-picker",
                                #                 "index": id["index"],
                                #             },
                                #             value="var(--app-text-color, #000000)",
                                #             format="hex",
                                #             # leftSection=DashIconify(icon="cil:paint"),
                                #             swatches=[
                                #                 colors["purple"],  # Depictio brand colors
                                #                 colors["violet"],
                                #                 colors["blue"],
                                #                 colors["teal"],
                                #                 colors["green"],
                                #                 colors["yellow"],
                                #                 colors["orange"],
                                #                 colors["pink"],
                                #                 colors["red"],
                                #                 colors["black"],
                                #             ],
                                #         ),
                                #     ],
                                #     gap="xs",
                                # ),
                                html.Div(
                                    id={
                                        "type": "aggregation-description",
                                        "index": id["index"],
                                    },
                                ),
                            ],
                            gap="sm",
                        ),
                        id={
                            "type": "card",
                            "index": id["index"],
                        },
                        style={"padding": "1rem"},
                    ),
                    withBorder=True,
                    shadow="sm",
                    style={"width": "100%"},
                ),
            ],
            align="flex-end",  # Align to right (horizontal)
            justify="center",  # Center vertically
            gap="md",
            style={"height": "100%"},
        ),
        span="auto",
        style={
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "flex-end",
        },  # Align to right
    )
    right_column = dmc.GridCol(
        dmc.Stack(
            [
                dmc.Title("Resulting card", order=5, style={"textAlign": "center"}),
                # Add a Paper wrapper just for visual preview in stepper mode
                dmc.Paper(
                    html.Div(
                        build_card_frame(
                            index=id["index"], show_border=False
                        ),  # No border on actual component
                        id={
                            "type": "component-container",
                            "index": id["index"],
                        },
                    ),
                    withBorder=True,  # Show border on preview container
                    radius="md",
                    p="md",  # Add some padding for the preview
                    style={"width": "100%"},
                ),
            ],
            align="flex-start",  # Align to left (horizontal)
            justify="center",  # Center vertically
            gap="md",
            style={"height": "100%"},
        ),
        span="auto",
        style={
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "flex-start",
        },  # Align to left
    )
    # Arrow between columns
    arrow_column = dmc.GridCol(
        dmc.Stack(
            [
                html.Div(style={"height": "50px"}),  # Spacer to align with content
                dmc.Center(
                    DashIconify(
                        icon="mdi:arrow-right-bold",
                        width=40,
                        height=40,
                        color="#666",
                    ),
                ),
            ],
            align="start",
            justify="start",
            style={"height": "100%"},
        ),
        span="content",
        style={"display": "flex", "alignItems": "center", "justifyContent": "center"},
    )

    # Main layout with components
    main_layout = dmc.Grid(
        [left_column, arrow_column, right_column],
        justify="center",
        align="center",
        gutter="md",
        style={"height": "100%", "minHeight": "300px"},
    )

    # Bottom section with column descriptions
    bottom_section = dmc.Stack(
        [
            dmc.Title("Data Collection - Columns description", order=5, ta="center"),
            html.Div(
                id={
                    "type": "card-columns-description",
                    "index": id["index"],
                }
            ),
        ],
        gap="md",
        style={"marginTop": "2rem"},
    )

    card_row = [
        dmc.Stack(
            [main_layout, html.Hr(), bottom_section],
            gap="lg",
        ),
    ]
    return card_row


def create_stepper_card_button(n, disabled=None):
    """
    Create the stepper card button

    Args:
        n (_type_): _description_
        disabled (bool, optional): Override enabled state. If None, uses metadata.
    """

    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("card")

    color = get_dmc_button_color("card")
    hex_color = get_component_color("card")

    # Create the card button
    button = dmc.Button(
        "Card",
        id={
            "type": "btn-option",
            "index": n,
            "value": "Card",
        },
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=color,
        leftSection=DashIconify(icon="formkit:number", color=hex_color),
        disabled=disabled,
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
