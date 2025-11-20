# Import necessary libraries
import dash_mantine_components as dmc
import httpx
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.colors import colors
from depictio.dash.component_metadata import get_component_color, get_dmc_button_color, is_enabled
from depictio.dash.modules.card_component.utils import (
    agg_functions,
    build_card,
    build_card_frame,
    get_adaptive_trend_colors,
)

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

    # Callback to switch between simple and advanced mode
    @app.callback(
        Output({"type": "card-simple-container", "index": MATCH}, "style"),
        Output({"type": "card-advanced-container", "index": MATCH}, "style"),
        Output({"type": "card-advanced-container", "index": MATCH}, "children"),
        Input({"type": "card-metric-mode", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        State("current-edit-parent-index", "data"),
        State({"type": "card-metric-mode", "index": MATCH}, "id"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def switch_card_mode(mode, wf_tag, dc_tag, parent_index, component_id, local_data, pathname):
        """
        Callback to switch between simple and advanced card configuration modes.

        Args:
            mode: "simple" or "advanced"
            wf_tag: Workflow tag
            dc_tag: Data collection tag
            parent_index: Parent component index (edit mode)
            component_id: Component ID dict with index
            local_data: Local storage data (contains TOKEN)
            pathname: Current URL pathname

        Returns:
            Tuple: (simple_style, advanced_style, advanced_children)
        """
        logger.info(f"=== CARD MODE SWITCH: {mode} ===")

        if not local_data:
            logger.error("No local_data available!")
            return {"display": "block"}, {"display": "none"}, []

        TOKEN = local_data["access_token"]
        index = component_id["index"]

        # In edit mode, get workflow/dc IDs from component data if needed
        if parent_index is not None and (not wf_tag or not dc_tag):
            logger.info(f"Edit mode - fetching component data for parent_index: {parent_index}")
            dashboard_id = pathname.split("/")[-1]
            component_data = get_component_data(
                input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
            )
            if component_data:
                wf_tag = component_data.get("wf_id")
                dc_tag = component_data.get("dc_id")
                logger.info(f"Retrieved from component_data - wf_tag: {wf_tag}, dc_tag: {dc_tag}")

        # Get columns from data collection
        if not wf_tag or not dc_tag:
            logger.warning(f"Missing workflow/dc tags - wf_tag: {wf_tag}, dc_tag: {dc_tag}")
            df_columns = []
        else:
            cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
            df_columns = list(cols_json.keys()) if cols_json else []

        logger.info(f"Mode: {mode}, Columns available: {len(df_columns)}")

        # Toggle visibility based on mode
        if mode == "simple":
            simple_style = {"display": "block"}
            advanced_style = {"display": "none"}
            advanced_children = []
        else:
            simple_style = {"display": "none"}
            advanced_style = {"display": "block"}
            advanced_children = create_advanced_stepper_ui(index, df_columns)

        return simple_style, advanced_style, advanced_children

    # Callback to handle stepper navigation (Back/Next buttons)
    @app.callback(
        Output({"type": "card-operation-stepper", "index": MATCH}, "active"),
        Output({"type": "card-step-1-panel", "index": MATCH}, "style"),
        Output({"type": "card-step-2-panel", "index": MATCH}, "style"),
        Output({"type": "card-step-3-panel", "index": MATCH}, "style"),
        Output({"type": "card-completed-panel", "index": MATCH}, "style"),
        Input({"type": "card-stepper-back", "index": MATCH}, "n_clicks"),
        Input({"type": "card-stepper-next", "index": MATCH}, "n_clicks"),
        State({"type": "card-operation-stepper", "index": MATCH}, "active"),
        prevent_initial_call=True,
    )
    def navigate_stepper(back_clicks, next_clicks, current_step):
        """
        Handle stepper navigation with Back and Next buttons.

        Args:
            back_clicks: Number of Back button clicks
            next_clicks: Number of Next button clicks
            current_step: Current active step (0-3)

        Returns:
            Tuple: (new_active_step, step1_style, step2_style, step3_style, completed_style)
        """
        from dash import ctx

        if not ctx.triggered_id:
            return (
                current_step,
                {"display": "block"},
                {"display": "none"},
                {"display": "none"},
                {"display": "none"},
            )

        # Determine which button was clicked
        button_type = ctx.triggered_id["type"]

        # Update active step
        if button_type == "card-stepper-back" and current_step > 0:
            new_step = current_step - 1
        elif button_type == "card-stepper-next" and current_step < 3:
            new_step = current_step + 1
        else:
            new_step = current_step

        # Set panel visibility based on active step
        panel_styles = [
            {"display": "block"} if new_step == i else {"display": "none"} for i in range(4)
        ]

        logger.info(f"Stepper navigation: {button_type}, current={current_step}, new={new_step}")

        return new_step, *panel_styles

    # Callback to show config panel for operation step 1
    @app.callback(
        Output({"type": "card-filter-config-1", "index": MATCH}, "style"),
        Output({"type": "card-groupby-config-1", "index": MATCH}, "style"),
        Output({"type": "card-filter-column-1", "index": MATCH}, "data"),
        Output({"type": "card-groupby-columns-1", "index": MATCH}, "data"),
        Input({"type": "card-operation-type-1", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        State("current-edit-parent-index", "data"),
        State({"type": "card-operation-type-1", "index": MATCH}, "id"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def show_step_1_config(
        operation_type, wf_tag, dc_tag, parent_index, component_id, local_data, pathname
    ):
        """
        Toggle visibility of step 1 config panels and update column data.

        Args:
            operation_type: Selected operation type ("skip", "filter", or "groupby")
            wf_tag: Workflow tag
            dc_tag: Data collection tag
            parent_index: Parent component index (edit mode)
            component_id: Component ID dict with index
            local_data: Local storage data (contains TOKEN)
            pathname: Current URL pathname

        Returns:
            Tuple: (filter_style, groupby_style, filter_columns, groupby_columns)
        """
        logger.info(f"Step 1 operation type selected: {operation_type}")

        # Get columns from data collection
        df_columns = []
        if local_data:
            TOKEN = local_data["access_token"]

            # Get columns from data collection
            if parent_index is not None and (not wf_tag or not dc_tag):
                dashboard_id = pathname.split("/")[-1]
                component_data = get_component_data(
                    input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
                )
                if component_data:
                    wf_tag = component_data.get("wf_id")
                    dc_tag = component_data.get("dc_id")

            if wf_tag and dc_tag:
                cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
                df_columns = list(cols_json.keys()) if cols_json else []

        # Build column options
        column_options = [{"label": c, "value": c} for c in df_columns]

        # Toggle visibility and update data based on operation type
        if operation_type == "skip":
            return (
                {"display": "none"},  # filter style
                {"display": "none"},  # groupby style
                column_options,  # filter columns
                column_options,  # groupby columns
            )
        elif operation_type == "filter":
            return (
                {"display": "block"},  # filter style
                {"display": "none"},  # groupby style
                column_options,  # filter columns
                column_options,  # groupby columns
            )
        elif operation_type == "groupby":
            return (
                {"display": "none"},  # filter style
                {"display": "block"},  # groupby style
                column_options,  # filter columns
                column_options,  # groupby columns
            )

        return {"display": "none"}, {"display": "none"}, column_options, column_options

    # Callback to show config panel for operation step 2
    @app.callback(
        Output({"type": "card-filter-config-2", "index": MATCH}, "style"),
        Output({"type": "card-groupby-config-2", "index": MATCH}, "style"),
        Output({"type": "card-filter-column-2", "index": MATCH}, "data"),
        Output({"type": "card-groupby-columns-2", "index": MATCH}, "data"),
        Input({"type": "card-operation-type-2", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        State("current-edit-parent-index", "data"),
        State({"type": "card-operation-type-2", "index": MATCH}, "id"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def show_step_2_config(
        operation_type, wf_tag, dc_tag, parent_index, component_id, local_data, pathname
    ):
        """
        Toggle visibility of step 2 config panels and update column data.

        Args:
            operation_type: Selected operation type ("skip", "filter", or "groupby")
            wf_tag: Workflow tag
            dc_tag: Data collection tag
            parent_index: Parent component index (edit mode)
            component_id: Component ID dict with index
            local_data: Local storage data (contains TOKEN)
            pathname: Current URL pathname

        Returns:
            Tuple: (filter_style, groupby_style, filter_columns, groupby_columns)
        """
        logger.info(f"Step 2 operation type selected: {operation_type}")

        # Get columns from data collection
        df_columns = []
        if local_data:
            TOKEN = local_data["access_token"]

            # Get columns from data collection
            if parent_index is not None and (not wf_tag or not dc_tag):
                dashboard_id = pathname.split("/")[-1]
                component_data = get_component_data(
                    input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
                )
                if component_data:
                    wf_tag = component_data.get("wf_id")
                    dc_tag = component_data.get("dc_id")

            if wf_tag and dc_tag:
                cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
                df_columns = list(cols_json.keys()) if cols_json else []

        # Build column options
        column_options = [{"label": c, "value": c} for c in df_columns]

        # Toggle visibility and update data based on operation type
        if operation_type == "skip":
            return (
                {"display": "none"},  # filter style
                {"display": "none"},  # groupby style
                column_options,  # filter columns
                column_options,  # groupby columns
            )
        elif operation_type == "filter":
            return (
                {"display": "block"},  # filter style
                {"display": "none"},  # groupby style
                column_options,  # filter columns
                column_options,  # groupby columns
            )
        elif operation_type == "groupby":
            return (
                {"display": "none"},  # filter style
                {"display": "block"},  # groupby style
                column_options,  # filter columns
                column_options,  # groupby columns
            )

        return {"display": "none"}, {"display": "none"}, column_options, column_options

    # Callback to build and store pipeline configuration from user selections
    @app.callback(
        Output({"type": "card-pipeline-store", "index": MATCH}, "data"),
        Output({"type": "card-pipeline-summary", "index": MATCH}, "children"),
        Input({"type": "card-operation-type-1", "index": MATCH}, "value"),
        Input({"type": "card-operation-type-2", "index": MATCH}, "value"),
        Input({"type": "card-final-aggregation-method", "index": MATCH}, "value"),
        State({"type": "card-filter-column-1", "index": MATCH}, "value"),
        State({"type": "card-filter-operator-1", "index": MATCH}, "value"),
        State({"type": "card-filter-value-1", "index": MATCH}, "value"),
        State({"type": "card-groupby-columns-1", "index": MATCH}, "value"),
        State({"type": "card-filter-column-2", "index": MATCH}, "value"),
        State({"type": "card-filter-operator-2", "index": MATCH}, "value"),
        State({"type": "card-filter-value-2", "index": MATCH}, "value"),
        State({"type": "card-groupby-columns-2", "index": MATCH}, "value"),
        State({"type": "card-final-aggregation-column", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def build_pipeline_from_selections(
        op_type_1,
        op_type_2,
        agg_method,
        # Step 1 configs
        filter_col_1,
        filter_op_1,
        filter_val_1,
        groupby_cols_1,
        # Step 2 configs
        filter_col_2,
        filter_op_2,
        filter_val_2,
        groupby_cols_2,
        # Aggregation
        agg_column,
    ):
        """
        Build CardPipeline object from user selections in advanced mode stepper.

        Collects all operation configurations and constructs a valid CardPipeline
        that can be passed to CardOperationExecutor.

        Args:
            op_type_1: Operation type for step 1 (skip/filter/groupby)
            op_type_2: Operation type for step 2 (skip/filter/groupby)
            agg_method: Final aggregation method
            filter_col_1, filter_op_1, filter_val_1: Step 1 filter config
            groupby_cols_1: Step 1 groupby config
            filter_col_2, filter_op_2, filter_val_2: Step 2 filter config
            groupby_cols_2: Step 2 groupby config
            agg_column: Column for aggregation (if required)

        Returns:
            Tuple: (pipeline_data_dict, summary_text)
        """
        from depictio.models.models.card_operations import (
            AggregateOperation,
            CardOperationStep,
            CardPipeline,
            FilterOperation,
            GroupByOperation,
        )

        logger.info("🔨 Building pipeline from user selections")
        logger.debug(f"Step 1: {op_type_1}, Step 2: {op_type_2}, Aggregation: {agg_method}")

        try:
            # Build operation steps list (skip "skip" operations - only add actual operations)
            operations = []

            # Step 1 - only add if not skip
            if op_type_1 == "filter" and filter_col_1 and filter_op_1:
                # Parse filter value - convert to appropriate type
                parsed_value = filter_val_1
                if filter_op_1 in ["in", "not_in"] and filter_val_1:
                    # Convert comma-separated string to list
                    parsed_value = [v.strip() for v in filter_val_1.split(",")]

                operations.append(
                    CardOperationStep(
                        step_number=len(operations) + 1,  # Sequential numbering
                        operation_type="filter",
                        config=FilterOperation(
                            column=filter_col_1, operator=filter_op_1, value=parsed_value
                        ),
                    )
                )
                logger.debug(
                    f"Added step {len(operations)} filter: {filter_col_1} {filter_op_1} {parsed_value}"
                )

            elif op_type_1 == "groupby" and groupby_cols_1:
                operations.append(
                    CardOperationStep(
                        step_number=len(operations) + 1,  # Sequential numbering
                        operation_type="groupby",
                        config=GroupByOperation(columns=groupby_cols_1),
                    )
                )
                logger.debug(f"Added step {len(operations)} groupby: {groupby_cols_1}")

            elif op_type_1 == "skip":
                logger.debug("Step 1 skipped - not adding to operations list")

            # Step 2 - only add if not skip
            if op_type_2 == "filter" and filter_col_2 and filter_op_2:
                # Parse filter value
                parsed_value = filter_val_2
                if filter_op_2 in ["in", "not_in"] and filter_val_2:
                    parsed_value = [v.strip() for v in filter_val_2.split(",")]

                operations.append(
                    CardOperationStep(
                        step_number=len(operations) + 1,  # Sequential numbering
                        operation_type="filter",
                        config=FilterOperation(
                            column=filter_col_2, operator=filter_op_2, value=parsed_value
                        ),
                    )
                )
                logger.debug(
                    f"Added step {len(operations)} filter: {filter_col_2} {filter_op_2} {parsed_value}"
                )

            elif op_type_2 == "groupby" and groupby_cols_2:
                operations.append(
                    CardOperationStep(
                        step_number=len(operations) + 1,  # Sequential numbering
                        operation_type="groupby",
                        config=GroupByOperation(columns=groupby_cols_2),
                    )
                )
                logger.debug(f"Added step {len(operations)} groupby: {groupby_cols_2}")

            elif op_type_2 == "skip":
                logger.debug("Step 2 skipped - not adding to operations list")

            # Build final aggregation
            # Define which methods require a column
            METHODS_REQUIRING_COLUMN = [
                "sum",
                "mean",
                "median",
                "min",
                "max",
                "std",
                "var",
                "nunique",
            ]

            # Check if method requires column but none selected yet
            if agg_method in METHODS_REQUIRING_COLUMN and not agg_column:
                error_msg = f"Please select a column for '{agg_method}' aggregation"
                logger.warning(f"⚠️ {error_msg}")
                return None, dmc.Text(error_msg, size="sm", c="orange")

            final_aggregate = AggregateOperation(method=agg_method, column=agg_column)
            logger.debug(f"Final aggregation: {agg_method}({agg_column if agg_column else ''})")

            # Build pipeline
            pipeline = CardPipeline(
                mode="advanced", operations=operations, final_aggregate=final_aggregate
            )

            # Get display summary
            summary_text = pipeline.get_display_summary()
            logger.info(f"✅ Pipeline built successfully: {summary_text}")

            # Convert to dict for storage (Pydantic model_dump)
            pipeline_dict = pipeline.model_dump()

            return pipeline_dict, dmc.Text(summary_text, size="sm", c="green")

        except Exception as e:
            logger.error(f"❌ Failed to build pipeline: {e}", exc_info=True)
            error_msg = f"Error building pipeline: {str(e)}"
            return None, dmc.Text(error_msg, size="sm", c="red")

    # Callback to show column selector for aggregation methods that require it
    @app.callback(
        Output({"type": "card-final-aggregation-column-hidden", "index": MATCH}, "style"),
        Output({"type": "card-final-aggregation-column", "index": MATCH}, "data"),
        Input({"type": "card-final-aggregation-method", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        State("current-edit-parent-index", "data"),
        State({"type": "card-final-aggregation-method", "index": MATCH}, "id"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def show_aggregation_column_selector(
        aggregation_method, wf_tag, dc_tag, parent_index, component_id, local_data, pathname
    ):
        """
        Toggle visibility of column selector and update column data.

        Count doesn't need a column, but all other methods do.

        Args:
            aggregation_method: Selected aggregation method
            wf_tag: Workflow tag
            dc_tag: Data collection tag
            parent_index: Parent component index (edit mode)
            component_id: Component ID dict with index
            local_data: Local storage data (contains TOKEN)
            pathname: Current URL pathname

        Returns:
            Tuple: (column_selector_style, column_options)
        """
        logger.info(f"Aggregation method selected: {aggregation_method}")
        logger.debug(f"wf_tag: {wf_tag}, dc_tag: {dc_tag}, parent_index: {parent_index}")

        # Get columns from data collection
        df_columns = []
        if local_data:
            TOKEN = local_data["access_token"]

            # Get columns from data collection
            if parent_index is not None and (not wf_tag or not dc_tag):
                logger.debug("Fetching wf_tag/dc_tag from parent component")
                dashboard_id = pathname.split("/")[-1]
                component_data = get_component_data(
                    input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
                )
                if component_data:
                    wf_tag = component_data.get("wf_id")
                    dc_tag = component_data.get("dc_id")
                    logger.debug(f"Retrieved wf_tag: {wf_tag}, dc_tag: {dc_tag} from parent")

            if wf_tag and dc_tag:
                cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
                df_columns = list(cols_json.keys()) if cols_json else []
                logger.debug(f"Retrieved {len(df_columns)} columns: {df_columns}")
            else:
                logger.warning("⚠️ Cannot get columns - missing wf_tag or dc_tag")

        # Build column options
        column_options = [{"label": c, "value": c} for c in df_columns]

        # Count doesn't need a column - hide selector
        if aggregation_method == "count":
            logger.debug("Hiding column selector for 'count' aggregation")
            return {"display": "none"}, column_options

        # Other methods need column - show selector
        logger.info(
            f"✅ Showing column selector with {len(column_options)} options for '{aggregation_method}'"
        )
        return {"display": "block"}, column_options

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
            Input({"type": "card-color-background", "index": MATCH}, "value"),
            Input({"type": "card-color-title", "index": MATCH}, "value"),
            Input({"type": "card-icon-selector", "index": MATCH}, "value"),
            Input({"type": "card-title-font-size", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State("current-edit-parent-index", "data"),  # Retrieve parent_index
            State({"type": "card-dropdown-column", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
            Input(
                {"type": "card-pipeline-store", "index": MATCH}, "data"
            ),  # Advanced mode pipeline - triggers callback when pipeline updates
        ],
        # prevent_initial_call=True,
    )
    def design_card_body(
        input_value,
        column_name,
        aggregation_value,
        background_color,
        title_color,
        icon_name,
        title_font_size,
        wf_id,
        dc_id,
        parent_index,
        id,
        local_data,
        pathname,
        pipeline_data,  # Pipeline from advanced mode (None for simple mode)
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
        logger.info(f"background_color: {background_color}")
        logger.info(f"title_color: {title_color}")
        logger.info(f"icon_name: {icon_name}")
        logger.info(f"title_font_size: {title_font_size}")

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
        # BUT: In advanced mode, column_name and aggregation_value can be None
        # because we use pipeline_data instead
        if column_name is None or aggregation_value is None or wf_id is None or dc_id is None:
            # Check if we're in advanced mode with valid pipeline
            if pipeline_data is not None:
                # Advanced mode - pipeline is valid, proceed with rendering
                # Use placeholder values for simple mode fields (won't be used)
                column_name = "advanced_mode_placeholder"
                aggregation_value = "count"  # Placeholder
                logger.info("🔬 ADVANCED MODE: Bypassing simple mode validation")
            elif not component_data:
                return ([], None, columns_description_df)
            else:
                column_name = component_data["column_name"]
                aggregation_value = component_data["aggregation"]
                input_value = component_data["title"]
                logger.info("COMPOENNT DATA")
                logger.info(f"column_name: {column_name}")
                logger.info(f"aggregation_value: {aggregation_value}")
                logger.info(f"input_value: {input_value}")

        # Simple mode specific logic - skip in advanced mode
        if pipeline_data is None:
            # Get the type of the selected column (simple mode only)
            column_type = cols_json[column_name]["type"]

            aggregation_description = html.Div(
                children=[
                    html.Hr(),
                    dmc.Tooltip(
                        children=dmc.Badge(
                            children="Aggregation description",
                            leftSection=DashIconify(
                                icon="mdi:information", color="white", width=20
                            ),
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
        else:
            # Advanced mode - use placeholder values
            column_type = "object"  # Generic placeholder type
            aggregation_description = None  # No aggregation description in advanced mode

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
        # Note: column_type already set above (either from cols_json in simple mode or placeholder in advanced mode)
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
            "access_token": TOKEN,
            "stepper": True,  # Show border during editing
            "build_frame": False,  # Don't build frame - return just the content for the card-body container
            "cols_json": cols_json,  # Pass cols_json for reference values
            # New individual style parameters
            "background_color": background_color,
            "title_color": title_color,
            "icon_name": icon_name,
            "icon_color": title_color,  # Use same as title for consistency
            "title_font_size": title_font_size,
            "metric_theme": None,  # Not using themes anymore for new cards
            # Advanced mode pipeline
            "pipeline": pipeline_data,  # None for simple mode, dict for advanced mode
        }

        if relevant_metadata:
            card_kwargs["dashboard_metadata"] = relevant_metadata

        logger.info(f"card_kwargs: {card_kwargs}")

        if parent_index:
            card_kwargs["parent_index"] = parent_index

        new_card_body = build_card(**card_kwargs)

        return new_card_body, aggregation_description, columns_description_df

    # PATTERN-MATCHING: Render callback for initial card value computation
    @app.callback(
        Output({"type": "card-value", "index": MATCH}, "children"),
        Output({"type": "card-metadata", "index": MATCH}, "data"),
        Input({"type": "card-trigger", "index": MATCH}, "data"),
        State({"type": "card-metadata", "index": MATCH}, "data"),
        prevent_initial_call=False,
    )
    def render_card_value_background(trigger_data, existing_metadata):
        """
        PATTERN-MATCHING: Render callback for initial card value computation.

        Triggers when card component mounts and trigger store is populated.
        Loads full dataset, computes aggregation value, stores reference value.

        Supports both simple mode (column + aggregation) and advanced mode (pipeline).

        Args:
            trigger_data: Data from card-trigger store containing all necessary params
            existing_metadata: Existing metadata from previous render (for idempotency check)

        Returns:
            tuple: (formatted_value, metadata_dict)
        """
        from bson import ObjectId
        from dash import no_update

        from depictio.api.v1.deltatables_utils import load_deltatable_lite

        logger.info(f"🔄 CARD RENDER: Starting value computation for trigger: {trigger_data}")

        # DEFENSIVE CHECK: Skip if already initialized (prevents spurious re-renders during Patch operations)
        # This prevents the 2-stage flash (unfiltered → filtered) when removing sibling components
        if existing_metadata and existing_metadata.get("reference_value") is not None:
            logger.info(
                "✅ CARD RENDER: Already initialized, skipping re-render "
                "(Patch operation or spurious Store update detected)"
            )
            return no_update, no_update

        if not trigger_data:
            logger.warning("No trigger data provided")
            return "...", {}

        # Extract parameters from trigger store
        wf_id = trigger_data.get("wf_id")
        dc_id = trigger_data.get("dc_id")
        access_token = trigger_data.get("access_token")
        cols_json = trigger_data.get("cols_json", {})

        # Check for pipeline data (advanced mode)
        pipeline_data = trigger_data.get("pipeline")

        # Simple mode parameters
        column_name = trigger_data.get("column_name")
        aggregation = trigger_data.get("aggregation")

        # Determine mode
        if pipeline_data:
            mode = "advanced"
            logger.info("🔬 ADVANCED MODE: Using CardOperationExecutor with pipeline")
        else:
            mode = "simple"
            logger.info("📊 SIMPLE MODE: Using compute_value for basic aggregation")

            # Validate required parameters for simple mode
            if not all([column_name, aggregation]):
                logger.error(
                    f"Simple mode missing required parameters - "
                    f"column_name: {column_name}, aggregation: {aggregation}"
                )
                return "Error", {"error": "Missing parameters"}

        # Validate common required parameters
        if not all([wf_id, dc_id]):
            logger.error(f"Missing required parameters - wf_id: {wf_id}, dc_id: {dc_id}")
            return "Error", {"error": "Missing parameters"}

        try:
            # Load full dataset
            logger.debug(f"Loading dataset for {wf_id}:{dc_id}")
            if isinstance(dc_id, str) and "--" in dc_id:
                # Joined data collection - keep as string
                data = load_deltatable_lite(
                    workflow_id=ObjectId(wf_id),
                    data_collection_id=dc_id,
                    TOKEN=access_token,
                )
            else:
                # Regular data collection - convert to ObjectId
                data = load_deltatable_lite(
                    workflow_id=ObjectId(wf_id),
                    data_collection_id=ObjectId(dc_id),
                    TOKEN=access_token,
                )

            logger.debug(f"Loaded data shape: {data.shape}")

            # Compute value based on mode
            if mode == "advanced":
                # Advanced mode: Execute pipeline
                from depictio.dash.modules.card_component.operations import CardOperationExecutor
                from depictio.models.models.card_operations import CardPipeline

                # Reconstruct CardPipeline from dict
                pipeline = CardPipeline(**pipeline_data)
                logger.debug(f"Pipeline: {pipeline.get_display_summary()}")

                # Execute pipeline
                executor = CardOperationExecutor()
                result = executor.execute_pipeline(data, pipeline)

                # Handle result - could be scalar or DataFrame
                if isinstance(result, (int, float, str)):
                    value = result
                    logger.debug(f"Pipeline result (scalar): {value}")
                else:
                    # DataFrame result (from groupby) - for now, just show row count
                    # TODO: Future enhancement - display grouped results in a table
                    value = len(result)
                    logger.warning(
                        f"Pipeline returned DataFrame with {len(result)} rows - "
                        f"showing row count for now"
                    )

            else:
                # Simple mode: Use existing compute_value function
                from depictio.dash.modules.card_component.utils import compute_value

                value = compute_value(data, column_name, aggregation)
                logger.debug(f"Computed value: {value}")

            # Format value
            try:
                if value is not None:
                    formatted_value = str(round(float(value), 4))
                else:
                    formatted_value = "N/A"
            except (ValueError, TypeError):
                formatted_value = str(value) if value is not None else "N/A"

            # Store metadata for patching callback
            metadata = {
                "reference_value": value,
                "mode": mode,
                "wf_id": wf_id,
                "dc_id": dc_id,
                "cols_json": cols_json,
            }

            # Add mode-specific metadata
            if mode == "simple":
                metadata["column_name"] = column_name
                metadata["aggregation"] = aggregation
            else:
                metadata["pipeline"] = pipeline_data

            logger.info(f"✅ CARD RENDER: Value computed successfully: {formatted_value}")
            return formatted_value, metadata

        except Exception as e:
            logger.error(f"❌ CARD RENDER: Error computing value: {e}", exc_info=True)
            return "Error", {"error": str(e)}

    # PATTERN-MATCHING: Patching callback for filter-based updates
    @app.callback(
        Output({"type": "card-value", "index": MATCH}, "children", allow_duplicate=True),
        Output({"type": "card-comparison", "index": MATCH}, "children", allow_duplicate=True),
        Input("interactive-values-store", "data"),
        State({"type": "card-metadata", "index": MATCH}, "data"),
        State({"type": "card-trigger", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def patch_card_with_filters(filters_data, metadata, trigger_data):
        """
        PATTERN-MATCHING: Patching callback for filter-based card updates.

        Triggers when interactive filters change. Applies filters to data,
        computes new value, and creates comparison with reference value.

        Args:
            filters_data: Interactive filter selections
            metadata: Card metadata with reference_value
            trigger_data: Original trigger data with card config

        Returns:
            tuple: (formatted_value, comparison_components)
        """
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import load_deltatable_lite
        from depictio.dash.modules.card_component.utils import compute_value

        logger.info("🔄 CARD PATCH: Applying filters to card")

        if not metadata or not trigger_data:
            logger.warning("Missing metadata or trigger data")
            return "...", []

        # Extract parameters
        wf_id = trigger_data.get("wf_id")
        dc_id = trigger_data.get("dc_id")
        column_name = trigger_data.get("column_name")
        aggregation = trigger_data.get("aggregation")
        access_token = trigger_data.get("access_token")
        reference_value = metadata.get("reference_value")

        if not all([wf_id, dc_id, column_name, aggregation]):
            logger.error("Missing required parameters for patching")
            return "Error", []

        try:
            # Extract interactive components from filters_data
            # filters_data format: {"interactive_components_values": [component1, component2, ...]}
            metadata_list = (
                filters_data.get("interactive_components_values") if filters_data else None
            )

            # MULTI-DC SUPPORT: Group filters by DC to detect cross-DC filtering scenarios
            filters_by_dc = {}
            if metadata_list:
                for component in metadata_list:
                    component_dc = str(component.get("metadata", {}).get("dc_id"))
                    if component_dc not in filters_by_dc:
                        filters_by_dc[component_dc] = []
                    filters_by_dc[component_dc].append(component)

                logger.debug(
                    f"🔍 CARD PATCH: {len(metadata_list)} total filters across "
                    f"{len(filters_by_dc)} DC(s): {list(filters_by_dc.keys())}"
                )

            # CRITICAL FIX: Filter out non-table DCs (MultiQC, JBrowse2) from filters_by_dc
            # These DC types don't support deltatable loading and would cause 404 errors
            filters_by_dc_table_only = {}
            for dc_key, dc_filters in filters_by_dc.items():
                if dc_filters:  # Has filters, check DC type
                    component_dc_config = dc_filters[0].get("metadata", {}).get("dc_config", {})
                    dc_type = component_dc_config.get("type", "table")
                    if dc_type == "table":
                        filters_by_dc_table_only[dc_key] = dc_filters
                    else:
                        logger.info(
                            f"⏭️ Excluding DC {dc_key} from filtering (type: {dc_type}) - "
                            f"non-table DCs don't support deltatable operations"
                        )
            filters_by_dc = filters_by_dc_table_only

            # Check if card's DC is MultiQC/JBrowse2 - if so, skip filtering entirely
            dc_config = trigger_data.get("dc_config", {})
            card_dc_type = dc_config.get("type", "table")
            if card_dc_type in ["multiqc", "jbrowse2"]:
                logger.info(
                    f"⏭️ CARD PATCH SKIP: Card DC type '{card_dc_type}' does not support filtering - "
                    f"returning reference value"
                )
                # Return reference value with no comparison
                if reference_value is not None:
                    try:
                        formatted_value = str(round(float(reference_value), 4))
                    except (ValueError, TypeError):
                        formatted_value = str(reference_value)
                else:
                    formatted_value = "N/A"
                return formatted_value, []

            # Determine if filters have active (non-empty) values
            has_active_filters = False
            if metadata_list:
                for component in metadata_list:
                    value = component.get("value")
                    if value is not None and value != [] and value != "" and value is not False:
                        has_active_filters = True
                        break

            if has_active_filters:
                logger.info("🔍 Active filters detected - loading filtered data")
            else:
                logger.info("🔄 No active filters - loading ALL unfiltered data")

            # AUTO-DETECT: Determine if we need to join DCs
            # Two scenarios:
            # 1. Same-DC: Card's DC has filters → Apply filters directly
            # 2. Joined-DC: Card's DC is joined with DC(s) that have filters → Join needed
            card_dc_str = str(dc_id)
            has_filters_for_card_dc = card_dc_str in filters_by_dc

            # Get join config to check DC relationships
            join_config = dc_config.get("join", {})

            # Determine if we need to perform a join
            needs_join = False
            if not has_filters_for_card_dc and len(filters_by_dc) > 0:
                # Filters are on different DC(s) - need to join with card DC
                needs_join = True
                logger.info("🔍 Filters on different DC(s), join required")

            logger.info(f"🔍 Card DC: {card_dc_str}")
            logger.info(f"🔍 Has filters for card DC: {has_filters_for_card_dc}")
            logger.info(f"🔍 Needs join: {needs_join}")
            logger.info(f"🔍 Filters on {len(filters_by_dc)} DC(s)")

            from depictio.api.v1.deltatables_utils import get_join_tables, load_deltatable_lite

            # If no explicit join config but join is needed, query workflow join tables
            if needs_join and (not join_config or not join_config.get("on_columns")):
                logger.info("🔍 No explicit join config in DC - querying workflow join tables")
                workflow_join_tables = get_join_tables(wf_id, access_token)

                if workflow_join_tables and wf_id in workflow_join_tables:
                    wf_joins = workflow_join_tables[wf_id]
                    logger.debug(f"🔍 Workflow join tables: {list(wf_joins.keys())}")

                    # Search for join between card DC and any filter DC
                    # Join keys are formatted as "dc1--dc2"
                    for filter_dc in filters_by_dc.keys():
                        # Try both directions: card--filter and filter--card
                        join_key_1 = f"{card_dc_str}--{filter_dc}"
                        join_key_2 = f"{filter_dc}--{card_dc_str}"

                        if join_key_1 in wf_joins:
                            join_config = wf_joins[join_key_1]
                            logger.info(f"✅ Found join config in workflow tables: {join_key_1}")
                            logger.debug(f"   Join config: {join_config}")
                            break
                        elif join_key_2 in wf_joins:
                            join_config = wf_joins[join_key_2]
                            logger.info(f"✅ Found join config in workflow tables: {join_key_2}")
                            logger.debug(f"   Join config: {join_config}")
                            break

                    if not join_config or not join_config.get("on_columns"):
                        logger.warning(
                            "⚠️ No join config found in workflow tables for card DC and filter DCs"
                        )
                else:
                    logger.warning(f"⚠️ No workflow join tables found for workflow {wf_id}")

            # Determine the filtering path
            # JOINED-DC: Filters on different DCs + join config available
            # SAME-DC: Filters on card DC only, or multiple DCs but no join config
            use_joined_path = needs_join and join_config and join_config.get("on_columns")

            # If filters on multiple DCs but no join config, fall back to SAME-DC
            if len(filters_by_dc) > 1 and not use_joined_path:
                logger.warning(
                    f"⚠️ Filters on {len(filters_by_dc)} DCs but no join config - "
                    f"falling back to SAME-DC filtering (card DC only)"
                )
                # Keep only card DC filters
                if card_dc_str in filters_by_dc:
                    filters_by_dc = {card_dc_str: filters_by_dc[card_dc_str]}
                else:
                    filters_by_dc = {}

            if use_joined_path:
                # JOINED-DC PATH: Manual loading + merge_multiple_dataframes
                logger.info(
                    f"🔗 JOINED-DC FILTERING: Loading and joining DCs "
                    f"(card DC + {len(filters_by_dc)} filter DC(s))"
                )

                from depictio.api.v1.deltatables_utils import merge_multiple_dataframes

                # Include card's DC in the join if it's not already in filters_by_dc
                if card_dc_str not in filters_by_dc:
                    logger.info(f"📂 Adding card DC {card_dc_str} to join (no filters)")
                    filters_by_dc[card_dc_str] = []

                # Extract DC metatypes from component metadata (already cached in Store)
                dc_metatypes = {}
                for dc_key, dc_filters in filters_by_dc.items():
                    if dc_filters:
                        component_dc_config = dc_filters[0].get("metadata", {}).get("dc_config", {})
                        metatype = component_dc_config.get("metatype")
                        if metatype:
                            dc_metatypes[dc_key] = metatype
                            logger.debug(
                                f"📋 DC {dc_key} metatype: {metatype} (from cached metadata)"
                            )

                # If card DC not in dc_metatypes, get from trigger_data
                if card_dc_str not in dc_metatypes:
                    card_metatype = dc_config.get("metatype")
                    if card_metatype:
                        dc_metatypes[card_dc_str] = card_metatype
                        logger.debug(f"📋 Card DC {card_dc_str} metatype: {card_metatype}")

                # Load each DC with all columns (rely on cache for performance)
                dataframes = {}
                for dc_key, dc_filters in filters_by_dc.items():
                    if has_active_filters:
                        # Filter out components with empty values
                        active_filters = [
                            c for c in dc_filters if c.get("value") not in [None, [], "", False]
                        ]
                        logger.info(
                            f"📂 Loading DC {dc_key} with {len(active_filters)} active filters"
                        )
                        metadata_to_pass = active_filters
                    else:
                        # Clearing filters - load ALL unfiltered data
                        logger.info(f"📂 Loading DC {dc_key} with NO filters (clearing)")
                        metadata_to_pass = []

                    dc_df = load_deltatable_lite(
                        ObjectId(wf_id),
                        ObjectId(dc_key),
                        metadata=metadata_to_pass,
                        TOKEN=access_token,
                        select_columns=None,  # Load all columns, rely on cache
                    )
                    dataframes[dc_key] = dc_df
                    logger.info(f"   Loaded {dc_df.height:,} rows × {dc_df.width} columns")

                # Build join instructions for merge_multiple_dataframes
                dc_ids = sorted(filters_by_dc.keys())
                join_instructions = [
                    {
                        "left": dc_ids[0],
                        "right": dc_ids[1],
                        "how": join_config.get("how", "inner"),
                        "on": join_config.get("on_columns", []),
                    }
                ]

                logger.info(f"🔗 Joining DCs: {join_instructions}")
                logger.info(f"📋 DC metatypes for join: {dc_metatypes}")

                # Merge DataFrames with table type awareness
                data = merge_multiple_dataframes(
                    dataframes=dataframes,
                    join_instructions=join_instructions,
                    dc_metatypes=dc_metatypes,
                )

                logger.info(f"📊 Joined result: {data.height:,} rows × {data.width} columns")

            else:
                # SAME-DC PATH: Card's DC has filters, apply them directly
                relevant_filters = filters_by_dc.get(card_dc_str, [])

                if has_active_filters:
                    # Filter out components with empty values
                    active_filters = [
                        c for c in relevant_filters if c.get("value") not in [None, [], "", False]
                    ]
                    logger.info(
                        f"📄 SAME-DC filtering - applying {len(active_filters)} active filters to card DC"
                    )
                    metadata_to_pass = active_filters
                else:
                    # Clearing filters - load ALL unfiltered data
                    logger.info("📄 SAME-DC clearing filters - loading ALL unfiltered data")
                    metadata_to_pass = []

                logger.info(f"📂 Loading data: {wf_id}:{dc_id} ({len(metadata_to_pass)} filters)")

                data = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id),
                    metadata=metadata_to_pass,
                    TOKEN=access_token,
                )

                logger.info(f"📊 Loaded {data.height:,} rows × {data.width} columns")

            # else:
            #     # SINGLE-DC PATH: Standard filtering with load_deltatable_lite
            #     logger.debug(f"📄 SINGLE-DC CARD: Using standard load for DC {dc_id}")

            #     # Filter metadata to only include filters for THIS card's DC
            #     filtered_metadata = filters_by_dc.get(str(dc_id), []) if filters_by_dc else None

            #     if filtered_metadata:
            #         logger.debug(
            #             f"🔍 Applying {len(filtered_metadata)} filter(s) to card's DC {dc_id}"
            #         )
            #     else:
            #         logger.debug("🔍 No filters for card's DC - loading unfiltered data")

            #     # Load dataset with filters applied
            #     if isinstance(dc_id, str) and "--" in dc_id:
            #         data = load_deltatable_lite(
            #             workflow_id=ObjectId(wf_id),
            #             data_collection_id=dc_id,
            #             metadata=filtered_metadata,
            #             TOKEN=access_token,
            #         )
            #     else:
            #         data = load_deltatable_lite(
            #             workflow_id=ObjectId(wf_id),
            #             data_collection_id=ObjectId(dc_id),
            #             metadata=filtered_metadata,
            #             TOKEN=access_token,
            #         )

            logger.debug("Loaded filtered data")

            # Compute new value on filtered data
            current_value = compute_value(data, column_name, aggregation)
            logger.debug(f"Computed filtered value: {current_value}")

            # Format current value
            try:
                if current_value is not None:
                    formatted_value = str(round(float(current_value), 4))
                    current_val = float(current_value)
                else:
                    formatted_value = "N/A"
                    current_val = None
            except (ValueError, TypeError):
                formatted_value = "Error"
                current_val = None

            # Get adaptive trend colors based on card background
            # Convert empty string to None for proper handling
            background_color = trigger_data.get("background_color") or None
            trend_colors = get_adaptive_trend_colors(background_color)
            logger.debug(
                f"Using adaptive trend colors for background '{background_color}': {trend_colors}"
            )

            # Create comparison components
            comparison_components = []
            if reference_value is not None and current_val is not None:
                try:
                    ref_val = float(reference_value)

                    # Calculate percentage change
                    if ref_val != 0:
                        change_pct = ((current_val - ref_val) / ref_val) * 100
                        if change_pct > 0:
                            comparison_text = f"+{change_pct:.1f}% vs unfiltered ({ref_val})"
                            comparison_color = trend_colors["positive"]
                            comparison_icon = "mdi:trending-up"
                        elif change_pct < 0:
                            comparison_text = f"{change_pct:.1f}% vs unfiltered ({ref_val})"
                            comparison_color = trend_colors["negative"]
                            comparison_icon = "mdi:trending-down"
                        else:
                            comparison_text = f"Same as unfiltered ({ref_val})"
                            comparison_color = trend_colors["neutral"]
                            comparison_icon = "mdi:trending-neutral"
                    else:
                        comparison_text = f"Reference: {ref_val}"
                        comparison_color = trend_colors["neutral"]
                        comparison_icon = "mdi:information-outline"

                    # Build comparison UI
                    comparison_components = [
                        DashIconify(icon=comparison_icon, width=14, color=comparison_color),
                        dmc.Text(
                            comparison_text,
                            size="xs",
                            c=comparison_color,
                            fw="normal",
                            style={"margin": "0"},
                        ),
                    ]
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error creating comparison: {e}")

            logger.info(f"✅ CARD PATCH: Value updated successfully: {formatted_value}")
            return formatted_value, comparison_components

        except Exception as e:
            logger.error(f"❌ CARD PATCH: Error applying filters: {e}", exc_info=True)
            return "Error", []


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
                                html.Hr(),
                                # Mode toggle: Simple vs Advanced
                                dmc.Stack(
                                    [
                                        dmc.Text("Metric Configuration", size="sm", fw="bold"),
                                        dmc.SegmentedControl(
                                            id={
                                                "type": "card-metric-mode",
                                                "index": id["index"],
                                            },
                                            data=[
                                                {"label": "Simple", "value": "simple"},
                                                {"label": "Advanced", "value": "advanced"},
                                            ],
                                            value="simple",
                                            fullWidth=True,
                                        ),
                                        # Simple mode container (always present, visibility toggled)
                                        html.Div(
                                            id={
                                                "type": "card-simple-container",
                                                "index": id["index"],
                                            },
                                            style={"display": "block"},
                                            children=[
                                                # Dropdown for the column selection
                                                dmc.Select(
                                                    label="Select your column",
                                                    id={
                                                        "type": "card-dropdown-column",
                                                        "index": id["index"],
                                                    },
                                                    data=[
                                                        {"label": e, "value": e} for e in df.columns
                                                    ],
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
                                            ],
                                        ),
                                        # Advanced mode container (always present, visibility toggled)
                                        # Pre-create with empty columns - will be populated with real columns when activated
                                        html.Div(
                                            id={
                                                "type": "card-advanced-container",
                                                "index": id["index"],
                                            },
                                            style={"display": "none"},
                                            children=create_advanced_stepper_ui(id["index"], []),
                                        ),
                                    ],
                                    gap="sm",
                                ),
                                html.Hr(),
                                # Individual style controls
                                dmc.Stack(
                                    [
                                        dmc.Text("Card Styling", size="sm", fw="bold"),
                                        dmc.ColorInput(
                                            label="Background Color",
                                            description="Card background color (leave empty for auto theme)",
                                            id={
                                                "type": "card-color-background",
                                                "index": id["index"],
                                            },
                                            value="",
                                            format="hex",
                                            placeholder="Auto (follows theme)",
                                            swatches=[
                                                colors["purple"],
                                                colors["blue"],
                                                colors["teal"],
                                                colors["green"],
                                                colors["yellow"],
                                                colors["orange"],
                                                colors["pink"],
                                                colors["red"],
                                                colors["grey"],
                                            ],
                                        ),
                                        dmc.ColorInput(
                                            label="Title Color",
                                            description="Card title and value text color (leave empty for auto theme)",
                                            id={
                                                "type": "card-color-title",
                                                "index": id["index"],
                                            },
                                            value="",
                                            format="hex",
                                            placeholder="Auto (follows theme)",
                                            swatches=[
                                                colors["purple"],
                                                colors["blue"],
                                                colors["teal"],
                                                colors["green"],
                                                colors["yellow"],
                                                colors["orange"],
                                                colors["pink"],
                                                colors["red"],
                                                colors["grey"],
                                                colors["black"],
                                            ],
                                        ),
                                        dmc.Select(
                                            label="Icon",
                                            description="Select an icon for your card",
                                            id={
                                                "type": "card-icon-selector",
                                                "index": id["index"],
                                            },
                                            data=[
                                                {
                                                    "label": "📊 Chart Line",
                                                    "value": "mdi:chart-line",
                                                },
                                                {
                                                    "label": "🌡️ Thermometer",
                                                    "value": "mdi:thermometer",
                                                },
                                                {"label": "💧 Water", "value": "mdi:water"},
                                                {"label": "🧪 Flask", "value": "mdi:flask"},
                                                {
                                                    "label": "💨 Air Filter",
                                                    "value": "mdi:air-filter",
                                                },
                                                {"label": "⚡ Flash", "value": "mdi:flash"},
                                                {"label": "📊 Gauge", "value": "mdi:gauge"},
                                                {
                                                    "label": "💦 Water Percent",
                                                    "value": "mdi:water-percent",
                                                },
                                                {"label": "📏 Ruler", "value": "mdi:ruler"},
                                                {"label": "🌫️ Blur", "value": "mdi:blur"},
                                                {"label": "🌿 Leaf", "value": "mdi:leaf"},
                                                {
                                                    "label": "✅ Check Circle",
                                                    "value": "mdi:check-circle",
                                                },
                                                {"label": "🎯 Target", "value": "mdi:target"},
                                                {
                                                    "label": "🎪 Bullseye Arrow",
                                                    "value": "mdi:bullseye-arrow",
                                                },
                                                {
                                                    "label": "⚗️ Flask Empty",
                                                    "value": "mdi:flask-empty",
                                                },
                                                {
                                                    "label": "🛡️ Shield Check",
                                                    "value": "mdi:shield-check",
                                                },
                                                {
                                                    "label": "📈 Chart Bell Curve",
                                                    "value": "mdi:chart-bell-curve",
                                                },
                                                {
                                                    "label": "🔗 Scatter Plot",
                                                    "value": "mdi:scatter-plot",
                                                },
                                                {
                                                    "label": "⚠️ Alert Circle",
                                                    "value": "mdi:alert-circle",
                                                },
                                                {"label": "🔢 Counter", "value": "mdi:counter"},
                                                {"label": "📡 Sine Wave", "value": "mdi:sine-wave"},
                                                {"label": "🧬 Beaker", "value": "mdi:beaker"},
                                                {
                                                    "label": "⚙️ Speedometer",
                                                    "value": "mdi:speedometer",
                                                },
                                                {
                                                    "label": "⚡ Flash Outline",
                                                    "value": "mdi:flash-outline",
                                                },
                                                {
                                                    "label": "📊 Trending Up",
                                                    "value": "mdi:trending-up",
                                                },
                                                {"label": "🧬 DNA", "value": "mdi:dna"},
                                                {
                                                    "label": "🗺️ Map Marker Path",
                                                    "value": "mdi:map-marker-path",
                                                },
                                                {
                                                    "label": "📋 Content Copy",
                                                    "value": "mdi:content-copy",
                                                },
                                            ],
                                            value="mdi:chart-line",
                                            searchable=True,
                                            clearable=False,
                                        ),
                                        dmc.Select(
                                            label="Title Font Size",
                                            description="Font size for card title",
                                            id={
                                                "type": "card-title-font-size",
                                                "index": id["index"],
                                            },
                                            data=[
                                                {"label": "Extra Small", "value": "xs"},
                                                {"label": "Small", "value": "sm"},
                                                {"label": "Medium", "value": "md"},
                                                {"label": "Large", "value": "lg"},
                                                {"label": "Extra Large", "value": "xl"},
                                            ],
                                            value="md",
                                            clearable=False,
                                        ),
                                    ],
                                    gap="sm",
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

    # Add Store component for pipeline state
    pipeline_store = dcc.Store(
        id={"type": "card-pipeline-store", "index": id["index"]},
        data=None,  # Will be populated by pipeline builder callback
    )

    card_row = [
        dmc.Stack(
            [main_layout, html.Hr(), bottom_section, pipeline_store],
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


# ============================================================================
# HELPER FUNCTIONS FOR ADVANCED CARD OPERATIONS UI
# ============================================================================


def create_simple_config_ui(index, df_columns):
    """
    Create simple mode UI: column and aggregation dropdowns.

    Args:
        index: Component index for pattern-matching IDs
        df_columns: List of available columns

    Returns:
        List of DMC components for simple configuration
    """
    return [
        dmc.Select(
            label="Select your column",
            id={
                "type": "card-dropdown-column",
                "index": index,
            },
            data=[{"label": e, "value": e} for e in df_columns],
            value=None,
        ),
        dmc.Select(
            label="Select your aggregation method",
            id={
                "type": "card-dropdown-aggregation",
                "index": index,
            },
            value=None,
        ),
    ]


def create_advanced_stepper_ui(index, df_columns):
    """
    Create advanced mode UI with stepper on left and config on right (side by side).

    Args:
        index: Component index for pattern-matching IDs
        df_columns: List of available columns

    Returns:
        Grid layout with stepper (left) and config panels (right)
    """
    return dmc.Paper(
        [
            dmc.Text("Advanced Pipeline Configuration", size="sm", fw="bold", mb="xs"),
            dmc.Text(
                "Build a multi-step operation pipeline: Filter → GroupBy → Aggregate",
                size="xs",
                c="gray",
                mb="md",
            ),
            # Grid with stepper on left (vertical) and config on right (vertical)
            dmc.Grid(
                [
                    # Left column: Vertical stepper
                    dmc.GridCol(
                        dmc.Stepper(
                            id={"type": "card-operation-stepper", "index": index},
                            active=0,
                            orientation="vertical",
                            children=[
                                dmc.StepperStep(
                                    label="Step 1",
                                    description="Filter data",
                                ),
                                dmc.StepperStep(
                                    label="Step 2",
                                    description="Group by columns",
                                ),
                                dmc.StepperStep(
                                    label="Step 3",
                                    description="Aggregate",
                                ),
                                dmc.StepperCompleted(
                                    children=dmc.Text("Pipeline ready!", size="sm", c="green")
                                ),
                            ],
                        ),
                        span=4,
                    ),
                    # Right column: Config panels for each step
                    dmc.GridCol(
                        dmc.Stack(
                            [
                                # Step 1 config (Filter)
                                html.Div(
                                    id={"type": "card-step-1-panel", "index": index},
                                    children=create_operation_step_ui(index, step_num=1),
                                    style={"display": "block"},
                                ),
                                # Step 2 config (GroupBy)
                                html.Div(
                                    id={"type": "card-step-2-panel", "index": index},
                                    children=create_operation_step_ui(index, step_num=2),
                                    style={"display": "none"},
                                ),
                                # Step 3 config (Aggregation)
                                html.Div(
                                    id={"type": "card-step-3-panel", "index": index},
                                    children=create_aggregation_step_ui(index),
                                    style={"display": "none"},
                                ),
                                # Completed panel (Summary)
                                html.Div(
                                    id={"type": "card-completed-panel", "index": index},
                                    style={"display": "none"},
                                    children=[
                                        dmc.Alert(
                                            "Pipeline configured successfully!",
                                            title="Ready",
                                            color="green",
                                            icon=DashIconify(icon="mdi:check-circle"),
                                        ),
                                        html.Div(
                                            id={"type": "card-pipeline-summary", "index": index},
                                            children="Pipeline summary will appear here",
                                        ),
                                    ],
                                ),
                            ],
                            gap="sm",
                        ),
                        span=8,
                    ),
                ],
                gutter="md",
            ),
            # Navigation buttons for stepper
            dmc.Group(
                [
                    dmc.Button(
                        "Back",
                        id={"type": "card-stepper-back", "index": index},
                        variant="default",
                    ),
                    dmc.Button(
                        "Next",
                        id={"type": "card-stepper-next", "index": index},
                        variant="filled",
                    ),
                ],
                justify="flex-end",
                mt="md",
            ),
        ],
        withBorder=True,
        p="md",
    )


def create_operation_step_ui(index, step_num):
    """
    Create UI for a single operation step (Filter or GroupBy or Skip).

    Pre-creates both filter and groupby config components as hidden elements
    to ensure all callback State dependencies exist from the start.

    Args:
        index: Component index
        step_num: Step number (1 or 2)

    Returns:
        DMC components for operation selection
    """
    # Pre-create hidden filter components (for callback State dependencies)
    hidden_filter_components = html.Div(
        id={"type": f"card-filter-config-{step_num}", "index": index},
        style={"display": "none"},
        children=[
            dmc.Select(
                label="Column",
                id={"type": f"card-filter-column-{step_num}", "index": index},
                data=[],
                value=None,
            ),
            dmc.Select(
                label="Operator",
                id={"type": f"card-filter-operator-{step_num}", "index": index},
                data=[
                    {"label": "Equals", "value": "=="},
                    {"label": "Not equals", "value": "!="},
                    {"label": "Greater than", "value": ">"},
                    {"label": "Less than", "value": "<"},
                    {"label": "Greater or equal", "value": ">="},
                    {"label": "Less or equal", "value": "<="},
                    {"label": "Contains", "value": "contains"},
                    {"label": "In list", "value": "in"},
                    {"label": "Is null", "value": "is_null"},
                    {"label": "Not null", "value": "not_null"},
                ],
                value=None,
            ),
            dmc.TextInput(
                label="Value",
                id={"type": f"card-filter-value-{step_num}", "index": index},
                value=None,
            ),
        ],
    )

    # Pre-create hidden groupby components (for callback State dependencies)
    hidden_groupby_components = html.Div(
        id={"type": f"card-groupby-config-{step_num}", "index": index},
        style={"display": "none"},
        children=[
            dmc.MultiSelect(
                label="Group By Columns",
                id={"type": f"card-groupby-columns-{step_num}", "index": index},
                data=[],
                value=None,
            ),
        ],
    )

    return dmc.Stack(
        [
            dmc.SegmentedControl(
                id={"type": f"card-operation-type-{step_num}", "index": index},
                data=[
                    {"label": "Skip", "value": "skip"},
                    {"label": "Filter", "value": "filter"},
                    {"label": "GroupBy", "value": "groupby"},
                ],
                value="skip",
                fullWidth=True,
            ),
            # Dynamic configuration container based on operation type
            html.Div(
                id={"type": f"card-operation-config-{step_num}", "index": index},
                children=[],  # Will be populated by callback (toggles visibility)
            ),
            # Hidden pre-created components for callback State dependencies
            hidden_filter_components,
            hidden_groupby_components,
        ],
        gap="sm",
    )


def create_aggregation_step_ui(index):
    """
    Create UI for final aggregation step (always required).

    Pre-creates the column selector as a hidden element to ensure
    callback State dependency exists from the start.

    Args:
        index: Component index

    Returns:
        DMC components for aggregation configuration
    """
    # Pre-create hidden column selector (for callback State dependency)
    # Now placed inside the container div so visibility toggle works correctly
    hidden_column_selector = html.Div(
        id={"type": "card-final-aggregation-column-hidden", "index": index},
        style={"display": "none"},
        children=[
            dmc.Select(
                label="Column",
                description="Select column to aggregate",
                id={"type": "card-final-aggregation-column", "index": index},
                data=[],
                value=None,
                searchable=True,
                required=True,
            ),
        ],
    )

    return dmc.Stack(
        [
            dmc.Select(
                label="Aggregation Method",
                description="How to compute the final metric value",
                id={"type": "card-final-aggregation-method", "index": index},
                data=[
                    {"label": "Count", "value": "count"},
                    {"label": "Sum", "value": "sum"},
                    {"label": "Mean", "value": "mean"},
                    {"label": "Median", "value": "median"},
                    {"label": "Min", "value": "min"},
                    {"label": "Max", "value": "max"},
                    {"label": "Std Dev", "value": "std"},
                    {"label": "Variance", "value": "var"},
                    {"label": "Unique Count", "value": "nunique"},
                ],
                value="count",
                required=True,
            ),
            # Column selector (hidden by default, shown when aggregation method needs it)
            hidden_column_selector,
        ],
        gap="sm",
    )


def create_filter_config_ui(index, step_num, df_columns):
    """
    Create filter operation configuration panel.

    Args:
        index: Component index
        step_num: Step number
        df_columns: Available columns

    Returns:
        DMC components for filter configuration
    """
    return dmc.Stack(
        [
            dmc.Select(
                label="Column",
                description="Column to filter on",
                id={"type": f"card-filter-column-{step_num}", "index": index},
                data=[{"label": c, "value": c} for c in df_columns],
                searchable=True,
            ),
            dmc.Select(
                label="Operator",
                description="Comparison operator",
                id={"type": f"card-filter-operator-{step_num}", "index": index},
                data=[
                    {"label": "Equals", "value": "=="},
                    {"label": "Not equals", "value": "!="},
                    {"label": "Greater than", "value": ">"},
                    {"label": "Less than", "value": "<"},
                    {"label": "Greater or equal", "value": ">="},
                    {"label": "Less or equal", "value": "<="},
                    {"label": "Contains", "value": "contains"},
                    {"label": "In list", "value": "in"},
                    {"label": "Is null", "value": "is_null"},
                    {"label": "Not null", "value": "not_null"},
                ],
            ),
            dmc.TextInput(
                label="Value",
                description="Filter value (not needed for null checks)",
                id={"type": f"card-filter-value-{step_num}", "index": index},
                placeholder="Enter value...",
            ),
        ],
        gap="xs",
    )


def create_groupby_config_ui(index, step_num, df_columns):
    """
    Create groupby operation configuration panel.

    Args:
        index: Component index
        step_num: Step number
        df_columns: Available columns

    Returns:
        DMC components for groupby configuration
    """
    return dmc.Stack(
        [
            dmc.MultiSelect(
                label="Group By Columns",
                description="Select one or more columns to group by",
                id={"type": f"card-groupby-columns-{step_num}", "index": index},
                data=[{"label": c, "value": c} for c in df_columns],
                searchable=True,
                required=True,
                placeholder="Select columns...",
            ),
            dmc.Alert(
                "Data will be grouped by selected columns before aggregation",
                color="blue",
                icon=DashIconify(icon="mdi:information"),
            ),
        ],
        gap="xs",
    )
