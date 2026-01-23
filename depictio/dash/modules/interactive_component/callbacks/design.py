"""
Interactive Component - Design/Edit Mode Callbacks.

This module contains callbacks for editing or designing interactive components.
These callbacks are lazy-loaded when entering edit mode to reduce initial app startup time.

Callbacks:
    pre_populate_interactive_settings_for_edit: Pre-fill design form in edit mode.
    update_aggregation_options: Populate method dropdown based on column selection.
    update_preview_component: Update component preview based on form inputs.
    update_stored_metadata: Update stored metadata for save functionality.
"""

from typing import Any, Optional

import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.utils import get_columns_from_data_collection

# Table cell style constants for columns description
_TABLE_CELL_STYLE: dict[str, Any] = {
    "textAlign": "center",
    "fontSize": "11px",
    "maxWidth": "150px",
}

_TABLE_HEADER_STYLE: dict[str, Any] = {
    "textAlign": "center",
    "fontSize": "11px",
    "fontWeight": "bold",
}


def _create_no_update_tuple(count: int) -> tuple:
    """
    Create a tuple of dash.no_update values.

    Args:
        count: Number of no_update values to include.

    Returns:
        Tuple of dash.no_update values.
    """
    import dash

    return tuple(dash.no_update for _ in range(count))


