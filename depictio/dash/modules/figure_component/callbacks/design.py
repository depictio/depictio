"""
Figure Component - Design/Edit Mode Callbacks

This module contains callbacks that are only needed when editing or designing figures.
These callbacks are lazy-loaded when entering edit mode to reduce initial app startup time.

Callbacks:
- handle_mode_switch: Toggle between UI and Code modes
- store_generated_code: Generate code from UI parameters when switching to code mode
- pre_populate_figure_settings_for_edit: Pre-fill design form in edit mode (disabled)
"""

import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.figure_component.code_mode import (
    convert_ui_params_to_code,
    create_code_mode_interface,
)


def register_design_callbacks(app):
    """Register design/edit mode callbacks for figure component."""

    # Mode toggle callback - handles switching between UI and Code modes
    @app.callback(
        [
            Output({"type": "ui-mode-content", "index": MATCH}, "style"),
            Output({"type": "code-mode-content", "index": MATCH}, "style"),
            Output({"type": "code-mode-interface", "index": MATCH}, "children"),
            Output({"type": "figure-mode-store", "index": MATCH}, "data"),
        ],
        [
            Input({"type": "figure-mode-toggle", "index": MATCH}, "value"),
        ],
        [
            State({"type": "figure-mode-store", "index": MATCH}, "data"),
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            State({"type": "code-content-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=False,  # Handle both initial load and user toggles
    )
    def handle_mode_switch(mode, current_mode, dict_kwargs, visu_type_label, current_code):
        """Handle initial setup and user toggling between UI and Code modes."""
        # Guard: Return no_update if mode is None (component not ready)
        if mode is None:
            logger.debug("Mode is None - component not ready yet")
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        logger.info(f"🔄 MODE TOGGLE: {current_mode} -> {mode}")

        # Get component index for code interface creation
        ctx = dash.callback_context
        try:
            if ctx.outputs_list:
                component_id = ctx.outputs_list[0]["id"]
                component_index = (
                    component_id["index"] if isinstance(component_id, dict) else "unknown"
                )
            else:
                component_index = "unknown"
        except Exception:
            component_index = "unknown"

        # Check if this is initial setup (current_mode is None or doesn't match mode)
        is_initial_setup = current_mode is None or current_mode != mode
        action_type = "INITIAL SETUP" if is_initial_setup else "USER TOGGLE"
        logger.info(f"{action_type}: Setting {mode} mode for component {component_index}")

        # Initialize styles - only UI and Code modes supported
        ui_content_style = {"display": "none"}
        code_content_style = {"display": "none"}

        if mode == "code":
            # Switch to code mode interface
            code_content_style = {"display": "block"}
            code_interface_children = create_code_mode_interface(component_index)
            logger.info(f"Switched to CODE MODE for {component_index}")
        else:
            # Switch to UI mode interface (default)
            ui_content_style = {"display": "block"}
            # Create hidden code-status component to ensure callbacks work
            code_interface_children = [
                dmc.Alert(
                    id={"type": "code-status", "index": component_index},
                    title="UI Mode",
                    color="blue",
                    children="Component in UI mode",
                    style={"display": "none"},  # Hidden in UI mode
                )
            ]
            logger.info(f"Switched to UI MODE for {component_index}")

        return (
            ui_content_style,
            code_content_style,
            code_interface_children,
            mode,
        )

    # Store generated code when switching to code mode
    @app.callback(
        Output({"type": "code-content-store", "index": MATCH}, "data"),
        [
            Input({"type": "figure-mode-toggle", "index": MATCH}, "value"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            State({"type": "code-content-store", "index": MATCH}, "data"),
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        ],
        prevent_initial_call=False,
    )
    def store_generated_code(
        mode, dict_kwargs, visu_type_label, current_code_content, stored_metadata
    ):
        """Store generated code when switching to code mode."""
        # Guard: Return no_update if mode is None (component not ready)
        if mode is None:
            logger.debug("store_generated_code: Mode is None - component not ready yet")
            return dash.no_update

        logger.info("=== store_generated_code CALLBACK CALLED ===")
        logger.info(f"Mode: {mode}")
        logger.info(f"Dict kwargs: {dict_kwargs}")
        logger.info(f"Visualization type label: {visu_type_label}")
        logger.info(f"Current code content: {bool(current_code_content)}")
        logger.info(
            f"Stored metadata code: {bool(stored_metadata and stored_metadata.get('code_content'))}"
        )

        # Priority 1: If we have code content in stored_metadata (loading existing code mode figure)
        if stored_metadata and stored_metadata.get("mode") == "code":
            existing_code = stored_metadata.get("code_content")
            if existing_code:
                logger.info("✅ Using code from stored_metadata (existing code mode figure)")
                return existing_code

        # Priority 2: If already have code content (user already edited code)
        if current_code_content:
            logger.info("✅ Preserving existing code content")
            return current_code_content

        # Priority 3: Generate code from UI parameters (switching from UI to code mode)
        if mode == "code" and dict_kwargs and visu_type_label:
            logger.info("🔄 Generating code from UI parameters")
            # visu_type_label is already the visu_type (e.g., "scatter", "bar", etc.)
            generated_code = convert_ui_params_to_code(dict_kwargs, visu_type_label)
            logger.info("✅ Code generated successfully")
            return generated_code

        # Priority 4: Return empty string for code mode without params
        if mode == "code":
            logger.info("⚠️ Code mode but no parameters - returning empty code")
            return ""

        # Priority 5: Return dash.no_update for UI mode
        logger.info("UI mode - no code update needed")
        return dash.no_update

    # TEMPORARILY DISABLED: Pre-populate callback is for edit page, not stepper
    # The stepper uses different component IDs (segmented-control-visu-graph vs figure-visu-type-selector)
    # Will be re-enabled when we test edit mode (Step 6)

    # @app.callback(
    #     # Visualization type selector
    #     Output({"type": "figure-visu-type-selector", "index": MATCH}, "value"),
    #     # Common parameters (exist across multiple viz types)
    #     Output({"type": "param-x", "index": MATCH}, "value", allow_duplicate=True),
    #     Output({"type": "param-y", "index": MATCH}, "value", allow_duplicate=True),
    #     Output({"type": "param-color", "index": MATCH}, "value", allow_duplicate=True),
    #     Output({"type": "param-size", "index": MATCH}, "value", allow_duplicate=True),
    #     Output({"type": "param-title", "index": MATCH}, "value", allow_duplicate=True),
    #     Output({"type": "param-opacity", "index": MATCH}, "value", allow_duplicate=True),
    #     Output({"type": "param-hover_name", "index": MATCH}, "value", allow_duplicate=True),
    #     Output({"type": "param-hover_data", "index": MATCH}, "value", allow_duplicate=True),
    #     Output({"type": "param-labels", "index": MATCH}, "value", allow_duplicate=True),
    #     Input("edit-page-context", "data"),
    #     State({"type": "figure-visu-type-selector", "index": MATCH}, "id"),
    #     prevent_initial_call="initial_duplicate",
    # )
    # def pre_populate_figure_settings_for_edit(edit_context, figure_id):
    #     """Pre-populate figure design settings when in edit mode (edit page only)."""
    #     import dash
    #
    #     if not edit_context:
    #         return tuple([dash.no_update] * 10)
    #
    #     component_data = edit_context.get("component_data")
    #     if not component_data or component_data.get("component_type") != "figure":
    #         return tuple([dash.no_update] * 10)
    #
    #     # Match component ID (actual ID, no -tmp)
    #     if str(figure_id["index"]) != str(edit_context.get("component_id")):
    #         return tuple([dash.no_update] * 10)
    #
    #     logger.info(f"🎨 PRE-POPULATING figure settings for component {figure_id['index']}")
    #
    #     # Extract visualization type
    #     visu_type = component_data.get("visu_type", "scatter")
    #     logger.info(f"   Visualization type: {visu_type}")
    #
    #     # Extract dict_kwargs (parameters)
    #     dict_kwargs = component_data.get("dict_kwargs", {})
    #     logger.info(f"   Parameters: {list(dict_kwargs.keys())}")
    #
    #     # Helper to extract parameter with None fallback
    #     def get_param(key, default=None):
    #         value = dict_kwargs.get(key, default)
    #         logger.info(f"   {key}: {value}")
    #         return value
    #
    #     # Extract all common parameters
    #     x = get_param("x")
    #     y = get_param("y")
    #     color = get_param("color")
    #     size = get_param("size")
    #     title = get_param("title")
    #     opacity = get_param("opacity")
    #     hover_name = get_param("hover_name")
    #     hover_data = get_param("hover_data")
    #
    #     # Handle labels (convert dict to JSON string for text input)
    #     labels = get_param("labels")
    #     if labels and isinstance(labels, dict):
    #         import json
    #
    #         labels = json.dumps(labels)
    #
    #     logger.info("✓ Pre-population complete")
    #
    #     return (
    #         visu_type,
    #         x,
    #         y,
    #         color,
    #         size,
    #         title,
    #         opacity,
    #         hover_name,
    #         hover_data,
    #         labels,
    #     )

    # Callback for code examples toggle button
    @app.callback(
        [
            Output({"type": "code-examples-collapse", "index": MATCH}, "opened"),
            Output({"type": "toggle-examples-btn", "index": MATCH}, "children"),
        ],
        [Input({"type": "toggle-examples-btn", "index": MATCH}, "n_clicks")],
        [State({"type": "code-examples-collapse", "index": MATCH}, "opened")],
        prevent_initial_call=True,
    )
    def toggle_code_examples(n_clicks, is_opened):
        """Toggle the code examples collapse section."""
        if n_clicks:
            new_is_opened = not is_opened
            button_text = "Hide Code Examples" if new_is_opened else "Show Code Examples"
            return new_is_opened, button_text
        raise dash.exceptions.PreventUpdate

    # Populate DataFrame columns information in code mode
    @app.callback(
        Output({"type": "columns-info", "index": MATCH}, "children"),
        Input({"type": "figure-mode-toggle", "index": MATCH}, "value"),
        State("local-store", "data"),
        State("url", "pathname"),
        State({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        prevent_initial_call=False,
    )
    def update_columns_info(mode, local_data, pathname, workflow_id, data_collection_id):
        """Update the available columns information for code mode."""
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import load_deltatable_lite

        logger.info(f"update_columns_info called: mode={mode}")

        # Guard: Return no_update if mode is None (component not ready)
        if mode is None:
            logger.debug("update_columns_info: Mode is None - component not ready yet")
            return dash.no_update

        # Only update when in code mode
        if mode != "code":
            logger.info("Not in code mode, skipping update")
            return dash.no_update

        if not local_data:
            logger.info("No local data available")
            return "Authentication required."

        try:
            # Get component index from the callback context
            dashboard_id = pathname.split("/")[-1] if pathname else None

            logger.info(f"Getting component data for dashboard: {dashboard_id}")

            if not workflow_id or not data_collection_id:
                return "Please ensure workflow and data collection are selected in the component."

            TOKEN = local_data["access_token"]
            loaded_df = load_deltatable_lite(
                ObjectId(workflow_id), ObjectId(data_collection_id), TOKEN=TOKEN
            )

            # Use Polars DataFrame directly to get column info
            df = loaded_df

            if df.height == 0:
                return "No data available in the selected data collection."

            # Create formatted column information using Polars schema
            columns_info = []
            for col, dtype in df.schema.items():
                dtype_str = str(dtype)
                # Simplify dtype names for Polars dtypes
                if "Int" in dtype_str or "UInt" in dtype_str:
                    display_type = "integer"
                elif "Float" in dtype_str:
                    display_type = "float"
                elif "String" in dtype_str or "Utf8" in dtype_str:
                    display_type = "text"
                elif "Date" in dtype_str or "Time" in dtype_str:
                    display_type = "datetime"
                else:
                    display_type = dtype_str.lower()

                columns_info.append(f"• {col} ({display_type})")

            columns_text = (
                f"DataFrame shape: {df.height} rows × {df.width} columns\n\n"
                + "\n".join(columns_info)
            )
            return dmc.Text(columns_text, style={"whiteSpace": "pre-line", "fontSize": "12px"})

        except Exception as e:
            logger.error(f"Error loading column information: {e}", exc_info=True)
            return f"Error loading column information: {str(e)}"

    # Update Ace editor theme based on app theme
    @app.callback(
        Output({"type": "code-editor", "index": MATCH}, "theme"),
        Input("theme-store", "data"),
        prevent_initial_call=False,
    )
    def update_code_editor_theme(theme_data):
        """Update Ace editor theme to match app theme (light/dark)."""
        # theme-store contains just a string: "light" or "dark"
        theme = theme_data if theme_data else "light"

        # Map app theme to Ace editor themes
        ace_theme = "monokai" if theme == "dark" else "github"
        logger.debug(f"Setting Ace editor theme to: {ace_theme} (app theme: {theme})")
        return ace_theme

    # Execute code button - live preview
    @app.callback(
        [
            Output({"type": "code-status", "index": MATCH}, "title"),
            Output({"type": "code-status", "index": MATCH}, "children"),
            Output({"type": "code-status", "index": MATCH}, "color"),
        ],
        Input({"type": "code-execute-btn", "index": MATCH}, "n_clicks"),
        [
            State({"type": "code-editor", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def execute_code_preview(n_clicks, code_content, workflow_id, data_collection_id, local_data):
        """Execute code and show preview/validation results."""
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import load_deltatable_lite
        from depictio.dash.modules.figure_component.simple_code_executor import (
            SimpleCodeExecutor,
        )

        if not n_clicks or not code_content:
            return dash.no_update, dash.no_update, dash.no_update

        logger.info("=== EXECUTE CODE PREVIEW ===")
        logger.info(f"Code length: {len(code_content)} characters")

        # Validate workflow and data collection
        if not workflow_id or not data_collection_id:
            return (
                "Error",
                "Please ensure workflow and data collection are selected.",
                "red",
            )

        if not local_data:
            return "Error", "Authentication required.", "red"

        try:
            # Load data
            TOKEN = local_data["access_token"]
            df = load_deltatable_lite(
                ObjectId(workflow_id), ObjectId(data_collection_id), TOKEN=TOKEN
            )

            if df.height == 0:
                return "Error", "No data available in the selected data collection.", "red"

            # Execute code
            executor = SimpleCodeExecutor()
            success, fig, message = executor.execute_code(code_content, df)

            if success:
                logger.info("✅ Code execution successful")
                return (
                    "Success",
                    dmc.Stack(
                        [
                            dmc.Text("✅ Code executed successfully!", size="sm"),
                            dmc.Text(
                                f"Figure type: {fig.data[0].type if fig.data else 'unknown'}",
                                size="xs",
                                c="gray",
                            ),
                            dmc.Text(
                                f"Data points: {len(fig.data[0].x) if fig.data and hasattr(fig.data[0], 'x') else 'N/A'}",
                                size="xs",
                                c="gray",
                            ),
                        ],
                        gap="xs",
                    ),
                    "green",
                )
            else:
                logger.error(f"Code execution failed: {message}")
                return (
                    "Execution Error",
                    dmc.Stack(
                        [
                            dmc.Text("❌ Code execution failed", size="sm"),
                            dmc.Code(message, block=True, style={"fontSize": "11px"}),
                        ],
                        gap="xs",
                    ),
                    "red",
                )

        except Exception as e:
            logger.error(f"Error during code execution: {e}", exc_info=True)
            return (
                "Error",
                dmc.Stack(
                    [
                        dmc.Text("❌ Unexpected error", size="sm"),
                        dmc.Code(str(e), block=True, style={"fontSize": "11px"}),
                    ],
                    gap="xs",
                ),
                "red",
            )

    logger.info(
        "✅ Figure design callbacks registered (mode toggle + code generation + code examples + columns info + theme + execute)"
    )


# Note: Live preview callback will be added in Phase 2B after testing pre-populate
