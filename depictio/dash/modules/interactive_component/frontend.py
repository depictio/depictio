# Import necessary libraries
import dash_mantine_components as dmc
import httpx
from dash_iconify import DashIconify

from dash import MATCH, Input, Output, State, dcc, html
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger

# Depictio imports
from depictio.dash.component_metadata import get_dmc_button_color, is_enabled
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
    # Debug callback to track column selection changes
    @app.callback(
        Output({"type": "debug-interactive-log", "index": MATCH}, "children"),
        [Input({"type": "input-dropdown-column", "index": MATCH}, "value")],
        prevent_initial_call=False,
    )
    def debug_column_selection(column_value):
        logger.info(f"=== DEBUG: Column selection changed to: {column_value} ===")
        return f"Debug: Column = {column_value}"

    @app.callback(
        Output({"type": "input-dropdown-method", "index": MATCH}, "data"),
        [
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "input-dropdown-method", "index": MATCH}, "id"),
            State("current-edit-parent-index", "data"),  # Add parent index for edit mode
            State("local-store", "data"),
            State("url", "pathname"),
        ],
        prevent_initial_call=False,
    )
    def update_aggregation_options(
        column_value, workflow_id, data_collection_id, id, parent_index, local_data, pathname
    ):
        """
        Callback to update aggregation dropdown options based on the selected column
        """
        logger.info("=== UPDATE AGGREGATION OPTIONS CALLBACK START ===")
        logger.info(f"column_value: {column_value}")
        logger.info(f"workflow_id: {workflow_id}")
        logger.info(f"data_collection_id: {data_collection_id}")
        logger.info(f"id: {id}")
        logger.info(f"parent_index: {parent_index}")
        logger.info(f"local_data available: {local_data is not None}")
        logger.info(f"pathname: {pathname}")

        if not local_data:
            logger.error("No local_data available!")
            return []

        TOKEN = local_data["access_token"]

        # In edit mode, we might need to get workflow/dc IDs from component data
        if parent_index is not None and (not workflow_id or not data_collection_id):
            logger.info(
                f"Edit mode detected - fetching component data for parent_index: {parent_index}"
            )
            dashboard_id = pathname.split("/")[-1]
            component_data = get_component_data(
                input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
            )
            if component_data:
                workflow_id = component_data.get("wf_id")
                data_collection_id = component_data.get("dc_id")
                logger.info(
                    f"Retrieved from component_data - workflow_id: {workflow_id}, data_collection_id: {data_collection_id}"
                )

        # If any essential parameters are None, return empty list but allow case where column_value is None
        if not workflow_id or not data_collection_id:
            logger.error(
                f"Missing essential workflow/dc parameters - workflow_id: {workflow_id}, data_collection_id: {data_collection_id}"
            )
            return []

        # If column_value is None, return empty list (but still log the attempt)
        if not column_value:
            logger.info(
                "Column value is None - returning empty list (this is normal on initial load)"
            )
            return []

        logger.info("Fetching columns from data collection...")
        cols_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)
        logger.info(f"cols_json keys: {list(cols_json.keys()) if cols_json else 'None'}")

        # Check if column exists in cols_json
        if column_value not in cols_json:
            logger.error(f"Column '{column_value}' not found in cols_json!")
            logger.error(f"Available columns: {list(cols_json.keys())}")
            return []

        # Get the type of the selected column
        column_type = cols_json[column_value]["type"]
        logger.info(f"Frontend: Column '{column_value}' has type '{column_type}'")
        logger.info(f"Frontend: Available agg_functions keys: {list(agg_functions.keys())}")

        # Get the number of unique values in the selected column if it is a categorical column
        if column_type in ["object", "category"]:
            nb_unique = cols_json[column_value]["specs"]["nunique"]
        else:
            nb_unique = 0

        # Get the aggregation functions available for the selected column type
        if str(column_type) not in agg_functions:
            logger.error(f"Frontend: Column type '{column_type}' not found in agg_functions!")
            logger.error(f"Frontend: Available types: {list(agg_functions.keys())}")
            return []

        agg_functions_tmp_methods = agg_functions[str(column_type)]["input_methods"]
        logger.info(f"agg_functions_tmp_methods: {agg_functions_tmp_methods}")

        # Create a list of options for the dropdown
        options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]
        logger.info(f"Options before filtering: {options}")

        # Remove the aggregation methods that are not suitable for the selected column
        if nb_unique > 5:
            options = [e for e in options if e["label"] != "SegmentedControl"]
            logger.info(f"Options after filtering (nb_unique > 5): {options}")

        logger.info(f"Final options to return: {options}")
        logger.info("=== UPDATE AGGREGATION OPTIONS CALLBACK END ===")
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
        Output({"type": "input-dropdown-scale", "index": MATCH}, "style"),
        Output({"type": "input-number-marks", "index": MATCH}, "style"),
        Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def toggle_slider_controls_visibility(method_value):
        """
        Show the scale selector and marks number input only for Slider and RangeSlider components
        """
        if method_value in ["Slider", "RangeSlider"]:
            return {"display": "block"}, {"display": "block"}
        else:
            return {"display": "none"}, {"display": "none"}

    @app.callback(
        Output({"type": "input-body", "index": MATCH}, "children"),
        Output({"type": "interactive-description", "index": MATCH}, "children"),
        Output({"type": "interactive-columns-description", "index": MATCH}, "children"),
        [
            Input({"type": "input-title", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-scale", "index": MATCH}, "value"),
            # Input({"type": "input-color-picker", "index": MATCH}, "value"),  # Disabled color picker
            Input({"type": "input-number-marks", "index": MATCH}, "value"),
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
        scale_value,
        # color_value,  # Disabled color picker
        marks_number,
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
        logger.info("=== UPDATE CARD BODY CALLBACK START ===")
        logger.info("CALLBACK INPUT VALUES:")
        logger.info(f"  input_value: {input_value}")
        logger.info(f"  column_value: {column_value}")
        logger.info(f"  aggregation_value: {aggregation_value}")
        logger.info(f"  scale_value: {scale_value}")
        # logger.info(f"  color_value: {color_value}")  # Disabled color picker
        color_value = None  # Default value since color picker is disabled
        logger.info(f"  marks_number: {marks_number}")
        logger.info(f"  workflow_id: {workflow_id}")
        logger.info(f"  data_collection_id: {data_collection_id}")
        logger.info(f"  parent_index: {parent_index}")
        logger.info(f"  pathname: {pathname}")

        # Initialize columns_description_df at the very beginning to avoid UnboundLocalError
        columns_description_df = None

        if not local_data:
            logger.error("No local_data available!")
            return [], None, columns_description_df

        TOKEN = local_data["access_token"]

        headers = {
            "Authorization": f"Bearer {TOKEN}",
        }

        dashboard_id = pathname.split("/")[-1]
        # input_id = id["index"]

        # Only fetch component data if parent_index is not None (editing existing component)
        if parent_index is not None:
            logger.info(f"Fetching existing component data for parent_index: {parent_index}")
            component_data = get_component_data(
                input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
            )
        else:
            logger.info("Creating new component - no existing component data to fetch")
            component_data = None

        # Check if value was already assigned
        value = None

        # In edit mode, we should prioritize form values over component_data
        # Only fall back to component_data for missing workflow_id and data_collection_id
        if component_data and parent_index is not None:
            logger.info("Edit mode detected - using form values with component_data fallback")

            # Use form values if available, otherwise fall back to component_data
            if not workflow_id:
                workflow_id = component_data.get("wf_id")
                logger.info(f"Using workflow_id from component_data: {workflow_id}")

            if not data_collection_id:
                data_collection_id = component_data.get("dc_id")
                logger.info(f"Using data_collection_id from component_data: {data_collection_id}")

            # For edit mode, prefer form values over component_data
            # Only use component_data if form values are explicitly None
            if column_value is None:
                column_value = component_data["column_name"]
                logger.info(f"Using column_value from component_data: {column_value}")
            else:
                logger.info(f"Using column_value from form: {column_value}")

            if aggregation_value is None:
                aggregation_value = component_data["interactive_component_type"]
                logger.info(f"Using aggregation_value from component_data: {aggregation_value}")
            else:
                logger.info(f"Using aggregation_value from form: {aggregation_value}")

            if not value:
                value = component_data.get("value", None)
                logger.info(f"Using value from component_data: {value}")
            else:
                logger.info(f"Using value from form: {value}")

            if not input_value:
                input_value = component_data.get("title", "")
                logger.info(f"Using input_value from component_data: {input_value}")
            else:
                logger.info(f"Using input_value from form: {input_value}")

            # Restore slider configuration from component_data if not provided in form
            if scale_value is None:
                scale_value = component_data.get("scale", "linear")
                logger.info(f"Using scale_value from component_data: {scale_value}")
            else:
                logger.info(f"Using scale_value from form: {scale_value}")

            if marks_number is None:
                marks_number = component_data.get("marks_number", 5)
                logger.info(f"Using marks_number from component_data: {marks_number}")
            else:
                logger.info(f"Using marks_number from form: {marks_number}")

            # Restore color from component_data if it was saved (for components created before color picker was disabled)
            if color_value is None:
                saved_color = component_data.get("custom_color", None)
                if saved_color:
                    color_value = saved_color
                    logger.info(f"Using saved color_value from component_data: {color_value}")
                else:
                    logger.info("No saved color found, keeping color_value as None")

        logger.info("Using final values:")
        logger.info(f"  column_value: {column_value}")
        logger.info(f"  aggregation_value: {aggregation_value}")
        logger.info(f"  workflow_id: {workflow_id}")
        logger.info(f"  data_collection_id: {data_collection_id}")

        # Create columns description table early when we have workflow and data collection IDs
        # This ensures it's always available even for early returns
        if workflow_id and data_collection_id:
            cols_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)
            logger.info(f"cols_json: {cols_json}")
            logger.info(f"cols_json type: {type(cols_json)}")

            if cols_json:
                from dash import dash_table

                logger.info("Creating data_columns_df...")
                try:
                    data_columns_df = [
                        {"column": c, "description": cols_json[c]["description"]}
                        for c in cols_json
                        if cols_json[c]["description"] is not None
                    ]
                    logger.info(
                        f"data_columns_df created successfully: {len(data_columns_df)} rows"
                    )

                    logger.info("Creating DataTable...")
                    columns_description_df = dash_table.DataTable(
                        columns=[
                            {"name": "Column", "id": "column"},
                            {"name": "Description", "id": "description"},
                        ],
                        data=data_columns_df,
                        # Small font size, helvetica, no border, center text
                        style_cell={
                            "fontSize": 11,
                            "fontFamily": "Helvetica",
                            "border": "0px",
                            "textAlign": "center",
                            "backgroundColor": "var(--app-surface-color, #ffffff)",
                            "color": "var(--app-text-color, #000000)",
                            "padding": "4px 8px",
                            "maxWidth": "150px",
                            "overflow": "hidden",
                            "textOverflow": "ellipsis",
                        },
                        style_header={
                            "fontWeight": "bold",
                            "backgroundColor": "var(--app-surface-color, #ffffff)",
                            "color": "var(--app-text-color, #000000)",
                        },
                        style_data={
                            "backgroundColor": "var(--app-surface-color, #ffffff)",
                            "color": "var(--app-text-color, #000000)",
                        },
                    )
                    logger.info("DataTable created successfully")
                except Exception as e:
                    logger.error(f"Error creating data_columns_df or DataTable: {e}")
                    logger.error(
                        f"cols_json structure: {list(cols_json.keys()) if cols_json else 'None'}"
                    )
                    columns_description_df = html.Div("Error creating columns description table")
            else:
                logger.error("cols_json is empty or None!")
                cols_json = None
        else:
            logger.info("Missing workflow_id or data_collection_id for columns description")
            cols_json = None

        # If not in edit mode, check if essential values are missing
        if not component_data or parent_index is None:
            logger.info("Not in edit mode - checking for missing values")
            if (
                column_value is None
                or aggregation_value is None
                or workflow_id is None
                or data_collection_id is None
            ):
                logger.error("Missing essential values in non-edit mode")
                return ([], None, columns_description_df)

        # Check if we still have missing essential values
        if (
            column_value is None
            or aggregation_value is None
            or workflow_id is None
            or data_collection_id is None
        ):
            logger.error("Still missing essential values after fallback")
            logger.error(f"column_value: {column_value}, aggregation_value: {aggregation_value}")
            logger.error(f"workflow_id: {workflow_id}, data_collection_id: {data_collection_id}")
            return ([], None, columns_description_df)

        # Early validation: Check if the aggregation_value is compatible with the column type
        if cols_json and column_value in cols_json:
            actual_column_type = cols_json[column_value]["type"]
            from depictio.dash.modules.interactive_component.utils import agg_functions

            available_methods = list(
                agg_functions.get(str(actual_column_type), {}).get("input_methods", {}).keys()
            )

            if aggregation_value not in available_methods:
                logger.warning("INVALID COMBINATION detected in callback:")
                logger.warning(f"  Column: {column_value} (type: {actual_column_type})")
                logger.warning(f"  Requested component: {aggregation_value}")
                logger.warning(f"  Available components: {available_methods}")
                logger.warning("Returning empty result - user needs to select a valid component")
                return ([], None, columns_description_df)
            else:
                logger.info(
                    f"VALID COMBINATION: {aggregation_value} is available for {actual_column_type}"
                )

        logger.debug(f"TOTO - input_value: {input_value}")

        logger.info("About to get column type...")
        logger.info(f"column_value: {column_value}")
        logger.info(f"cols_json keys: {list(cols_json.keys()) if cols_json else 'None'}")

        # Check if we have cols_json and column_value exists in it
        if not cols_json:
            logger.error("cols_json is None - cannot proceed with component creation")
            return ([], None, columns_description_df)

        if column_value not in cols_json:
            logger.error(f"column_value '{column_value}' not found in cols_json!")
            return ([], None, columns_description_df)

        # Get the type of the selected column
        column_type = cols_json[column_value]["type"]
        logger.info(f"column_type: {column_type}")

        # Check if the aggregation_value is valid for this column_type
        logger.info(
            f"Checking if aggregation_value '{aggregation_value}' is valid for column_type '{column_type}'"
        )
        logger.info(
            f"Available input_methods for {column_type}: {list(agg_functions[str(column_type)].get('input_methods', {}).keys())}"
        )

        # Create interactive description with error handling
        try:
            description_text = agg_functions[str(column_type)]["input_methods"][aggregation_value][
                "description"
            ]
            logger.info(
                f"Found description for {column_type}.{aggregation_value}: {description_text}"
            )
        except KeyError as e:
            logger.error(f"KeyError accessing description: {e}")
            logger.error(f"column_type: {column_type}, aggregation_value: {aggregation_value}")
            logger.error(
                f"Available aggregation values: {list(agg_functions[str(column_type)].get('input_methods', {}).keys())}"
            )
            description_text = (
                f"Description not available for {aggregation_value} on {column_type} data"
            )

        interactive_description = html.Div(
            children=[
                html.Hr(),
                dmc.Tooltip(
                    children=dmc.Stack(
                        [
                            dmc.Badge(
                                children="Interactive component description",
                                leftSection=DashIconify(
                                    icon="mdi:information", color="white", width=20
                                ),
                                color="gray",
                                radius="lg",
                            ),
                        ]
                    ),
                    label=description_text,
                    multiline=True,
                    w=300,
                    withinPortal=False,
                    # transition="pop",
                    # transitionDuration=300,
                    transitionProps={
                        "name": "pop",
                        "duration": 300,
                    },
                    # justify="flex-end",
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

        # Handle joined data collection IDs
        if isinstance(data_collection_id, str) and "--" in data_collection_id:
            # For joined data collections, create synthetic specs
            dc_specs = {
                "config": {"type": "table", "metatype": "joined"},
                "data_collection_tag": f"Joined data collection ({data_collection_id})",
                "description": "Virtual joined data collection",
                "_id": data_collection_id,
            }
        else:
            # Regular data collection - fetch from API
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
            "build_frame": False,  # Don't build frame - return just the content for the input-body container
            "scale": scale_value,
            "color": color_value,  # Re-enabled since we set default value
            "marks_number": marks_number,
        }

        if value:
            interactive_kwargs["value"] = value

        new_interactive_component = build_interactive(**interactive_kwargs)

        logger.info("=== INTERACTIVE COMPONENT BUILT ===")
        logger.info(f"interactive_kwargs: {interactive_kwargs}")
        logger.info(f"new_interactive_component type: {type(new_interactive_component)}")
        logger.info(f"new_interactive_component: {new_interactive_component}")
        logger.info("=== RETURNING FROM UPDATE_CARD_BODY ===")

        return (
            new_interactive_component,
            interactive_description,
            columns_description_df,
        )


def design_interactive(id, df):
    left_column = dmc.GridCol(
        dmc.Stack(
            [
                html.H5("Interactive edit menu", style={"textAlign": "center"}),
                dmc.Card(
                    dmc.CardSection(
                        dmc.Stack(
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
                                dmc.Select(
                                    label="Scale type (for numerical sliders)",
                                    description="Choose between linear or logarithmic scale for slider components",
                                    id={
                                        "type": "input-dropdown-scale",
                                        "index": id["index"],
                                    },
                                    data=[
                                        {"label": "Linear", "value": "linear"},
                                        {"label": "Logarithmic (Log10)", "value": "log10"},
                                    ],
                                    value="linear",
                                    clearable=False,
                                    style={"display": "none"},  # Initially hidden
                                ),
                                # dmc.Stack(  # Disabled color picker
                                #     [
                                #         dmc.Text("Color customization", size="sm", fw="bold"),
                                #         dmc.ColorInput(
                                #             label="Pick any color from the page",
                                #             w=250,
                                #             id={
                                #                 "type": "input-color-picker",
                                #                 "index": id["index"],
                                #             },
                                #             value="var(--app-text-color, #000000)",
                                #             format="hex",
                                #             # leftSection=DashIconify(icon="cil:paint"),
                                #             swatches=[
                                #                 colors["purple"],  # Depictio brand colors first
                                #                 colors["blue"],
                                #                 colors["teal"],
                                #                 colors["green"],
                                #                 colors["yellow"],
                                #                 colors["orange"],
                                #                 colors["pink"],
                                #                 colors["red"],
                                #                 colors["violet"],
                                #                 colors["black"],
                                #                 # "#25262b",  # Additional neutral colors
                                #                 # "#868e96",
                                #                 # "#fa5252",
                                #                 # "#e64980",
                                #                 # "#be4bdb",
                                #                 # "#7950f2",
                                #                 # "#4c6ef5",
                                #                 # "#228be6",
                                #                 # "#15aabf",
                                #                 # "#12b886",
                                #                 # "#40c057",
                                #                 # "#82c91e",
                                #                 # "#fab005",
                                #                 # "#fd7e14",
                                #             ],
                                #         ),
                                #     ],
                                #     gap="xs",
                                # ),
                                dmc.NumberInput(
                                    label="Number of marks (for sliders)",
                                    description="Choose how many marks to display on the slider",
                                    id={
                                        "type": "input-number-marks",
                                        "index": id["index"],
                                    },
                                    value=5,
                                    min=3,
                                    max=10,
                                    step=1,
                                    style={"display": "none"},  # Initially hidden
                                ),
                                html.Div(
                                    id={
                                        "type": "interactive-description",
                                        "index": id["index"],
                                    },
                                ),
                                # html.Div(
                                #     "Debug: No column selected",
                                #     id={
                                #         "type": "debug-interactive-log",
                                #         "index": id["index"],
                                #     },
                                #     style={"fontSize": "10px", "color": "red"},
                                # ),
                            ],
                            gap="sm",
                        ),
                        id={
                            "type": "input",
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
        style={"display": "flex", "alignItems": "center", "justifyContent": "flex-end"},
    )
    right_column = dmc.GridCol(
        dmc.Stack(
            [
                html.H5("Resulting interactive component", style={"textAlign": "center"}),
                html.Div(
                    build_interactive_frame(index=id["index"], show_border=True),
                    id={
                        "type": "component-container",
                        "index": id["index"],
                    },
                ),
            ],
            align="flex-start",  # Align to left (horizontal)
            justify="center",  # Center vertically
            gap="md",
            style={"height": "100%"},
        ),
        span="auto",
        style={"display": "flex", "alignItems": "center", "justifyContent": "flex-start"},
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
            align="center",
            justify="center",
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
                    "type": "interactive-columns-description",
                    "index": id["index"],
                }
            ),
        ],
        gap="md",
        style={"marginTop": "2rem"},
    )

    interactive_row = [
        dmc.Stack(
            [main_layout, html.Hr(), bottom_section],
            gap="lg",
        ),
    ]
    return interactive_row


def create_stepper_interactive_button(n, disabled=None):
    """
    Create the stepper interactive button

    Args:
        n (_type_): _description_
        disabled (bool, optional): Override enabled state. If None, uses metadata.
    """
    import dash_bootstrap_components as dbc

    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("interactive")

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
            color=get_dmc_button_color("interactive"),
            leftSection=DashIconify(icon="bx:slider-alt", color="white"),
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
