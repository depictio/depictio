"""
Figure Component - UI Callbacks

This module contains callbacks for building the parameter UI interface.
Restored from frontend_legacy.py as part of Phase 2A implementation.
"""

from datetime import datetime

import dash
import dash_mantine_components as dmc
from dash import ALL, MATCH, Input, Output, State, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.utils import get_columns_from_data_collection

from ..component_builder import AccordionBuilder, ComponentBuilder
from ..definitions import get_visualization_definition
from ..state_manager import state_manager


def register_ui_callbacks(app):
    """Register UI building callbacks for figure component."""

    @app.callback(
        Output({"type": "collapse", "index": MATCH}, "children"),
        [
            Input({"type": "edit-button", "index": MATCH}, "n_clicks"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
        ],
        [
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "edit-button", "index": MATCH}, "id"),
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State("local-store", "data"),
            State({"type": "figure-mode-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=False,
    )
    def build_parameter_interface(
        _n_clicks_edit,
        visu_type,
        workflow,
        data_collection,
        edit_button_id,
        current_dict_kwargs,
        local_data,
        current_mode,
    ):
        """Build parameter interface using the robust component builder system.

        This callback is triggered when:
        1. Visualization type changes in the dropdown
        2. Edit button is clicked (though unused in current implementation)

        It builds the parameter input UI (x, y, color, size dropdowns, etc.)
        based on the selected visualization type and available columns.
        """
        if not local_data:
            raise dash.exceptions.PreventUpdate

        # Don't build UI parameter interface if in code mode
        if current_mode == "code":
            return html.Div()  # Return empty div for code mode

        TOKEN = local_data["access_token"]
        component_index = edit_button_id["index"] if edit_button_id else "unknown"

        # Get available columns
        try:
            columns_json = get_columns_from_data_collection(workflow, data_collection, TOKEN)
            columns = list(columns_json.keys())
        except Exception as e:
            logger.error(f"Failed to get columns: {e}")
            columns = []
            columns_json = {}
            return html.Div(
                dmc.Alert(
                    f"Failed to load columns: {str(e)}",
                    title="Column Loading Error",
                    color="red",
                )
            )

        # Determine visualization type from dropdown
        if visu_type:  # visu_type is now the name (lowercase) from dropdown
            # Since we now use viz.name.lower() as dropdown value, use it directly
            visu_type = visu_type.lower()
        else:
            visu_type = "scatter"  # Default fallback

        try:
            # Get visualization definition
            viz_def = get_visualization_definition(visu_type)

            # Get or create component state
            state = state_manager.get_state(component_index)
            if not state:
                state = state_manager.create_state(
                    component_id=component_index,
                    visualization_type=visu_type,
                    data_collection_id=data_collection or "",
                    workflow_id=workflow or "",
                )
            else:
                # Update visualization type if changed
                if state.visualization_type != visu_type:
                    state_manager.change_visualization_type(component_index, visu_type)

            # Load existing parameters from current dict_kwargs (which contains preserved values)
            parameters_to_load = current_dict_kwargs or {}

            if parameters_to_load:
                logger.debug(f"Loading parameters into state: {parameters_to_load}")
                for param_name, value in parameters_to_load.items():
                    state.set_parameter_value(param_name, value)

            # Build UI components
            component_builder = ComponentBuilder(component_index, columns, columns_json)
            accordion_builder = AccordionBuilder(component_builder)

            # Build the complete accordion interface
            accordion = accordion_builder.build_full_accordion(viz_def, state)

            return accordion

        except Exception as e:
            logger.error(f"Error building parameter interface: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return html.Div(
                [
                    dmc.Alert(
                        f"Error loading parameters: {str(e)}",
                        title="Parameter Loading Error",
                        color="red",
                    )
                ]
            )

    # Callback to capture parameter changes dynamically
    @app.callback(
        Output({"type": "param-trigger", "index": MATCH}, "data"),
        [
            Input({"type": ALL, "index": MATCH}, "value"),
            Input({"type": ALL, "index": MATCH}, "checked"),  # For DMC Switch components
        ],
        [
            State({"type": "param-trigger", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def update_param_trigger_and_state(*args):
        """
        Dynamically capture parameter changes using callback context.

        This callback uses ctx.inputs_list to dynamically iterate over
        whatever parameter inputs exist for the current visualization type,
        avoiding hardcoded parameter lists.
        """
        import json
        import time

        from ..state_manager import state_manager

        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        # Get component index from state
        trigger_id = args[-1]  # Last arg is the State
        component_index = trigger_id["index"]

        # Check if any param-* input triggered this
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        try:
            triggered_id_dict = json.loads(triggered_id)
        except (json.JSONDecodeError, TypeError):
            raise dash.exceptions.PreventUpdate

        # Only process if it's a parameter input
        if not (
            isinstance(triggered_id_dict, dict)
            and triggered_id_dict.get("type", "").startswith("param-")
        ):
            raise dash.exceptions.PreventUpdate

        # Get the parameter name that was actually changed
        triggered_param = triggered_id_dict.get("type", "").replace("param-", "")

        logger.info(f"   Parameter: {triggered_param}")

        # Get state from state manager
        state = state_manager.get_state(component_index)
        if not state:
            logger.warning(
                f"No state found for component {component_index}, cannot update parameters"
            )
            return dash.no_update

        # Extract all parameter values from ctx.inputs_list
        # Update all parameters, but specifically handle the triggered one for clearing
        # Track processed parameters to avoid duplicates
        processed_params = set()

        for input_dict in ctx.inputs_list:
            for input_item in input_dict:
                input_id = input_item.get("id", {})
                if isinstance(input_id, dict) and input_id.get("type", "").startswith("param-"):
                    param_name = input_id["type"].replace("param-", "")

                    # Skip if we've already processed this parameter
                    if param_name in processed_params:
                        continue

                    processed_params.add(param_name)

                    # Get value from input - try both 'value' and 'checked'
                    value = input_item.get("value")
                    checked = input_item.get("checked")

                    # Use checked for Switch components, value for others
                    actual_value = checked if checked is not None else value

                    # Update state - handle both setting and clearing
                    if isinstance(actual_value, bool):
                        # Boolean False is a valid value - always set it
                        state.set_parameter_value(param_name, actual_value)
                        if param_name == triggered_param:
                            logger.info(f"   {param_name}: {actual_value}")
                    elif actual_value is not None and actual_value != "" and actual_value != []:
                        # Non-empty value - set it
                        state.set_parameter_value(param_name, actual_value)
                        if param_name == triggered_param:
                            logger.info(f"   {param_name}: {actual_value}")
                    else:
                        # Parameter is empty/cleared
                        # Only set to None if this is the parameter that was actually cleared
                        # (to avoid clearing other parameters that happen to be None in current inputs)
                        if param_name == triggered_param:
                            state.set_parameter_value(param_name, None)
                            logger.info(f"   {param_name}: CLEARED (set to None)")
                        # Otherwise, don't update it - keep existing value in state

        # Return updated trigger with timestamp
        return {"timestamp": time.time()}

    # Callback to collect parameter changes and update dict_kwargs
    # Uses ALLSMALLER pattern to handle any parameters that exist for the current viz type
    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data"),
        [
            Input({"type": "param-trigger", "index": MATCH}, "data"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State({"type": "collapse", "index": MATCH}, "children"),
            State({"type": "param-trigger", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def update_dict_kwargs_from_state_manager(
        trigger_data, current_kwargs, collapse_children, trigger_id
    ):
        """
        Update dict_kwargs using state manager to avoid missing parameter issues.

        This callback is triggered by state_manager changes and extracts
        parameter values safely without depending on specific parameter inputs.
        """
        from ..state_manager import state_manager

        component_index = trigger_id["index"]

        # Get state from state manager
        state = state_manager.get_state(component_index)
        if not state:
            logger.warning(f"No state found for component {component_index}")
            return current_kwargs or {}

        # Get all parameter values from state.parameters dictionary
        # Filter out None/empty values - only include meaningful parameters
        # Keep boolean False (it's a valid value)
        # IMPORTANT: Exclude customization parameters - they're not Plotly Express parameters
        customization_param_names = {
            "axis_scale_enabled",
            "axis_scale_axis",
            "axis_scale_default",
            "reference_lines",  # Reference lines are stored separately, not passed to Plotly
            "highlights",  # Point highlights configuration
        }

        updated_kwargs = {}
        for param_name, param_value in state.parameters.items():
            # Skip customization parameters
            if param_name in customization_param_names:
                continue

            if isinstance(param_value, bool):
                # Always include boolean values (including False)
                updated_kwargs[param_name] = param_value
            elif param_value is not None and param_value != "" and param_value != []:
                # Include non-empty values
                updated_kwargs[param_name] = param_value

        return updated_kwargs

    # Callback to sync dict_kwargs into stored-metadata-component for saving
    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data"),
        [
            Input({"type": "dict_kwargs", "index": MATCH}, "data"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            Input({"type": "figure-mode-store", "index": MATCH}, "data"),
            Input({"type": "code-content-store", "index": MATCH}, "data"),
            # CRITICAL: Listen to customization store changes
            Input({"type": "reflines-store", "index": MATCH}, "data"),
            Input({"type": "highlights-store", "index": MATCH}, "data"),
        ],
        [
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
            State({"type": "stored-metadata-component", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def sync_dict_kwargs_to_metadata(
        dict_kwargs,
        visu_type,
        mode,
        code_content,
        reflines_data,
        highlights_data,
        current_metadata,
        component_id,
    ):
        """Sync dict_kwargs, visu_type, mode, code_content, and customizations to stored-metadata-component for saving."""
        from ..state_manager import state_manager

        if not current_metadata:
            raise dash.exceptions.PreventUpdate

        # Determine effective mode and code content
        effective_mode = mode or "ui"
        effective_code_content = (code_content or "") if effective_mode == "code" else ""

        # Get customization values from state manager (if they exist)
        component_index = component_id["index"]
        state = state_manager.get_state(component_index)

        scale_enabled = None
        scale_axis = None
        scale_default = None
        highlights = None
        reference_lines = None

        if state:
            scale_enabled = state.get_parameter_value("axis_scale_enabled")
            scale_axis = state.get_parameter_value("axis_scale_axis")
            scale_default = state.get_parameter_value("axis_scale_default")
            highlights = state.get_parameter_value("highlights")
            reference_lines = state.get_parameter_value("reference_lines")

        # Build customizations object
        customizations = {}

        # Axis customizations
        if scale_enabled:
            customizations["axes"] = {}
            axes_to_configure = ["x", "y"] if scale_axis == "both" else [scale_axis or "y"]
            for axis in axes_to_configure:
                customizations["axes"][axis] = {
                    "scale": scale_default or "linear",
                }

        # Reference lines
        if reference_lines and isinstance(reference_lines, list):
            customizations["reference_lines"] = []
            for idx, line in enumerate(reference_lines):
                line_config = {
                    "type": line.get("type", "hline"),
                    "y": line.get("position") if line.get("type") == "hline" else None,
                    "x": line.get("position") if line.get("type") == "vline" else None,
                    "line_color": line.get("color", "red"),
                    "line_dash": line.get("dash", "dash"),
                    "line_width": line.get("width", 2),
                }
                # Only add annotation if present and not empty
                annotation = line.get("annotation", "")
                if annotation and annotation.strip():
                    line_config["annotation_text"] = annotation
                    logger.warning(
                        f"📝 Reference line {idx} has annotation: '{annotation}'. "
                        "To remove: edit component and clear the annotation field."
                    )
                customizations["reference_lines"].append(line_config)

        # Highlights
        if highlights and isinstance(highlights, list):
            customizations["highlights"] = [
                {
                    "conditions": [
                        {
                            "column": hl.get("column", ""),
                            "operator": {
                                "equals": "eq",
                                "greater than": "gt",
                                "less than": "lt",
                                "contains": "contains",
                            }.get(hl.get("condition", "equals"), "eq"),
                            "value": hl.get("value", ""),
                        }
                    ],
                    "logic": "and",
                    "style": {
                        "marker_color": hl.get("color", "red"),
                        "marker_size": hl.get("size", 12),
                        "marker_line_color": hl.get("outline", ""),
                        "marker_line_width": 2 if hl.get("outline") else 0,
                        "dim_opacity": 0.3,
                    },
                }
                for hl in highlights
            ]

        # Build customization UI state for view mode
        customization_ui_state = {}
        if scale_enabled:
            customization_ui_state["scale_control"] = {
                "enabled": True,
                "axis": scale_axis or "y",
                "position": "top-right",
                "current_scale": scale_default or "linear",
            }

        # Add reference line controls to UI state
        if reference_lines and isinstance(reference_lines, list):
            customization_ui_state["reference_line_controls"] = [
                {
                    "id": f"refline-{idx}",
                    "type": line.get("type", "hline"),
                    "show_slider": line.get("show_slider", False),
                    "current_value": line.get("position", 0),
                }
                for idx, line in enumerate(reference_lines)
            ]

        # Build updated metadata
        updated_metadata = {
            **current_metadata,
            "dict_kwargs": dict_kwargs or {},
            "visu_type": visu_type or current_metadata.get("visu_type", "scatter"),
            "last_updated": datetime.now().isoformat(),
            "mode": effective_mode,
            "code_content": effective_code_content,
        }

        # Add customizations if any exist
        if customizations:
            updated_metadata["customizations"] = customizations

        # Add customization UI state if any exist
        if customization_ui_state:
            updated_metadata["customization_ui_state"] = customization_ui_state

        return updated_metadata

    # Callback to add a new reference line
    @app.callback(
        Output({"type": "reflines-store", "index": MATCH}, "data"),
        Input({"type": "btn-add-refline", "index": MATCH}, "n_clicks"),
        State({"type": "reflines-store", "index": MATCH}, "data"),
        State({"type": "reflines-store", "index": MATCH}, "id"),
        prevent_initial_call=True,
    )
    def add_reference_line(n_clicks, current_lines, store_id):
        """Add a new reference line."""
        if not n_clicks:
            raise dash.exceptions.PreventUpdate

        component_index = store_id["index"]

        # Get current lines or initialize empty list
        lines = current_lines if isinstance(current_lines, list) else []

        # Add new line with defaults
        new_line = {
            "type": "hline",
            "position": 0,
            "color": "red",
            "dash": "dash",
            "width": 2,
            "annotation": "",
            "show_slider": True,  # Enable slider by default for view mode controls
        }
        lines.append(new_line)

        # Update state manager
        state = state_manager.get_state(component_index)
        if state:
            state.set_parameter_value("reference_lines", lines)

        return lines

    # Callback to update reflines container when store changes
    @app.callback(
        Output({"type": "reflines-container", "index": MATCH}, "children"),
        Input({"type": "reflines-store", "index": MATCH}, "data"),
        State({"type": "reflines-store", "index": MATCH}, "id"),
        State({"type": "reflines-container", "index": MATCH}, "children"),
        prevent_initial_call=False,
    )
    def update_reflines_display(lines_data, store_id, current_children):
        """Rebuild reflines display when data changes."""

        component_index = store_id["index"]

        if not lines_data or not isinstance(lines_data, list):
            return dmc.Text("No reference lines", size="sm", c="gray")

        # Only rebuild if the number of lines changed (add/delete), not on property updates
        if current_children and not isinstance(current_children, str):
            # Count existing line items (Papers with line configurations)
            existing_count = 0
            if isinstance(current_children, list):
                existing_count = len(
                    [c for c in current_children if hasattr(c, "get") and c.get("type") == "Paper"]
                )

            # If count matches, don't rebuild (just property updates)
            if existing_count == len(lines_data):
                raise dash.exceptions.PreventUpdate

        # Build UI for each line
        line_items = []
        for idx, line in enumerate(lines_data):
            line_items.append(
                dmc.Paper(
                    [
                        dmc.Stack(
                            [
                                dmc.Group(
                                    [
                                        dmc.Text(
                                            f"Line {idx + 1}",
                                            size="sm",
                                        ),
                                        dmc.ActionIcon(
                                            DashIconify(icon="mdi:delete"),
                                            id={
                                                "type": "btn-delete-refline",
                                                "index": component_index,
                                                "line_idx": idx,
                                            },
                                            color="red",
                                            variant="subtle",
                                            size="sm",
                                        ),
                                    ],
                                    justify="space-between",
                                ),
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Select(
                                                label="Type",
                                                data=["hline", "vline"],
                                                value=line.get("type", "hline"),
                                                id={
                                                    "type": "refline-type",
                                                    "index": component_index,
                                                    "line_idx": idx,
                                                },
                                                size="xs",
                                            ),
                                            span=6,
                                        ),
                                        dmc.GridCol(
                                            dmc.NumberInput(
                                                label="Position",
                                                value=line.get("position", 0),
                                                id={
                                                    "type": "refline-position",
                                                    "index": component_index,
                                                    "line_idx": idx,
                                                },
                                                size="xs",
                                                step=0.01,
                                            ),
                                            span=6,
                                        ),
                                    ],
                                    gutter="xs",
                                ),
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.ColorInput(
                                                label="Color",
                                                value=line.get("color", "red"),
                                                id={
                                                    "type": "refline-color",
                                                    "index": component_index,
                                                    "line_idx": idx,
                                                },
                                                size="xs",
                                            ),
                                            span=6,
                                        ),
                                        dmc.GridCol(
                                            dmc.Select(
                                                label="Line Style",
                                                data=["solid", "dash", "dot", "dashdot"],
                                                value=line.get("dash", "dash"),
                                                id={
                                                    "type": "refline-dash",
                                                    "index": component_index,
                                                    "line_idx": idx,
                                                },
                                                size="xs",
                                            ),
                                            span=6,
                                        ),
                                    ],
                                    gutter="xs",
                                ),
                                dmc.TextInput(
                                    label="Annotation (optional)",
                                    value=line.get("annotation", ""),
                                    id={
                                        "type": "refline-annotation",
                                        "index": component_index,
                                        "line_idx": idx,
                                    },
                                    size="xs",
                                ),
                                dmc.Checkbox(
                                    label="Show slider in view mode",
                                    checked=line.get("show_slider", False),
                                    id={
                                        "type": "refline-show-slider",
                                        "index": component_index,
                                        "line_idx": idx,
                                    },
                                    size="xs",
                                ),
                            ],
                            gap="xs",
                        )
                    ],
                    p="sm",
                    withBorder=True,
                    mb="xs",
                )
            )

        return line_items

    # Callback to delete a reference line
    @app.callback(
        Output({"type": "reflines-store", "index": MATCH}, "data", allow_duplicate=True),
        Input({"type": "btn-delete-refline", "index": MATCH, "line_idx": ALL}, "n_clicks"),
        State({"type": "btn-delete-refline", "index": MATCH, "line_idx": ALL}, "id"),
        State({"type": "reflines-store", "index": MATCH}, "data"),
        State({"type": "reflines-store", "index": MATCH}, "id"),
        prevent_initial_call=True,
    )
    def delete_reference_line(n_clicks_list, button_ids, current_lines, store_id):
        """Delete a reference line."""
        if not dash.callback_context.triggered:
            raise dash.exceptions.PreventUpdate

        component_index = store_id["index"]

        # Find which button was clicked
        triggered_id = dash.callback_context.triggered_id
        line_idx_to_delete = triggered_id.get("line_idx")

        # Get current lines
        lines = current_lines if isinstance(current_lines, list) else []

        # Delete the line
        if 0 <= line_idx_to_delete < len(lines):
            lines.pop(line_idx_to_delete)

        # Update state manager
        state = state_manager.get_state(component_index)
        if state:
            state.set_parameter_value("reference_lines", lines)

        return lines

    # Callback to update reference line properties
    @app.callback(
        Output({"type": "reflines-store", "index": MATCH}, "data", allow_duplicate=True),
        [
            Input({"type": "refline-type", "index": MATCH, "line_idx": ALL}, "value"),
            Input({"type": "refline-position", "index": MATCH, "line_idx": ALL}, "value"),
            Input({"type": "refline-color", "index": MATCH, "line_idx": ALL}, "value"),
            Input({"type": "refline-dash", "index": MATCH, "line_idx": ALL}, "value"),
            Input({"type": "refline-width", "index": MATCH, "line_idx": ALL}, "value"),
            Input({"type": "refline-annotation", "index": MATCH, "line_idx": ALL}, "value"),
            Input({"type": "refline-show-slider", "index": MATCH, "line_idx": ALL}, "checked"),
        ],
        State({"type": "reflines-store", "index": MATCH}, "data"),
        State({"type": "reflines-store", "index": MATCH}, "id"),
        prevent_initial_call=True,
    )
    def update_reference_line_properties(
        types, positions, colors, dashes, widths, annotations, show_sliders, current_lines, store_id
    ):
        """Update reference line properties."""
        if not dash.callback_context.triggered:
            raise dash.exceptions.PreventUpdate

        component_index = store_id["index"]

        # Get current lines
        lines = current_lines if isinstance(current_lines, list) else []

        # Update lines with new values
        updated_lines = []
        for idx in range(len(lines)):
            updated_line = {
                "type": types[idx] if idx < len(types) else "hline",
                "position": positions[idx] if idx < len(positions) else 0,
                "color": colors[idx] if idx < len(colors) else "red",
                "dash": dashes[idx] if idx < len(dashes) else "dash",
                "width": widths[idx] if idx < len(widths) else 2,
                "annotation": annotations[idx] if idx < len(annotations) else "",
                "show_slider": show_sliders[idx] if idx < len(show_sliders) else False,
            }
            updated_lines.append(updated_line)

        # Update state manager
        state = state_manager.get_state(component_index)
        if state:
            state.set_parameter_value("reference_lines", updated_lines)

        return updated_lines

    # ========== Highlight Callbacks ==========

    # Callback to add a new highlight
    @app.callback(
        Output({"type": "highlights-store", "index": MATCH}, "data", allow_duplicate=True),
        Input({"type": "btn-add-highlight", "index": MATCH}, "n_clicks"),
        State({"type": "highlights-store", "index": MATCH}, "data"),
        State({"type": "highlights-store", "index": MATCH}, "id"),
        prevent_initial_call=True,
    )
    def add_highlight(n_clicks, current_highlights, store_id):
        """Add a new highlight to the list."""
        if not n_clicks:
            raise dash.exceptions.PreventUpdate

        component_index = store_id["index"]

        # Get current highlights
        highlights = current_highlights if isinstance(current_highlights, list) else []

        # Add new highlight with default values
        new_highlight = {
            "column": "",
            "condition": "equals",
            "value": "",
            "color": "red",
            "size": 12,
            "outline": "",
        }
        highlights.append(new_highlight)

        # Update state manager
        state = state_manager.get_state(component_index)
        if state:
            state.set_parameter_value("highlights", highlights)

        return highlights

    # Callback to update highlights display
    @app.callback(
        Output({"type": "highlights-container", "index": MATCH}, "children"),
        Input({"type": "highlights-store", "index": MATCH}, "data"),
        State({"type": "highlights-store", "index": MATCH}, "id"),
        State({"type": "dict_kwargs", "index": MATCH}, "data"),
        State({"type": "highlights-container", "index": MATCH}, "children"),
        prevent_initial_call="initial_duplicate",
    )
    def update_highlights_display(highlights, store_id, dict_kwargs, current_children):
        """Update the highlights display based on store data."""
        component_index = store_id["index"]

        if not highlights or not isinstance(highlights, list):
            return dmc.Text("No highlights added", size="sm", c="gray")

        # Only rebuild if the number of highlights changed (add/delete), not on property updates
        if current_children and not isinstance(current_children, str):
            # Count existing highlight items (Papers with highlight configurations)
            existing_count = 0
            if isinstance(current_children, list):
                existing_count = len(
                    [c for c in current_children if hasattr(c, "get") and c.get("type") == "Paper"]
                )

            # If count matches, don't rebuild (just property updates)
            if existing_count == len(highlights):
                raise dash.exceptions.PreventUpdate

        # Get available columns from dict_kwargs
        available_columns = []
        if dict_kwargs:
            # Extract x, y, z, color columns
            for key in ["x", "y", "z", "color", "size", "hover_data"]:
                if key in dict_kwargs:
                    val = dict_kwargs[key]
                    if isinstance(val, str):
                        available_columns.append(val)
                    elif isinstance(val, list):
                        available_columns.extend([v for v in val if isinstance(v, str)])

        highlight_items = []
        for idx, hl in enumerate(highlights):
            highlight_items.append(
                dmc.Paper(
                    [
                        dmc.Group(
                            [
                                dmc.Text(f"Highlight {idx + 1}", size="sm"),
                                dmc.ActionIcon(
                                    DashIconify(icon="mdi:delete"),
                                    id={
                                        "type": "btn-delete-highlight",
                                        "index": component_index,
                                        "hl_idx": idx,
                                    },
                                    color="red",
                                    variant="subtle",
                                    size="sm",
                                ),
                            ],
                            justify="space-between",
                            mb="xs",
                        ),
                        dmc.Stack(
                            [
                                # Column selector
                                dmc.Select(
                                    label="Column",
                                    placeholder="Select column",
                                    data=available_columns,
                                    value=hl.get("column", ""),
                                    id={
                                        "type": "highlight-column",
                                        "index": component_index,
                                        "hl_idx": idx,
                                    },
                                    size="xs",
                                    searchable=True,
                                ),
                                # Condition and value
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Select(
                                                label="Condition",
                                                data=[
                                                    "equals",
                                                    "greater than",
                                                    "less than",
                                                    "contains",
                                                ],
                                                value=hl.get("condition", "equals"),
                                                id={
                                                    "type": "highlight-condition",
                                                    "index": component_index,
                                                    "hl_idx": idx,
                                                },
                                                size="xs",
                                            ),
                                            span=6,
                                        ),
                                        dmc.GridCol(
                                            dmc.TextInput(
                                                label="Value",
                                                placeholder="Enter value",
                                                value=str(hl.get("value", "")),
                                                id={
                                                    "type": "highlight-value",
                                                    "index": component_index,
                                                    "hl_idx": idx,
                                                },
                                                size="xs",
                                            ),
                                            span=6,
                                        ),
                                    ],
                                    gutter="xs",
                                ),
                                # Styling options
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.ColorInput(
                                                label="Color",
                                                value=hl.get("color", "red"),
                                                id={
                                                    "type": "highlight-color",
                                                    "index": component_index,
                                                    "hl_idx": idx,
                                                },
                                                size="xs",
                                            ),
                                            span=4,
                                        ),
                                        dmc.GridCol(
                                            dmc.NumberInput(
                                                label="Size",
                                                value=hl.get("size", 12),
                                                min=1,
                                                max=50,
                                                id={
                                                    "type": "highlight-size",
                                                    "index": component_index,
                                                    "hl_idx": idx,
                                                },
                                                size="xs",
                                            ),
                                            span=4,
                                        ),
                                        dmc.GridCol(
                                            dmc.ColorInput(
                                                label="Outline",
                                                value=hl.get("outline", ""),
                                                id={
                                                    "type": "highlight-outline",
                                                    "index": component_index,
                                                    "hl_idx": idx,
                                                },
                                                size="xs",
                                            ),
                                            span=4,
                                        ),
                                    ],
                                    gutter="xs",
                                ),
                            ],
                            gap="xs",
                        ),
                    ],
                    p="sm",
                    withBorder=True,
                    mb="xs",
                )
            )

        return highlight_items

    # Callback to delete a highlight
    @app.callback(
        Output({"type": "highlights-store", "index": MATCH}, "data", allow_duplicate=True),
        Input({"type": "btn-delete-highlight", "index": MATCH, "hl_idx": ALL}, "n_clicks"),
        State({"type": "btn-delete-highlight", "index": MATCH, "hl_idx": ALL}, "id"),
        State({"type": "highlights-store", "index": MATCH}, "data"),
        State({"type": "highlights-store", "index": MATCH}, "id"),
        prevent_initial_call=True,
    )
    def delete_highlight(n_clicks_list, button_ids, current_highlights, store_id):
        """Delete a highlight."""
        if not dash.callback_context.triggered:
            raise dash.exceptions.PreventUpdate

        component_index = store_id["index"]

        # Find which button was clicked
        triggered_id = dash.callback_context.triggered_id
        hl_idx_to_delete = triggered_id.get("hl_idx")

        # Get current highlights
        highlights = current_highlights if isinstance(current_highlights, list) else []

        # Delete the highlight
        if 0 <= hl_idx_to_delete < len(highlights):
            highlights.pop(hl_idx_to_delete)

        # Update state manager
        state = state_manager.get_state(component_index)
        if state:
            state.set_parameter_value("highlights", highlights)

        return highlights

    # Callback to update highlight properties
    @app.callback(
        Output({"type": "highlights-store", "index": MATCH}, "data", allow_duplicate=True),
        [
            Input({"type": "highlight-column", "index": MATCH, "hl_idx": ALL}, "value"),
            Input({"type": "highlight-condition", "index": MATCH, "hl_idx": ALL}, "value"),
            Input({"type": "highlight-value", "index": MATCH, "hl_idx": ALL}, "value"),
            Input({"type": "highlight-color", "index": MATCH, "hl_idx": ALL}, "value"),
            Input({"type": "highlight-size", "index": MATCH, "hl_idx": ALL}, "value"),
            Input({"type": "highlight-outline", "index": MATCH, "hl_idx": ALL}, "value"),
        ],
        State({"type": "highlights-store", "index": MATCH}, "data"),
        State({"type": "highlights-store", "index": MATCH}, "id"),
        prevent_initial_call=True,
    )
    def update_highlight_properties(
        columns, conditions, values, colors, sizes, outlines, current_highlights, store_id
    ):
        """Update highlight properties."""
        if not dash.callback_context.triggered:
            raise dash.exceptions.PreventUpdate

        component_index = store_id["index"]

        # Get current highlights
        highlights = current_highlights if isinstance(current_highlights, list) else []

        # Update highlights with new values
        updated_highlights = []
        for idx in range(len(highlights)):
            updated_highlight = {
                "column": columns[idx] if idx < len(columns) else "",
                "condition": conditions[idx] if idx < len(conditions) else "equals",
                "value": values[idx] if idx < len(values) else "",
                "color": colors[idx] if idx < len(colors) else "red",
                "size": sizes[idx] if idx < len(sizes) else 12,
                "outline": outlines[idx] if idx < len(outlines) else "",
            }
            updated_highlights.append(updated_highlight)

        # Update state manager
        state = state_manager.get_state(component_index)
        if state:
            state.set_parameter_value("highlights", updated_highlights)

        return updated_highlights
