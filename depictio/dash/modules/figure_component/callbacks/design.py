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
            Output(
                {"type": "figure-design-preview", "index": MATCH}, "style", allow_duplicate=True
            ),
            Output(
                {"type": "code-mode-preview-graph", "index": MATCH}, "style", allow_duplicate=True
            ),
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
        prevent_initial_call="initial_duplicate",  # Allow initial call with duplicate outputs
    )
    def handle_mode_switch(mode, current_mode, dict_kwargs, visu_type_label, current_code):
        """Handle initial setup and user toggling between UI and Code modes."""
        NO_UPDATE_TUPLE = (dash.no_update,) * 6
        STYLE_VISIBLE = {"height": "100%", "width": "100%"}
        STYLE_HIDDEN = {"display": "none"}
        STYLE_BLOCK = {"display": "block"}

        # Guard: Return no_update if mode is None (component not ready)
        if mode is None:
            logger.debug("Mode is None - component not ready yet")
            return NO_UPDATE_TUPLE

        logger.info(f"🔄 MODE TOGGLE: {current_mode} -> {mode}")

        # Get component index for code interface creation
        component_index = _get_component_index_from_context()

        # Log action type for debugging
        is_initial_setup = current_mode is None or current_mode != mode
        action_type = "INITIAL SETUP" if is_initial_setup else "USER TOGGLE"
        logger.info(f"{action_type}: Setting {mode} mode for component {component_index}")

        is_code_mode = mode == "code"

        if is_code_mode:
            code_interface_children = create_code_mode_interface(
                component_index, current_code or ""
            )
            logger.info(f"Switched to CODE MODE for {component_index}")
            logger.info(
                f"   Populated editor with {len(current_code) if current_code else 0} characters"
            )
        else:
            # Create hidden code-status component to ensure callbacks work
            code_interface_children = [
                dmc.Alert(
                    id={"type": "code-status", "index": component_index},
                    title="UI Mode",
                    color="blue",
                    children="Component in UI mode",
                    style=STYLE_HIDDEN,
                )
            ]
            logger.info(f"Switched to UI MODE for {component_index}")

        return (
            STYLE_HIDDEN if is_code_mode else STYLE_BLOCK,  # ui_content_style
            STYLE_BLOCK if is_code_mode else STYLE_HIDDEN,  # code_content_style
            code_interface_children,
            mode,
            STYLE_HIDDEN if is_code_mode else STYLE_VISIBLE,  # ui_preview_style
            STYLE_VISIBLE if is_code_mode else STYLE_HIDDEN,  # code_preview_style
        )

    def _get_component_index_from_context() -> str:
        """Extract component index from callback context."""
        ctx = dash.callback_context
        try:
            if ctx.outputs_list:
                component_id = ctx.outputs_list[0]["id"]
                if isinstance(component_id, dict):
                    return component_id["index"]
        except Exception:
            pass
        return "unknown"

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
        if mode is None:
            logger.debug("store_generated_code: Mode is None - component not ready yet")
            return dash.no_update

        has_stored_code = stored_metadata and stored_metadata.get("code_content")
        logger.info("=== store_generated_code CALLBACK CALLED ===")
        logger.info(f"Mode: {mode}")
        logger.info(f"Dict kwargs: {dict_kwargs}")
        logger.info(f"Visualization type label: {visu_type_label}")
        logger.info(f"Current code content: {bool(current_code_content)}")
        logger.info(f"Stored metadata code: {bool(has_stored_code)}")

        # UI mode - no code update needed
        if mode != "code":
            logger.info("UI mode - no code update needed")
            return dash.no_update

        # Priority 1: Use code from stored_metadata (loading existing code mode figure)
        if stored_metadata and stored_metadata.get("mode") == "code" and has_stored_code:
            logger.info("✅ Using code from stored_metadata (existing code mode figure)")
            return stored_metadata.get("code_content")

        # Priority 2: Preserve existing code content (user already edited code)
        if current_code_content:
            logger.info("✅ Preserving existing code content")
            return current_code_content

        # Priority 3: Generate code from UI parameters (switching from UI to code mode)
        if dict_kwargs and visu_type_label:
            logger.info("🔄 Generating code from UI parameters")
            generated_code = convert_ui_params_to_code(dict_kwargs, visu_type_label)
            logger.info("✅ Code generated successfully")
            return generated_code

        # Priority 4: Return empty string for code mode without params
        logger.info("⚠️ Code mode but no parameters - returning empty code")
        return ""

    # Callback to sync code editor changes to code-content-store
    @app.callback(
        Output({"type": "code-content-store", "index": MATCH}, "data", allow_duplicate=True),
        [
            Input({"type": "code-editor", "index": MATCH}, "value"),
        ],
        [
            State({"type": "figure-mode-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def sync_code_editor_to_store(editor_value, current_mode):
        """Sync code editor changes to code-content-store for dashboard saving."""
        if current_mode != "code":
            logger.debug("Not in code mode - skipping code editor sync")
            return dash.no_update

        logger.info("📝 Syncing code editor to store")
        logger.info(f"   Code length: {len(editor_value) if editor_value else 0}")

        return editor_value or ""

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

    # Auto-execute code when switching to code mode with existing code (edit mode)
    @app.callback(
        Output({"type": "code-execute-btn", "index": MATCH}, "n_clicks"),
        [
            Input({"type": "figure-mode-store", "index": MATCH}, "data"),
        ],
        [
            State({"type": "code-content-store", "index": MATCH}, "data"),
            State({"type": "code-execute-btn", "index": MATCH}, "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def auto_execute_on_code_mode_load(mode, code_content, current_clicks):
        """Auto-execute code when loading code mode with existing code (edit mode)."""
        should_auto_execute = mode == "code" and code_content
        if not should_auto_execute:
            return dash.no_update

        logger.info("🔄 AUTO-EXECUTING code on mode load (edit mode)")
        logger.info(f"   Code length: {len(code_content)}")
        return (current_clicks or 0) + 1

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
            Output({"type": "code-mode-preview-graph", "index": MATCH}, "figure"),
            Output({"type": "code-mode-preview-graph", "index": MATCH}, "style"),
            Output({"type": "figure-design-preview", "index": MATCH}, "style"),
        ],
        Input({"type": "code-execute-btn", "index": MATCH}, "n_clicks"),
        [
            State({"type": "code-editor", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
        background=True,  # CRITICAL: Prevent UI blocking during data loading and code execution
    )
    def execute_code_preview(n_clicks, code_content, workflow_id, data_collection_id, local_data):
        """
        Execute code and show preview in left panel (code mode graph), hide UI mode graph.

        NOTE: Runs in background via Celery to prevent UI blocking during:
        - Data loading (load_deltatable_lite)
        - Code execution (SimpleCodeExecutor.execute_code)
        - Figure generation

        Requires Celery worker to be running (same as figure preview rendering).
        All imports must be inside function for Celery serialization.
        """
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import load_deltatable_lite
        from depictio.dash.modules.figure_component.simple_code_executor import (
            SimpleCodeExecutor,
        )

        # Style constants for graph visibility
        STYLE_VISIBLE = {"height": "100%", "width": "100%"}
        STYLE_HIDDEN = {"display": "none"}

        def error_response(title: str, message):
            """Build error response tuple showing UI mode graph."""
            return (title, message, "red", {}, STYLE_HIDDEN, STYLE_VISIBLE)

        def success_response(fig):
            """Build success response tuple showing code mode graph with figure."""
            figure_type = fig.data[0].type if fig.data else "unknown"
            data_points = len(fig.data[0].x) if fig.data and hasattr(fig.data[0], "x") else "N/A"
            message = dmc.Stack(
                [
                    dmc.Text("Code executed successfully! Preview shown on the left.", size="sm"),
                    dmc.Text(f"Figure type: {figure_type}", size="xs", c="gray"),
                    dmc.Text(f"Data points: {data_points}", size="xs", c="gray"),
                ],
                gap="xs",
            )
            return ("Success", message, "green", fig, STYLE_VISIBLE, STYLE_HIDDEN)

        def error_with_details(title: str, summary: str, details: str):
            """Build error response with code block showing details."""
            message = dmc.Stack(
                [
                    dmc.Text(summary, size="sm"),
                    dmc.Code(details, block=True, style={"fontSize": "11px"}),
                ],
                gap="xs",
            )
            return error_response(title, message)

        # Guard: no action if button not clicked or no code
        if not n_clicks or not code_content:
            return (dash.no_update,) * 6

        logger.info("=== EXECUTE CODE PREVIEW ===")
        logger.info(f"Code length: {len(code_content)} characters")

        # Validate inputs
        if not workflow_id or not data_collection_id:
            return error_response(
                "Error", "Please ensure workflow and data collection are selected."
            )

        if not local_data:
            return error_response("Error", "Authentication required.")

        try:
            # Load data
            token = local_data["access_token"]
            df = load_deltatable_lite(
                ObjectId(workflow_id), ObjectId(data_collection_id), TOKEN=token
            )

            if df.height == 0:
                return error_response("Error", "No data available in the selected data collection.")

            # Execute code
            executor = SimpleCodeExecutor()
            success, fig, message = executor.execute_code(code_content, df)

            if success:
                logger.info("Code execution successful")
                return success_response(fig)

            logger.error(f"Code execution failed: {message}")
            return error_with_details("Execution Error", "Code execution failed", message)

        except Exception as e:
            logger.error(f"Error during code execution: {e}", exc_info=True)
            return error_with_details("Error", "Unexpected error", str(e))

    logger.info(
        "✅ Figure design callbacks registered (mode toggle + code generation + code examples + columns info + theme + execute)"
    )


# Note: Live preview callback will be added in Phase 2B after testing pre-populate