def _create_interactive_description(
    aggregation_value: str, column_type: str, agg_functions: dict
) -> html.Div:
    """
    Create the interactive component description tooltip element.

    Args:
        aggregation_value: Selected aggregation method.
        column_type: Type of the selected column.
        agg_functions: Dictionary of available aggregation functions.

    Returns:
        html.Div containing the description tooltip.
    """
    try:
        description_text = agg_functions[str(column_type)]["input_methods"][aggregation_value][
            "description"
        ]
    except KeyError:
        description_text = (
            f"Description not available for {aggregation_value} on {column_type} data"
        )

    return html.Div(
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


def _create_columns_description_table(cols_json: dict) -> Optional[dmc.Table]:
    """
    Create a table showing column descriptions.

    Args:
        cols_json: Dictionary of column metadata.

    Returns:
        dmc.Table with column descriptions, or None if creation fails.
    """
    try:
        data_columns_df = [
            {"column": c, "description": cols_json[c]["description"]}
            for c in cols_json
            if cols_json[c]["description"] is not None
        ]

        table_rows = [
            dmc.TableTr(
                [
                    dmc.TableTd(row["column"], style=_TABLE_CELL_STYLE),
                    dmc.TableTd(row["description"], style=_TABLE_CELL_STYLE),
                ]
            )
            for row in data_columns_df
        ]

        return dmc.Table(
            [
                dmc.TableThead(
                    [
                        dmc.TableTr(
                            [
                                dmc.TableTh("Column", style=_TABLE_HEADER_STYLE),
                                dmc.TableTh("Description", style=_TABLE_HEADER_STYLE),
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
        return None


def _build_preview_by_type(
    aggregation_value: str,
    column_value: str,
    df: Any,
) -> Any:
    """
    Build the preview component based on the aggregation type.

    Args:
        aggregation_value: Selected aggregation method (Select, MultiSelect, etc.).
        column_value: Name of the selected column.
        df: DataFrame containing the data.

    Returns:
        Dash Mantine component for the preview.
    """
    if aggregation_value in ["Select", "MultiSelect", "SegmentedControl"]:
        unique_vals = df[column_value].unique()
        if hasattr(unique_vals, "to_list"):
            unique_vals_list = unique_vals.to_list()
        elif hasattr(unique_vals, "tolist"):
            unique_vals_list = unique_vals.tolist()
        else:
            unique_vals_list = list(unique_vals)

        options = [str(val) for val in unique_vals_list if val is not None][:20]

        if aggregation_value == "Select":
            return dmc.Select(
                data=[{"label": opt, "value": opt} for opt in options],
                placeholder=f"Select {column_value}",
                style={"width": "100%"},
            )
        elif aggregation_value == "MultiSelect":
            return dmc.MultiSelect(
                data=[{"label": opt, "value": opt} for opt in options],
                placeholder=f"Select {column_value} (multiple)",
                style={"width": "100%"},
            )
        else:  # SegmentedControl
            return dmc.SegmentedControl(
                data=options[:5],
                fullWidth=True,
            )

    elif aggregation_value in ["Slider", "RangeSlider"]:
        col_min = float(df[column_value].min())
        col_max = float(df[column_value].max())

        if aggregation_value == "Slider":
            return dmc.Slider(
                min=col_min,
                max=col_max,
                value=col_min,
                style={"width": "100%"},
            )
        else:  # RangeSlider
            return dmc.RangeSlider(
                min=col_min,
                max=col_max,
                value=(col_min, col_max),
                style={"width": "100%"},
            )

    elif aggregation_value == "DateRangePicker":
        return dmc.DatePickerInput(
            type="range",
            placeholder="Select date range",
            style={"width": "100%"},
        )

    return dmc.Text(f"Preview for {aggregation_value}", c="gray")


def _wrap_preview_with_title(
    preview_component: Any,
    title: str,
    icon_name: str,
    color_value: str,
    title_size: str,
) -> dmc.Stack:
    """
    Wrap a preview component with its title and icon.

    Args:
        preview_component: The preview component to wrap.
        title: Title text to display.
        icon_name: Name of the icon to display.
        color_value: Color for the icon.
        title_size: Size of the title text.

    Returns:
        dmc.Stack containing the titled preview.
    """
    return dmc.Stack(
        [
            dmc.Group(
                [
                    DashIconify(
                        icon=icon_name or "bx:slider-alt",
                        width=24,
                        color=color_value if color_value else None,
                    ),
                    dmc.Text(title, size=title_size, fw="bold"),
                ],
                gap="xs",
            ),
            preview_component,
        ],
        gap="sm",
    )


def register_interactive_design_callbacks(app) -> None:
    """
    Register design/edit mode callbacks for interactive component.

    This function registers all callbacks needed for the interactive component
    design interface, including form pre-population in edit mode, method dropdown
    updates, preview generation, and metadata storage.

    Args:
        app: Dash application instance.
    """

    # Pre-populate interactive settings in edit mode (edit page, not stepper)
    @app.callback(
        Output({"type": "input-title", "index": MATCH}, "value"),
        Output({"type": "input-dropdown-column", "index": MATCH}, "value"),
        Output({"type": "input-dropdown-method", "index": MATCH}, "value"),
        # COMMENTED OUT: Scale and marks outputs (UI elements removed)
        # Output({"type": "input-dropdown-scale", "index": MATCH}, "value"),
        Output({"type": "input-color-picker", "index": MATCH}, "value"),
        Output({"type": "input-icon-selector", "index": MATCH}, "value"),
        Output({"type": "input-title-size", "index": MATCH}, "value"),
        # Output({"type": "input-number-marks", "index": MATCH}, "value"),
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
            edit_context: Edit page context with component data.
            input_id: Interactive component ID from the design form.

        Returns:
            Tuple of pre-populated values for all interactive settings.
        """
        no_update_tuple = _create_no_update_tuple(6)

        if not edit_context:
            return no_update_tuple

        component_data = edit_context.get("component_data")
        if not component_data or component_data.get("component_type") != "interactive":
            return no_update_tuple

        # Match component ID (actual ID, no -tmp)
        if str(input_id["index"]) != str(edit_context.get("component_id")):
            return no_update_tuple

        logger.debug(
            f"Pre-populating interactive settings for component {input_id['index']}: "
            f"title={component_data.get('title')}, column={component_data.get('column_name')}, "
            f"method={component_data.get('interactive_component_type')}"
        )

        # Ensure ColorInput components get empty string instead of None to avoid trim() errors
        return (
            component_data.get("title") or "",  # TextInput needs string
            component_data.get("column_name"),  # Select accepts None
            component_data.get("interactive_component_type"),  # Select accepts None
            # COMMENTED OUT: Scale and marks (UI elements removed)
            # component_data.get("scale") or "linear",  # Select needs value
            component_data.get("custom_color") or "",  # ColorInput needs empty string, not None
            component_data.get("icon_name") or "bx:slider-alt",  # Select needs value
            component_data.get("title_size") or "md",  # Select needs value
            # component_data.get("marks_number") or 2,  # NumberInput needs value
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

        Determines available aggregation methods (Select, MultiSelect, Slider, etc.)
        based on the column's data type and characteristics.

        Args:
            column_value: Selected column name.
            workflow_id: Workflow ID (from stepper or edit context).
            data_collection_id: Data collection ID (from stepper or edit context).
            edit_context: Edit page context (used in edit mode).
            id: Component ID dict.
            local_data: Local store data containing access token.

        Returns:
            List of options for the method dropdown.
        """
        import dash

        # Skip if all inputs are None during component initialization
        if column_value is None and workflow_id is None and data_collection_id is None:
            return dash.no_update

        if not local_data:
            logger.error("No local_data available for update_aggregation_options")
            return []

        TOKEN = local_data["access_token"]

        # In edit mode, get workflow/dc IDs from edit context
        if edit_context and (not workflow_id or not data_collection_id):
            component_data = edit_context.get("component_data", {})
            if component_data:
                workflow_id = workflow_id or component_data.get("wf_id")
                data_collection_id = data_collection_id or component_data.get("dc_id")

        if not workflow_id or not data_collection_id:
            logger.debug("Missing workflow/dc parameters for aggregation options")
            return []

        if not column_value:
            return []

        cols_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)

        if column_value not in cols_json:
            logger.error(f"Column '{column_value}' not found in available columns")
            return []

        column_type = cols_json[column_value]["type"]

        from depictio.dash.modules.interactive_component.utils import agg_functions

        if str(column_type) not in agg_functions:
            logger.error(f"Column type '{column_type}' not supported")
            return []

        # Get unique count for categorical columns
        nb_unique = 0
        if column_type in ["object", "category"]:
            nb_unique = cols_json[column_value]["specs"]["nunique"]

        agg_methods = agg_functions[str(column_type)]["input_methods"]
        options = [{"label": k, "value": k} for k in agg_methods.keys()]

        # Filter out SegmentedControl for high-cardinality columns
        if nb_unique > 5:
            options = [e for e in options if e["label"] != "SegmentedControl"]

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
            # COMMENTED OUT: Scale and marks inputs (UI elements removed)
            # Input({"type": "input-dropdown-scale", "index": MATCH}, "value"),
            Input({"type": "input-color-picker", "index": MATCH}, "value"),
            Input({"type": "input-icon-selector", "index": MATCH}, "value"),
            Input({"type": "input-title-size", "index": MATCH}, "value"),
            # Input({"type": "input-number-marks", "index": MATCH}, "value"),
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
        color_value,
        icon_name,
        title_size,
        edit_context,
        workflow_id,
        data_collection_id,
        id,
        local_data,
    ):
        """
        Update interactive component preview based on form inputs.

        Generates a live preview of the interactive component based on current
        form selections, along with description and column metadata table.

        Args:
            input_value: Title input value.
            column_value: Selected column name.
            aggregation_value: Selected aggregation method.
            color_value: Selected color for the icon.
            icon_name: Selected icon name.
            title_size: Selected title size.
            edit_context: Edit page context (used in edit mode).
            workflow_id: Workflow ID (from stepper or edit context).
            data_collection_id: Data collection ID (from stepper or edit context).
            id: Component ID dict.
            local_data: Local store data containing access token.

        Returns:
            Tuple of (preview_component, description_element, columns_table).
        """
        if not local_data:
            logger.error("No local_data available for preview component")
            return [], None, None

        TOKEN = local_data["access_token"]

        # In edit mode, get values from edit context
        if edit_context:
            component_data = edit_context.get("component_data", {})
            if component_data:
                workflow_id = workflow_id or component_data.get("wf_id")
                data_collection_id = data_collection_id or component_data.get("dc_id")
                column_value = column_value or component_data.get("column_name")
                aggregation_value = aggregation_value or component_data.get(
                    "interactive_component_type"
                )
                input_value = input_value or component_data.get("title", "")
                color_value = color_value or component_data.get("custom_color", "")
                title_size = title_size or component_data.get("title_size", "md")
                icon_name = icon_name or component_data.get("icon_name", "bx:slider-alt")

        # Validate required parameters
        if not workflow_id or not data_collection_id:
            return [], None, None

        if column_value is None or aggregation_value is None:
            return [], None, None

        # Fetch column metadata
        cols_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)

        if not cols_json or column_value not in cols_json:
            logger.error(f"Column '{column_value}' not found in available columns")
            return [], None, None

        column_type = cols_json[column_value]["type"]

        # Validate aggregation compatibility
        from depictio.dash.modules.interactive_component.utils import agg_functions

        available_methods = list(
            agg_functions.get(str(column_type), {}).get("input_methods", {}).keys()
        )

        if aggregation_value not in available_methods:
            logger.warning(f"Method {aggregation_value} not available for type {column_type}")
            return [], None, None

        # Create description and columns table
        interactive_description = _create_interactive_description(
            aggregation_value, column_type, agg_functions
        )
        columns_description_df = _create_columns_description_table(cols_json)
        if columns_description_df is None:
            columns_description_df = html.Div("Error creating columns description table")

        # Build preview component
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import load_deltatable_lite

        try:
            df = load_deltatable_lite(
                ObjectId(workflow_id),
                ObjectId(data_collection_id),
                TOKEN=TOKEN,
            )

            preview_component = _build_preview_by_type(aggregation_value, column_value, df)
            new_interactive_component = _wrap_preview_with_title(
                preview_component,
                input_value or column_value,
                icon_name,
                color_value,
                title_size,
            )

        except Exception as e:
            logger.error(f"Error building preview: {e}")
            new_interactive_component = dmc.Alert(
                title="Preview Error",
                children=f"Could not generate preview: {str(e)}",
                color="red",
            )

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
        Update stored metadata as user configures the interactive component.

        This metadata is used by save_stepper_component callback to persist
        the component configuration. Field names must match those expected
        by the batch callback in core_async.py.

        Args:
            workflow_id: Selected workflow ID.
            dc_id: Selected data collection ID.
            column: Selected column name.
            method: Selected aggregation method.
            title: Component title.
            color: Custom icon color.
            icon: Icon name.
            title_size: Title text size.
            current_metadata: Existing metadata dict to update.

        Returns:
            Updated metadata dict with all current selections.
        """
        if not current_metadata:
            current_metadata = {}

        current_metadata.update(
            {
                "wf_id": workflow_id,
                "dc_id": dc_id,
                "column_name": column,
                "interactive_component_type": method,
                "title": title or column,
                "custom_color": color,
                "icon_name": icon,
                "title_size": title_size,
            }
        )

        logger.debug(f"Updated stored metadata: {current_metadata}")
        return current_metadata

    logger.debug("Interactive design callbacks registered")
