"""
Interactive Component - Design/Edit Mode Callbacks

This module contains callbacks that are only needed when editing or designing interactive components.
These callbacks are lazy-loaded when entering edit mode to reduce initial app startup time.

Callbacks:
- pre_populate_interactive_settings_for_edit: Pre-fill design form in edit mode
- update_aggregation_options: Populate method dropdown based on column selection
- toggle_slider_controls_visibility: Show/hide slider controls based on method selection
"""

from dash import MATCH, Input, Output, State, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.utils import get_columns_from_data_collection


def register_interactive_design_callbacks(app):
    """Register design/edit mode callbacks for interactive component."""

    # Pre-populate interactive settings in edit mode (edit page, not stepper)
    @app.callback(
        Output({"type": "input-title", "index": MATCH}, "value"),
        Output({"type": "input-dropdown-column", "index": MATCH}, "value"),
        Output({"type": "input-dropdown-method", "index": MATCH}, "value"),
        Output({"type": "input-dropdown-scale", "index": MATCH}, "value"),
        Output({"type": "input-color-picker", "index": MATCH}, "value"),
        Output({"type": "input-icon-selector", "index": MATCH}, "value"),
        Output({"type": "input-title-size", "index": MATCH}, "value"),
        Output({"type": "input-number-marks", "index": MATCH}, "value"),
        Input("edit-page-context", "data"),
        State({"type": "input-title", "index": MATCH}, "id"),
        prevent_initial_call="initial_duplicate",
    )
    def pre_populate_interactive_settings_for_edit(edit_context, input_id):
        """
        Pre-populate interactive design settings when in edit mode.

        Uses actual component ID (no -tmp suffix). Only populates when
        the input_id matches the component being edited in the edit page.

        Args:
            edit_context: Edit page context with component data
            input_id: Interactive component ID from the design form

        Returns:
            Tuple of pre-populated values for all interactive settings
        """
        import dash

        if not edit_context:
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        component_data = edit_context.get("component_data")
        if not component_data or component_data.get("component_type") != "interactive":
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        # Match component ID (actual ID, no -tmp)
        if str(input_id["index"]) != str(edit_context.get("component_id")):
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        logger.info(f"🎨 PRE-POPULATING interactive settings for component {input_id['index']}")
        logger.info(f"   Title: {component_data.get('title')}")
        logger.info(f"   Column: {component_data.get('column_name')}")
        logger.info(f"   Method: {component_data.get('interactive_component_type')}")
        logger.info(f"   Scale: {component_data.get('scale')}")

        # Ensure ColorInput components get empty string instead of None to avoid trim() errors
        return (
            component_data.get("title") or "",  # TextInput needs string
            component_data.get("column_name"),  # Select accepts None
            component_data.get("interactive_component_type"),  # Select accepts None
            component_data.get("scale") or "linear",  # Select needs value
            component_data.get("custom_color") or "",  # ColorInput needs empty string, not None
            component_data.get("icon_name") or "bx:slider-alt",  # Select needs value
            component_data.get("title_size") or "md",  # Select needs value
            component_data.get("marks_number") or 2,  # NumberInput needs value
        )

    # Populate method dropdown based on column selection
    @app.callback(
        Output({"type": "input-dropdown-method", "index": MATCH}, "data"),
        [
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input("edit-page-context", "data"),
            State({"type": "input-dropdown-method", "index": MATCH}, "id"),
            State("local-store", "data"),
        ],
        prevent_initial_call=False,
    )
    def update_aggregation_options(
        column_value, workflow_id, data_collection_id, edit_context, id, local_data
    ):
        """
        Populate method dropdown based on selected column type.

        Restored from legacy code (commit 852b230e~1) - adapted for multi-app architecture.
        Uses edit-page-context for edit mode, stepper selections for add mode.
        """

        logger.info("=== UPDATE AGGREGATION OPTIONS CALLBACK START ===")
        logger.info(f"column_value: {column_value}")
        logger.info(f"workflow_id: {workflow_id}")
        logger.info(f"data_collection_id: {data_collection_id}")
        logger.info(f"edit_context: {edit_context is not None}")
        logger.info(f"id: {id}")
        logger.info(f"local_data available: {local_data is not None}")

        if not local_data:
            logger.error("No local_data available!")
            return []

        TOKEN = local_data["access_token"]

        # In edit mode, get workflow/dc IDs from edit context
        if edit_context and (not workflow_id or not data_collection_id):
            logger.info("Edit mode detected - using edit-page-context")
            component_data = edit_context.get("component_data", {})
            if component_data:
                workflow_id = component_data.get("wf_id")
                data_collection_id = component_data.get("dc_id")
                logger.info(
                    f"Retrieved from edit context - workflow_id: {workflow_id}, data_collection_id: {data_collection_id}"
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

        # Import agg_functions inline (as done in legacy code)
        from depictio.dash.modules.interactive_component.utils import agg_functions

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

    # COMMENTED OUT: Show/hide slider controls (scale type & marks inputs disabled for now)
    # @app.callback(
    #     Output({"type": "input-dropdown-scale", "index": MATCH}, "style"),
    #     Output({"type": "input-number-marks", "index": MATCH}, "style"),
    #     Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
    #     prevent_initial_call=True,
    # )
    # def toggle_slider_controls_visibility(method_value):
    #     """
    #     Show the scale selector and marks number input only for Slider and RangeSlider components.
    #
    #     Restored from legacy code (commit 852b230e~1) - was commented out during multi-app refactor.
    #     """
    #     if method_value in ["Slider", "RangeSlider"]:
    #         return {"display": "block"}, {"display": "block"}
    #     else:
    #         return {"display": "none"}, {"display": "none"}

    # Update preview component based on form inputs
    @app.callback(
        Output({"type": "input-body", "index": MATCH}, "children"),
        Output({"type": "interactive-description", "index": MATCH}, "children"),
        Output({"type": "interactive-columns-description", "index": MATCH}, "children"),
        [
            Input({"type": "input-title", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-scale", "index": MATCH}, "value"),
            Input({"type": "input-color-picker", "index": MATCH}, "value"),
            Input({"type": "input-icon-selector", "index": MATCH}, "value"),
            Input({"type": "input-title-size", "index": MATCH}, "value"),
            Input({"type": "input-number-marks", "index": MATCH}, "value"),
            Input("edit-page-context", "data"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "input-dropdown-method", "index": MATCH}, "id"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_preview_component(
        input_value,
        column_value,
        aggregation_value,
        scale_value,
        color_value,
        icon_name,
        title_size,
        marks_number,
        edit_context,
        workflow_id,
        data_collection_id,
        id,
        local_data,
    ):
        """
        Update interactive component preview based on form inputs.

        Restored from legacy code (commit 852b230e~1) - adapted for multi-app architecture.
        """
        import dash_mantine_components as dmc

        logger.info("=== UPDATE PREVIEW COMPONENT CALLBACK START ===")

        # Initialize columns_description_df
        columns_description_df = None

        if not local_data:
            logger.error("No local_data available!")
            return [], None, columns_description_df

        TOKEN = local_data["access_token"]

        # In edit mode, get workflow/dc IDs and pre-populated values from edit context
        if edit_context:
            logger.info("Edit mode detected - using edit-page-context")
            component_data = edit_context.get("component_data", {})
            if component_data:
                # Use stepper values if available, otherwise fall back to component data
                if not workflow_id:
                    workflow_id = component_data.get("wf_id")
                if not data_collection_id:
                    data_collection_id = component_data.get("dc_id")

                # Pre-populate form values from component data if not set
                if column_value is None:
                    column_value = component_data.get("column_name")
                if aggregation_value is None:
                    aggregation_value = component_data.get("interactive_component_type")
                if not input_value:
                    input_value = component_data.get("title", "")
                if scale_value is None:
                    scale_value = component_data.get("scale", "linear")
                if marks_number is None:
                    marks_number = component_data.get("marks_number", 2)
                if not color_value:
                    color_value = component_data.get("custom_color", "")
                if not title_size:
                    title_size = component_data.get("title_size", "md")
                if not icon_name:
                    icon_name = component_data.get("icon_name", "bx:slider-alt")

        # Check for missing essential values
        if not workflow_id or not data_collection_id:
            logger.error(
                f"Missing workflow/dc - workflow_id: {workflow_id}, data_collection_id: {data_collection_id}"
            )
            return [], None, columns_description_df

        if column_value is None or aggregation_value is None:
            logger.info(
                f"Missing column or method - column: {column_value}, method: {aggregation_value}"
            )
            return [], None, columns_description_df

        # Fetch column metadata
        cols_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)

        if not cols_json or column_value not in cols_json:
            logger.error(f"Column '{column_value}' not found in cols_json")
            return [], None, columns_description_df

        # Get column type
        column_type = cols_json[column_value]["type"]
        logger.info(f"Column '{column_value}' has type '{column_type}'")

        # Validate aggregation_value is compatible with column type
        from depictio.dash.modules.interactive_component.utils import agg_functions

        available_methods = list(
            agg_functions.get(str(column_type), {}).get("input_methods", {}).keys()
        )

        if aggregation_value not in available_methods:
            logger.warning(
                f"Invalid combination - {aggregation_value} not available for {column_type}"
            )
            return [], None, columns_description_df

        # Get component description
        try:
            description_text = agg_functions[str(column_type)]["input_methods"][aggregation_value][
                "description"
            ]
        except KeyError:
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
                ),
            ]
        )

        # Create columns description table
        try:
            data_columns_df = [
                {"column": c, "description": cols_json[c]["description"]}
                for c in cols_json
                if cols_json[c]["description"] is not None
            ]

            table_rows = []
            for row in data_columns_df:
                table_rows.append(
                    dmc.TableTr(
                        [
                            dmc.TableTd(
                                row["column"],
                                style={
                                    "textAlign": "center",
                                    "fontSize": "11px",
                                    "maxWidth": "150px",
                                },
                            ),
                            dmc.TableTd(
                                row["description"],
                                style={
                                    "textAlign": "center",
                                    "fontSize": "11px",
                                    "maxWidth": "150px",
                                },
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
        except Exception as e:
            logger.error(f"Error creating columns description table: {e}")
            columns_description_df = html.Div("Error creating columns description table")

        # Build simplified preview component (no stores to avoid triggering batch callbacks)
        # Get unique values for categorical components
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import load_deltatable_lite

        try:
            df = load_deltatable_lite(
                ObjectId(workflow_id),
                ObjectId(data_collection_id),
                TOKEN=TOKEN,
            )

            # Create preview based on component type
            if aggregation_value in ["Select", "MultiSelect", "SegmentedControl"]:
                # Get unique values
                unique_vals = df[column_value].unique()
                if hasattr(unique_vals, "to_list"):
                    unique_vals_list = unique_vals.to_list()
                elif hasattr(unique_vals, "tolist"):
                    unique_vals_list = unique_vals.tolist()
                else:
                    unique_vals_list = list(unique_vals)

                options = [str(val) for val in unique_vals_list if val is not None][:20]

                if aggregation_value == "Select":
                    preview_component = dmc.Select(
                        data=[{"label": opt, "value": opt} for opt in options],
                        placeholder=f"Select {column_value}",
                        style={"width": "100%"},
                    )
                elif aggregation_value == "MultiSelect":
                    preview_component = dmc.MultiSelect(
                        data=[{"label": opt, "value": opt} for opt in options],
                        placeholder=f"Select {column_value} (multiple)",
                        style={"width": "100%"},
                    )
                else:  # SegmentedControl
                    preview_component = dmc.SegmentedControl(
                        data=options[:5],  # Limit to 5 for segmented control
                        fullWidth=True,
                    )

            elif aggregation_value in ["Slider", "RangeSlider"]:
                # Get min/max values
                col_min = float(df[column_value].min())
                col_max = float(df[column_value].max())

                if aggregation_value == "Slider":
                    preview_component = dmc.Slider(
                        min=col_min,
                        max=col_max,
                        value=col_min,
                        style={"width": "100%"},
                    )
                else:  # RangeSlider
                    preview_component = dmc.RangeSlider(
                        min=col_min,
                        max=col_max,
                        value=(col_min, col_max),
                        style={"width": "100%"},
                    )

            elif aggregation_value == "DateRangePicker":
                preview_component = dmc.DatePickerInput(
                    type="range",
                    placeholder="Select date range",
                    style={"width": "100%"},
                )

            else:
                preview_component = dmc.Text(f"Preview for {aggregation_value}", c="gray")

            # Wrap with title
            new_interactive_component = dmc.Stack(
                [
                    dmc.Group(
                        [
                            DashIconify(
                                icon=icon_name or "bx:slider-alt",
                                width=24,
                                color=color_value if color_value else None,
                            ),
                            dmc.Text(input_value or column_value, size=title_size, fw="bold"),
                        ],
                        gap="xs",
                    ),
                    preview_component,
                ],
                gap="sm",
            )

        except Exception as e:
            logger.error(f"Error building preview: {e}")
            new_interactive_component = dmc.Alert(
                title="Preview Error",
                children=f"Could not generate preview: {str(e)}",
                color="red",
            )

        logger.info("=== PREVIEW COMPONENT BUILT SUCCESSFULLY ===")

        return (
            new_interactive_component,
            interactive_description,
            columns_description_df,
        )

    # Update stored metadata when workflow/DC are selected (for save functionality)
    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
            Input({"type": "input-title", "index": MATCH}, "value"),
            Input({"type": "input-color-picker", "index": MATCH}, "value"),
            Input({"type": "input-icon-selector", "index": MATCH}, "value"),
            Input({"type": "input-title-size", "index": MATCH}, "value"),
        ],
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_stored_metadata(
        workflow_id, dc_id, column, method, title, color, icon, title_size, current_metadata
    ):
        """
        Update the stored-metadata-component Store as user configures the interactive component.
        This metadata is used by save_stepper_component callback to persist the component.
        """
        if not current_metadata:
            current_metadata = {}

        # Update with latest selections
        current_metadata.update(
            {
                "workflow_id": workflow_id,
                "data_collection_id": dc_id,
                "column": column,
                "method": method,
                "title": title or column,
                "color": color,
                "icon": icon,
                "title_size": title_size,
            }
        )

        logger.info(f"📝 Updated stored metadata: {current_metadata}")
        return current_metadata

    logger.info("✅ Interactive design callbacks registered")
