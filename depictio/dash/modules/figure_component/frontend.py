# Import necessary libraries
from collections import defaultdict
from typing import Any, Dict, List

import dash
import dash_mantine_components as dmc
import httpx
from dash import ALL, MATCH, Input, Output, Patch, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import get_dmc_button_color, is_enabled
from depictio.dash.modules.figure_component.code_mode import (
    convert_ui_params_to_code,
    create_code_mode_interface,
    evaluate_params_in_context,
    extract_params_from_code,
    extract_visualization_type_from_code,
)

# Depictio imports - Updated to use new robust system
from depictio.dash.modules.figure_component.component_builder import (
    AccordionBuilder,
    ComponentBuilder,
)
from depictio.dash.modules.figure_component.definitions import (
    get_available_visualizations,
    get_visualization_definition,
)

# Removed get_common_visualizations import - now using all visualizations in dropdown
from depictio.dash.modules.figure_component.simple_code_executor import SimpleCodeExecutor
from depictio.dash.modules.figure_component.state_manager import state_manager
from depictio.dash.modules.figure_component.utils import (
    build_figure,
    build_figure_frame,
)
from depictio.dash.utils import (
    UNSELECTED_STYLE,
    get_columns_from_data_collection,
    get_component_data,
)


def _get_required_parameters_for_visu(visu_type: str) -> List[str]:
    """Get required parameters for a visualization type using dynamic discovery."""
    try:
        # Use the visualization definition to get required parameters
        viz_def = get_visualization_definition(visu_type)
        required_params = []

        # Extract required parameters from the definition
        for param in viz_def.parameters:
            if param.required:
                required_params.append(param.name)

        # If no required parameters found in definition, use common fallbacks
        if not required_params:
            # Basic fallbacks for common visualization types
            if visu_type.lower() in ["histogram", "box", "violin"]:
                required_params = ["x"] if visu_type.lower() == "histogram" else ["y"]
            elif visu_type.lower() in ["pie", "sunburst", "treemap"]:
                required_params = ["values"]
            elif visu_type.lower() in ["timeline"]:
                required_params = ["x_start"]
            elif visu_type.lower() in ["umap"]:
                # Clustering visualizations don't have required parameters
                # They can work without explicit parameters (will use all numeric columns)
                required_params = []
            else:
                required_params = ["x", "y"]  # Default for most plots

        return required_params

    except Exception:
        # Fallback if visualization definition not found
        if visu_type.lower() in ["umap"]:
            return []  # Clustering visualizations don't require specific parameters
        return ["x", "y"]


def _needs_default_parameters(visu_type: str, dict_kwargs: Dict[str, Any]) -> bool:
    """Check if default parameters need to be set for a visualization type."""
    # Defensive handling: ensure dict_kwargs is a dict
    if not isinstance(dict_kwargs, dict):
        logger.warning(f"Expected dict for dict_kwargs, got {type(dict_kwargs)}: {dict_kwargs}")
        return True

    if not dict_kwargs:
        return True

    required_params = _get_required_parameters_for_visu(visu_type)

    # Check if any required parameters are missing or None
    for param in required_params:
        if param not in dict_kwargs or dict_kwargs.get(param) is None:
            return True

    return False


def _get_default_parameters(visu_type: str, columns_specs: Dict[str, List[str]]) -> Dict[str, Any]:
    """Get default parameters for a visualization type based on available columns."""
    defaults = {}
    required_params = _get_required_parameters_for_visu(visu_type)

    # Get available columns by type
    categorical_cols = columns_specs.get("object", [])
    numeric_cols = columns_specs.get("int64", []) + columns_specs.get("float64", [])

    for param in required_params:
        if param in ["x", "names"]:
            # Prefer categorical for x-axis and names
            if categorical_cols:
                defaults[param] = categorical_cols[0]
            elif numeric_cols:
                defaults[param] = numeric_cols[0]
        elif param in ["y", "values"]:
            # Prefer numeric for y-axis and values
            if numeric_cols:
                defaults[param] = numeric_cols[0]
            elif categorical_cols:
                defaults[param] = categorical_cols[0]

    # Add color column if available
    if categorical_cols and "color" not in defaults:
        defaults["color"] = categorical_cols[0]

    # Special handling for hierarchical visualizations (sunburst, treemap)
    if visu_type.lower() in ["sunburst", "treemap"]:
        # For hierarchical charts, set helpful defaults for optional parameters
        if "parents" not in defaults and len(categorical_cols) > 1:
            # Use second categorical column as parents if available
            defaults["parents"] = categorical_cols[1] if len(categorical_cols) > 1 else ""
        elif "parents" not in defaults:
            # Empty string is valid for root-level hierarchical charts
            defaults["parents"] = ""

        if "names" not in defaults and categorical_cols:
            defaults["names"] = categorical_cols[0]

        if "ids" not in defaults and categorical_cols:
            # Use first categorical column as IDs if available
            defaults["ids"] = categorical_cols[0]

    return {k: v for k, v in defaults.items() if v is not None}


def register_callbacks_figure_component(app):
    """Register all callbacks for the robust figure component system."""

    @dash.callback(
        Output({"type": "collapse", "index": MATCH}, "children"),
        [
            Input({"type": "edit-button", "index": MATCH}, "n_clicks"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
        ],
        [
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State("current-edit-parent-index", "data"),
            State({"type": "edit-button", "index": MATCH}, "id"),
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State("local-store", "data"),
            State("url", "pathname"),
            State({"type": "figure-mode-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=False,  # Prevent initial call to avoid loops
    )
    def build_parameter_interface(
        _n_clicks_edit,  # Prefixed with _ to indicate unused
        visu_type,
        workflow,
        data_collection,
        parent_index,
        edit_button_id,
        current_dict_kwargs,
        local_data,
        pathname,
        current_mode,
    ):
        """Build parameter interface using the new robust system."""

        if not local_data:
            raise dash.exceptions.PreventUpdate

        # Don't build UI parameter interface if in code mode
        if current_mode == "code":
            logger.info("🚫 SKIPPING UI PARAMETER INTERFACE - Component is in code mode")
            return html.Div()  # Return empty div for code mode

        logger.info("=== BUILDING PARAMETER INTERFACE ===")
        logger.info(f"Visualization type: {visu_type}")
        logger.info(f"Component ID: {edit_button_id.get('index') if edit_button_id else 'unknown'}")

        TOKEN = local_data["access_token"]
        dashboard_id = pathname.split("/")[-1]
        component_index = edit_button_id["index"] if edit_button_id else "unknown"

        logger.info(f"Component index: {component_index}")
        logger.info(f"parent_index: {parent_index}")
        logger.info(f"Workflow: {workflow}")
        logger.info(f"Data collection: {data_collection}")

        # Get existing component data
        component_data = None
        if parent_index:
            try:
                component_data = get_component_data(
                    input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
                )
                logger.info(
                    f"Edit mode: loaded component data: {component_data} from parent_index: {parent_index} for component {component_index}"
                )
                workflow = component_data.get("wf_id", workflow)
                data_collection = component_data.get("dc_id", data_collection)
                logger.info(f"Workflow after component data: {workflow}")
                logger.info(f"Data collection after component data: {data_collection}")
            except Exception as e:
                logger.warning(f"Failed to get component data: {e}")

        logger.info("Fetching available columns for data collection...")
        logger.info(f"Workflow ID: {workflow}")
        logger.info(f"Data Collection ID: {data_collection}")
        # Get available columns
        try:
            columns_json = get_columns_from_data_collection(workflow, data_collection, TOKEN)
            columns = list(columns_json.keys())
        except Exception as e:
            logger.error(f"Failed to get columns: {e}")
            columns = []
            columns_json = {}

        # Determine visualization type from segmented control
        if visu_type:  # visu_type is now the name (lowercase) from dropdown
            # Since we now use viz.name.lower() as dropdown value, use it directly
            visu_type = visu_type.lower()
        elif component_data and "visu_type" in component_data:
            visu_type = component_data["visu_type"].lower()
        else:
            visu_type = "scatter"  # Default fallback

        logger.info(f"Final visualization type: {visu_type}")

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
            # or fall back to component data if no current values exist
            parameters_to_load = current_dict_kwargs or (
                component_data.get("dict_kwargs", {}) if component_data else {}
            )

            if parameters_to_load:
                logger.info(f"Loading parameters into state: {parameters_to_load}")
                for param_name, value in parameters_to_load.items():
                    state.set_parameter_value(param_name, value)

            # Build UI components
            component_builder = ComponentBuilder(component_index, columns, columns_json)
            accordion_builder = AccordionBuilder(component_builder)

            # Build the complete accordion interface
            accordion = accordion_builder.build_full_accordion(viz_def, state)

            logger.info("Successfully built parameter interface")
            return accordion

        except Exception as e:
            logger.error(f"Error building parameter interface: {e}")
            return html.Div(
                [
                    dmc.Alert(
                        f"Error loading parameters: {str(e)}",
                        title="Parameter Loading Error",
                        color="red",
                    )
                ]
            )

    def _convert_parameter_value(param_name: str, value: Any) -> Any:
        """Convert string values back to their original types based on parameter definitions."""
        # Handle string representations of boolean values
        if isinstance(value, str):
            if value.lower() == "true":
                return True
            elif value.lower() == "false":
                return False

            # Handle specific parameters that need boolean conversion
            if param_name == "points" and value == "False":
                return False

            # Try to convert to numeric if it looks like a number
            try:
                # Try integer first
                if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
                    return int(value)
                # Try float
                return float(value)
            except ValueError:
                pass

        # Return original value if no conversion needed
        return value

    def _is_placeholder_code(code: str) -> bool:
        """Check if the code is placeholder/template code that shouldn't be used for parameter extraction."""
        if not code or not code.strip():
            return True

        # Check for common placeholder patterns
        placeholder_indicators = [
            "# Add your Plotly code here",
            "# Example:",
            "column1",
            "column2",
            "x='column1'",
            "y='column2'",
            "x='your_x_column'",
            "y='your_y_column'",
            "# Enter your Python/Plotly code here",
        ]

        # If the code contains placeholder indicators, it's likely placeholder code
        for indicator in placeholder_indicators:
            if indicator in code:
                return True

        # Check if it's very short (less than 20 characters of actual code)
        code_lines = [
            line.strip()
            for line in code.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        if len("".join(code_lines)) < 20:
            return True

        return False

    # Callback to sync dict_kwargs from stored-metadata-component after component recreation
    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data", allow_duplicate=True),
        [
            Input({"type": "stored-metadata-component", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,  # Required when using allow_duplicate=True
    )
    def sync_dict_kwargs_from_metadata(stored_metadata):
        """Sync dict_kwargs store from stored-metadata-component after edit/recreation."""
        if not stored_metadata or not isinstance(stored_metadata, dict):
            logger.warning("sync_dict_kwargs_from_metadata: No valid stored metadata")
            raise dash.exceptions.PreventUpdate

        dict_kwargs = stored_metadata.get("dict_kwargs", {})

        # Only update if we have non-empty dict_kwargs
        if dict_kwargs and isinstance(dict_kwargs, dict):
            logger.info(f"🔄 Syncing dict_kwargs from metadata: {dict_kwargs}")
            return dict_kwargs

        raise dash.exceptions.PreventUpdate

    # Universal parameter change listener using pattern matching
    # This callback listens to ANY component with pattern {"type": "param-*", "index": MATCH}
    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data"),
        [
            # This Input will match ANY parameter component dynamically
            Input({"type": ALL, "index": MATCH}, "value"),
            # Add support for DMC Switch 'checked' property
            Input({"type": ALL, "index": MATCH}, "checked"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def extract_parameters_universal(all_values, all_checked_values, existing_kwargs):
        """Universal parameter extraction using pattern matching."""

        # Get the callback context to understand what triggered this
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        # Get the triggered input ID
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

        try:
            import json

            triggered_id_dict = json.loads(triggered_id)
        except (json.JSONDecodeError, TypeError):
            raise dash.exceptions.PreventUpdate

        # Only process if it's a parameter input
        if not (
            isinstance(triggered_id_dict, dict)
            and triggered_id_dict.get("type", "").startswith("param-")
        ):
            raise dash.exceptions.PreventUpdate

        logger.info("=== UNIVERSAL PARAMETER EXTRACTION ===")
        logger.info(f"Triggered by: {triggered_id_dict}")

        # Extract parameters from callback context inputs
        parameters = {}

        # Get all inputs from the callback context
        for input_dict in ctx.inputs_list:
            for input_item in input_dict:
                input_id = input_item.get("id", {})
                if isinstance(input_id, dict) and input_id.get("type", "").startswith("param-"):
                    param_name = input_id["type"].replace("param-", "")

                    # Get value from the triggered values - try both 'value' and 'checked'
                    value = input_item.get("value")
                    checked = input_item.get("checked")

                    # Use checked for DMC Switch components (boolean parameters), value for others
                    actual_value = checked if checked is not None else value

                    # Include non-empty values
                    if actual_value is not None and actual_value != "" and actual_value != []:
                        # Convert string values back to their original types
                        converted_value = _convert_parameter_value(param_name, actual_value)
                        parameters[param_name] = converted_value
                    elif isinstance(actual_value, bool):  # Include boolean False
                        parameters[param_name] = actual_value
                    elif (
                        actual_value == ""
                    ):  # Include empty string for optional parameters like parents
                        # For hierarchical charts (sunburst, treemap), empty string is valid for parents
                        parameters[param_name] = actual_value

        logger.info(f"Extracted parameters: {parameters}")
        logger.info(f"Parameter count: {len(parameters)}")

        return parameters if parameters else (existing_kwargs or {})

    @app.callback(
        Output(
            {
                "type": "collapse",
                "index": MATCH,
            },
            "opened",
        ),
        [
            Input(
                {
                    "type": "edit-button",
                    "index": MATCH,
                },
                "n_clicks",
            )
        ],
        [
            State(
                {
                    "type": "collapse",
                    "index": MATCH,
                },
                "opened",
            )
        ],
        # prevent_initial_call=True,
    )
    def toggle_collapse(n, _is_open):  # Prefixed with _ to indicate unused
        # print(n, is_open, n % 2 == 0)
        logger.info(f"Toggle collapse called with n={n}, returning is_open={n % 2 != 0}")
        if n % 2 == 0:
            return False
        else:
            return True

    @app.callback(
        Output({"type": "btn-done-edit", "index": MATCH}, "disabled", allow_duplicate=True),
        [
            Input({"type": "dict_kwargs", "index": MATCH}, "data"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
        ],
        prevent_initial_call=True,
    )
    def disable_done_button(dict_kwargs_value, visu_type_value):
        # Enable the button if either parameters exist or a visualization type is selected
        if dict_kwargs_value or visu_type_value:
            return False
        return True

    # Removed old fragile parameter extraction callback - replaced with robust version above

    # Callback to show loading state when inputs change
    @app.callback(
        [
            Output({"type": "figure-loading", "index": MATCH}, "children"),
            Output({"type": "figure-loading", "index": MATCH}, "style"),
        ],
        [
            Input({"type": "dict_kwargs", "index": MATCH}, "data"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
        ],
        prevent_initial_call=True,
    )
    def show_loading_state(dict_kwargs, visu_type_label):
        """Show loading spinner when figure inputs change - DISABLED."""
        # Disabled loading state to prevent infinite "Generating figure" issue
        return html.Div(), {"display": "none"}

    @app.callback(
        [
            Output({"type": "figure-body", "index": MATCH}, "children"),
            Output({"type": "figure-loading", "index": MATCH}, "children", allow_duplicate=True),
            Output({"type": "figure-loading", "index": MATCH}, "style", allow_duplicate=True),
        ],
        [
            Input({"type": "dict_kwargs", "index": MATCH}, "data"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            Input({"type": "figure-mode-store", "index": MATCH}, "data"),  # Trigger on mode changes
            State("theme-store", "data"),  # Keep as State - theme handled separately
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "segmented-control-visu-graph", "index": MATCH}, "id"),
            State("current-edit-parent-index", "data"),  # Retrieve parent_index
            State("local-store", "data"),
            State("url", "pathname"),
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def update_figure(*args):
        dict_kwargs = args[0]
        visu_type_label = args[1]  # This is now the visualization name from dropdown
        current_mode = args[2]  # Current mode from figure-mode-store (now Input)
        theme_data = args[3]  # Theme is 4th in the State list
        workflow_id = args[4]
        data_collection_id = args[5]
        component_id_dict = args[6]
        parent_index = args[7]
        local_data = args[8]
        pathname = args[9]
        stored_metadata = args[10]  # Stored metadata containing code_content

        logger.info("=== UPDATE FIGURE CALLBACK ===")
        logger.info(f"Received dict_kwargs: {dict_kwargs}")
        logger.info(f"Visualization type label: {visu_type_label}")
        logger.info(f"Current mode: {current_mode}")
        logger.info(f"Workflow ID: {workflow_id}")
        logger.info(f"Data Collection ID: {data_collection_id}")
        logger.info(f"Component ID dict: {component_id_dict}")
        logger.info(f"Parent index: {parent_index}")

        # Don't update if in code mode - let code execution handle it
        if current_mode == "code":
            logger.info("Skipping UI figure update - in code mode")
            raise dash.exceptions.PreventUpdate

        if not local_data:
            raise dash.exceptions.PreventUpdate

        TOKEN = local_data["access_token"]
        dashboard_id = pathname.split("/")[-1]
        component_id = component_id_dict["index"]

        logger.info("=== UPDATE FIGURE CALLBACK DEBUG ===")
        logger.info(f"Component ID: {component_id}")
        logger.info(f"Parent index: {parent_index}")
        logger.info(f"Visualization type label: {visu_type_label}")
        logger.info(f"Parameters received: {dict_kwargs}")
        logger.info(f"Parameters type: {type(dict_kwargs)}")
        logger.info(f"Parameters empty: {not dict_kwargs or dict_kwargs == {'x': None, 'y': None}}")

        # visu_type_label is now the visualization name (lowercase) from dropdown
        visu_type = "scatter"  # Default fallback
        if visu_type_label:
            visu_type = visu_type_label.lower()

        # Get component data if available
        component_data = None
        if parent_index:
            try:
                component_data = get_component_data(
                    input_id=parent_index, dashboard_id=dashboard_id, TOKEN=TOKEN
                )
                logger.info(f"Component data: {component_data}")
            except Exception as e:
                logger.warning(f"Failed to get component data: {e}")

        # Use component data to override if available, but prioritize dropdown selection
        if component_data:
            # Only use stored visu_type if no dropdown selection was made
            if "visu_type" in component_data and not visu_type_label:
                visu_type = component_data["visu_type"]
            # Always load stored parameters if no current parameters exist
            if not dict_kwargs and "dict_kwargs" in component_data:
                dict_kwargs = component_data["dict_kwargs"]

        # Get column information for defaults
        try:
            workflow_id = workflow_id or (component_data.get("wf_id", "") if component_data else "")
            data_collection_id = data_collection_id or (
                component_data.get("dc_id", "") if component_data else ""
            )
            columns_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)
            columns_specs_reformatted = defaultdict(list)
            {columns_specs_reformatted[v["type"]].append(k) for k, v in columns_json.items()}

            # Check if we need to set default parameters for the specific visualization type
            # Only auto-generate parameters if the setting is enabled
            needs_defaults = _needs_default_parameters(visu_type, dict_kwargs)

            if needs_defaults and settings.dash.auto_generate_figures:
                logger.info(f"Setting default parameters for {visu_type} visualization")
                default_params = _get_default_parameters(visu_type, columns_specs_reformatted)

                # Update dict_kwargs with defaults (preserve existing params)
                dict_kwargs = {**default_params, **dict_kwargs}
            elif needs_defaults and not settings.dash.auto_generate_figures:
                logger.info(
                    f"Auto-generate figures disabled, skipping default parameter assignment for {visu_type}"
                )
                # Don't auto-assign parameters, but allow manual ones to proceed

        except Exception as e:
            logger.error(f"Failed to get column information: {e}")
            if not dict_kwargs or dict_kwargs == {"x": None, "y": None}:
                dict_kwargs = {}

        logger.info("BEFORE FIGURE CREATION:")
        logger.info(f"  Final visu_type: {visu_type}")
        logger.info(f"  Final dict_kwargs: {dict_kwargs}")
        logger.info(f"  Dict_kwargs keys: {list(dict_kwargs.keys()) if dict_kwargs else 'None'}")
        logger.info(
            f"  Dict_kwargs values: {list(dict_kwargs.values()) if dict_kwargs else 'None'}"
        )

        # Get data collection specs
        dc_config = None
        try:
            dc_specs = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            ).json()
            dc_config = dc_specs.get("config", {})
        except Exception as e:
            logger.error(f"Failed to get data collection specs: {e}")
            raise dash.exceptions.PreventUpdate

        # Extract theme
        theme = "light"
        if theme_data:
            if isinstance(theme_data, dict):
                theme = theme_data.get("colorScheme", "light")
            elif isinstance(theme_data, str):
                theme = theme_data

        logger.info("Theme: %s", theme)

        # Build figure with robust error handling
        try:
            figure_kwargs = {
                "index": component_id,
                "dict_kwargs": dict_kwargs,
                "visu_type": visu_type,
                "wf_id": workflow_id,
                "dc_id": data_collection_id,
                "dc_config": dc_config,
                "access_token": TOKEN,
                "theme": theme,
                "build_frame": False,  # Don't build frame - return just the content for stepper mode
                "stepper": True,
            }

            # Add mode and code_content if component is in code mode
            if current_mode == "code":
                figure_kwargs["mode"] = "code"
                if stored_metadata and isinstance(stored_metadata, dict):
                    code_content = stored_metadata.get("code_content", "")
                    if code_content:
                        figure_kwargs["code_content"] = code_content
                        logger.info(
                            f"Added mode=code and code_content to figure_kwargs for component {component_id}"
                        )
                    else:
                        logger.warning(
                            f"Code mode detected but no code_content in stored metadata for component {component_id}"
                        )
                else:
                    logger.warning(
                        f"Code mode detected but no valid stored_metadata for component {component_id}"
                    )

            if parent_index:
                figure_kwargs["parent_index"] = parent_index

            logger.info("CALLING build_figure WITH:")
            logger.info(f"  dict_kwargs: {figure_kwargs['dict_kwargs']}")
            logger.info(f"  visu_type: {figure_kwargs['visu_type']}")
            logger.info(f"  wf_id: {figure_kwargs['wf_id']}")
            logger.info(f"  dc_id: {figure_kwargs['dc_id']}")
            logger.info(f"  theme: {figure_kwargs['theme']}")
            logger.info(f"  build_frame: {figure_kwargs['build_frame']}")
            logger.info(f"  stepper: {figure_kwargs['stepper']}")
            logger.info(f"  parent_index: {figure_kwargs.get('parent_index', 'None')}")

            figure_result = build_figure(**figure_kwargs)
            logger.info(f"build_figure RETURNED: {type(figure_result)}")

            # Return figure content and hide loading
            hidden_loading_style = {"display": "none"}
            return figure_result, html.Div(), hidden_loading_style

        except Exception as e:
            logger.error(f"Failed to build figure: {e}")
            error_content = html.Div(
                [
                    dmc.Alert(
                        f"Error building figure: {str(e)}", title="Figure Build Error", color="red"
                    )
                ]
            )
            # Return error content and hide loading
            hidden_loading_style = {"display": "none"}
            return error_content, html.Div(), hidden_loading_style

    # Callback to initialize figure with default visualization when component is first created
    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data", allow_duplicate=True),
        [
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def initialize_default_parameters(
        visu_type_label, current_kwargs, workflow_id, data_collection_id, local_data
    ):
        """Initialize default parameters when visualization type changes, preserving shared parameters."""
        logger.info("=== PARAMETER PRESERVATION TRIGGERED ===")
        logger.info(f"Visualization type: {visu_type_label}")
        logger.info(f"Current parameters: {current_kwargs}")
        logger.info(f"Current parameters type: {type(current_kwargs)}")
        logger.info(f"Has workflow_id: {bool(workflow_id)}")
        logger.info(f"Has data_collection_id: {bool(data_collection_id)}")
        logger.info(f"Has local_data: {bool(local_data)}")

        # Check auto_generate_figures setting
        if not settings.dash.auto_generate_figures:
            logger.info(
                "Auto-generate figures disabled, skipping automatic parameter initialization"
            )
            raise dash.exceptions.PreventUpdate

        # Check if we need to prevent update to avoid race conditions
        ctx = dash.callback_context
        if not ctx.triggered:
            logger.info("No trigger detected, preventing update")
            raise dash.exceptions.PreventUpdate

        triggered_prop = ctx.triggered[0]["prop_id"]
        logger.info(f"Triggered by: {triggered_prop}")

        # Only process if visualization type actually changed
        if "segmented-control-visu-graph" not in triggered_prop:
            logger.info("Not triggered by visualization change, preventing update")
            raise dash.exceptions.PreventUpdate

        if not local_data or not workflow_id or not data_collection_id:
            logger.warning("Missing required data for parameter initialization")
            raise dash.exceptions.PreventUpdate

        try:
            # Get column information for defaults
            TOKEN = local_data["access_token"]
            columns_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)
            columns_specs_reformatted = defaultdict(list)
            {columns_specs_reformatted[v["type"]].append(k) for k, v in columns_json.items()}

            # visu_type_label is now the visualization name (lowercase) from dropdown
            visu_type = "scatter"  # Default fallback
            if visu_type_label:
                visu_type = visu_type_label.lower()

            # Get default parameters for this visualization type
            default_params = _get_default_parameters(visu_type, columns_specs_reformatted)

            # If we have existing parameters, preserve shared ones
            if current_kwargs and current_kwargs not in [{}, {"x": None, "y": None}]:
                try:
                    logger.info(f"Attempting to preserve parameters from: {current_kwargs}")

                    # Get required parameters for the new visualization
                    new_viz_def = get_visualization_definition(visu_type)
                    new_param_names = {param.name for param in new_viz_def.parameters}
                    logger.info(
                        f"New visualization '{visu_type}' accepts parameters: {new_param_names}"
                    )

                    # Define common parameters that should be preserved across all visualizations
                    common_params = {
                        "title",
                        "width",
                        "height",
                        "template",
                        "opacity",
                        "hover_name",
                        "hover_data",
                        "custom_data",
                        "labels",
                        "color_discrete_sequence",
                        "color_continuous_scale",
                        "log_x",
                        "log_y",
                        "range_x",
                        "range_y",
                        "category_orders",
                        "color_discrete_map",
                        "animation_frame",
                        "animation_group",
                        "facet_row",
                        "facet_col",
                        "facet_col_wrap",
                    }

                    # Preserve parameters that exist in both old and new visualization, OR are common parameters
                    preserved_params = {}
                    for param_name, value in current_kwargs.items():
                        should_preserve = (
                            param_name in new_param_names  # Parameter exists in new visualization
                            or param_name in common_params  # Parameter is a common parameter
                        )

                        if (
                            should_preserve and value is not None and value != "" and value != []
                        ) or (
                            should_preserve and isinstance(value, bool)
                        ):  # Preserve boolean False
                            preserved_params[param_name] = value
                            logger.info(f"Preserving parameter '{param_name}': {value}")

                    logger.info(f"Parameters eligible for preservation: {preserved_params}")

                    # Merge preserved parameters with defaults (preserved takes priority)
                    final_params = {**default_params, **preserved_params}

                    logger.info(f"Default parameters for {visu_type}: {default_params}")
                    logger.info(f"Preserved parameters for {visu_type}: {preserved_params}")
                    logger.info(f"Final merged parameters for {visu_type}: {final_params}")

                    # Only return if we actually have some parameters to preserve
                    if preserved_params:
                        logger.info(f"Successfully preserved {len(preserved_params)} parameters")
                        return final_params
                    else:
                        logger.info("No parameters could be preserved, using defaults")
                        return default_params if default_params else {"x": None, "y": None}

                except Exception as e:
                    logger.error(f"Error preserving parameters: {e}, using defaults only")
                    return default_params if default_params else {"x": None, "y": None}
            else:
                # No existing parameters, use defaults
                logger.info(
                    f"No existing parameters to preserve, initializing defaults for {visu_type}: {default_params}"
                )
                return default_params if default_params else {"x": None, "y": None}

        except Exception as e:
            logger.error(f"Error initializing default parameters: {e}")
            return {"x": None, "y": None}

    # Callback to automatically initialize figure when component loads
    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data", allow_duplicate=True),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def auto_initialize_on_load(
        workflow_id, data_collection_id, current_kwargs, visu_type_label, local_data
    ):
        """Auto-initialize default parameters when workflow/datacollection are set."""
        # Check auto_generate_figures setting
        if not settings.dash.auto_generate_figures:
            logger.info("Auto-generate figures disabled, skipping auto-initialization on load")
            raise dash.exceptions.PreventUpdate

        # Only trigger if we have empty kwargs and all required data
        if current_kwargs or not workflow_id or not data_collection_id or not local_data:
            raise dash.exceptions.PreventUpdate

        try:
            # Get column information for defaults
            TOKEN = local_data["access_token"]
            columns_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)
            columns_specs_reformatted = defaultdict(list)
            {columns_specs_reformatted[v["type"]].append(k) for k, v in columns_json.items()}

            # visu_type_label is now the visualization name (lowercase) from dropdown
            visu_type = "scatter"
            if visu_type_label:
                visu_type = visu_type_label.lower()

            # Get default parameters for this visualization type
            default_params = _get_default_parameters(visu_type, columns_specs_reformatted)

            logger.info(f"Auto-initializing default parameters for {visu_type}: {default_params}")
            return default_params if default_params else {}

        except Exception as e:
            logger.error(f"Error auto-initializing default parameters: {e}")
            return {}

    # Simple callback to trigger figure generation when component is created
    @app.callback(
        Output({"type": "figure-body", "index": MATCH}, "children", allow_duplicate=True),
        [
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "id"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State("current-edit-parent-index", "data"),  # Retrieve parent_index
            State("local-store", "data"),
            State("theme-store", "data"),
            State("url", "pathname"),
            State({"type": "figure-mode-store", "index": MATCH}, "data"),
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        ],
        prevent_initial_call="initial_load",
    )
    def generate_default_figure_on_load(
        visu_type_label,
        component_index,
        dict_kwargs,
        workflow_id,
        data_collection_id,
        parent_index,
        local_data,
        theme_data,
        pathname,
        current_mode,
        stored_metadata,
    ):
        logger.info("=== GENERATE DEFAULT FIGURE CALLBACK ===")
        logger.info(f"Visualization type label: {visu_type_label}")
        logger.info(f"Component index: {component_index}")
        logger.info(f"Current mode: {current_mode}")
        logger.info(f"Current parameters: {dict_kwargs}")
        logger.info(f"dict_kwargs.keys: {len(list(dict_kwargs.keys()))}")
        logger.info(f"Workflow ID: {workflow_id}")
        logger.info(f"Data Collection ID: {data_collection_id}")
        logger.info(f"parent_index: {parent_index}")
        logger.info(f"pathname: {pathname}")

        # Don't generate default figure if in code mode - let code execution handle it
        if current_mode == "code":
            logger.info("Skipping default figure generation - in code mode")
            raise dash.exceptions.PreventUpdate

        # Check auto_generate_figures setting - but allow if this is an edit mode (parent_index exists)
        # Edit mode should always show existing figures, only new figures are controlled by the setting
        if not settings.dash.auto_generate_figures and not parent_index:
            logger.info(
                "Auto-generate figures disabled and not in edit mode, skipping default figure generation"
            )
            # raise dash.exceptions.PreventUpdate
            return html.Div(
                dmc.Center(
                    dmc.Text(
                        "Select a visualization type and core parameters to start generating a figure.",
                        ta="center",
                        c="gray",
                        size="md",
                    )
                ),
                style={
                    "height": "100%",
                    "minHeight": "300px",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "width": "100%",
                },
            )

        # Get existing component data
        component_data = None
        if parent_index:
            try:
                dashboard_id = pathname.split("/")[-1]
                component_data = get_component_data(
                    input_id=parent_index,
                    dashboard_id=dashboard_id,
                    TOKEN=local_data["access_token"],
                )
                logger.info(
                    f"Edit mode: loaded component data: {component_data} from parent_index: {parent_index} for component {component_index}"
                )
                workflow = component_data.get("wf_id", workflow_id)
                data_collection = component_data.get("dc_id", data_collection_id)
                logger.info(f"Workflow after component data: {workflow}")
                logger.info(f"Data collection after component data: {data_collection}")
            except Exception as e:
                logger.warning(f"Failed to get component data: {e}")

        # Get the actual component ID from the callback context
        if not component_index:
            component_id = "default_component"
        else:
            component_id = component_index["index"]

        if not local_data:
            raise dash.exceptions.PreventUpdate

        # Prevent update if we don't have the required workflow and data collection IDs
        # This can happen when the callback is triggered during edit mode
        if not workflow_id or not data_collection_id:
            logger.info("Missing workflow_id or data_collection_id, preventing figure generation")
            raise dash.exceptions.PreventUpdate

        if len(list(dict_kwargs.keys())) == 0 and parent_index:
            try:
                component_data = get_component_data(
                    input_id=parent_index,
                    dashboard_id=pathname.split("/")[-1],
                    TOKEN=local_data["access_token"],
                )
                workflow_id = component_data.get("wf_id", workflow_id)
                data_collection_id = component_data.get("dc_id", data_collection_id)
                dict_kwargs = component_data.get("dict_kwargs", dict_kwargs)
                logger.info("------ COMPONENT DATA LOADED ---")
                logger.info(f"Loaded component data: {component_data}")
                logger.info(f"Workflow ID: {workflow_id}")
                logger.info(f"Data Collection ID: {data_collection_id}")
            except Exception as e:
                logger.error(f"Failed to get component data: {e}")

        try:
            TOKEN = local_data["access_token"]

            # visu_type_label is now the visualization name (lowercase) from dropdown
            visu_type = "scatter"  # Default fallback
            if visu_type_label:
                visu_type = visu_type_label.lower()

            # If no parameters set, generate defaults (only if auto_generate_figures is enabled)
            if not dict_kwargs or dict_kwargs in [{}, {"x": None, "y": None}]:
                if settings.dash.auto_generate_figures:
                    columns_json = get_columns_from_data_collection(
                        workflow_id, data_collection_id, TOKEN
                    )
                    columns_specs_reformatted = defaultdict(list)
                    {
                        columns_specs_reformatted[v["type"]].append(k)
                        for k, v in columns_json.items()
                    }

                    dict_kwargs = _get_default_parameters(visu_type, columns_specs_reformatted)
                    logger.info(f"Generated default parameters for {visu_type}: {dict_kwargs}")
                else:
                    logger.info(
                        f"Auto-generate figures disabled, not generating default parameters for {visu_type}"
                    )
                    # Don't generate defaults, use empty dict

            if not dict_kwargs:
                raise dash.exceptions.PreventUpdate

            # Get data collection specs
            try:
                dc_specs = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                ).json()
                dc_config = dc_specs.get("config", {})
            except Exception as e:
                logger.error(f"Failed to get data collection specs in generate_default_figure: {e}")
                dc_config = {}

            # Extract theme
            theme = "light"
            if theme_data:
                if isinstance(theme_data, dict):
                    theme = theme_data.get("colorScheme", "light")
                elif isinstance(theme_data, str):
                    theme = theme_data

            # Build figure
            figure_kwargs = {
                "index": component_id,  # Use the correct component ID
                "dict_kwargs": dict_kwargs,
                "visu_type": visu_type,
                "wf_id": workflow_id,
                "dc_id": data_collection_id,
                "dc_config": dc_config,
                "access_token": TOKEN,
                "theme": theme,
                "build_frame": True,
                "stepper": True,
            }

            # Add mode and code_content if component is in code mode
            if current_mode == "code":
                figure_kwargs["mode"] = "code"
                if stored_metadata and isinstance(stored_metadata, dict):
                    code_content = stored_metadata.get("code_content", "")
                    if code_content:
                        figure_kwargs["code_content"] = code_content
                        logger.info(
                            f"Added mode=code and code_content to figure_kwargs for component {component_index}"
                        )
                    else:
                        logger.warning(
                            f"Code mode detected but no code_content in stored metadata for component {component_index}"
                        )
                else:
                    logger.warning(
                        f"Code mode detected but no valid stored_metadata for component {component_index}"
                    )

            # Add parent_index if available
            if parent_index:
                figure_kwargs["parent_index"] = parent_index

            return build_figure(**figure_kwargs)

        except Exception as e:
            logger.error(f"Error generating default figure: {e}")
            return html.Div(
                [
                    dmc.Alert(
                        f"Error generating default figure: {str(e)}",
                        title="Figure Generation Error",
                        color="red",
                    )
                ]
            )

    # Client-side callback to preserve scroll position in collapse panel
    app.clientside_callback(
        """
        function(dict_kwargs) {
            try {
                // Store scroll position before parameter change
                const collapseElement = document.querySelector('[id*="collapse"]');
                if (collapseElement) {
                    const scrollTop = collapseElement.scrollTop;
                    // Use a simple key for sessionStorage
                    sessionStorage.setItem('figure_collapse_scroll_position', scrollTop);
                }
            } catch (error) {
                console.log('Error storing scroll position:', error);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output({"type": "scroll-store", "index": MATCH}, "data"),
        Input({"type": "dict_kwargs", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )

    # Client-side callback to restore scroll position after parameter change
    app.clientside_callback(
        """
        function(collapse_children) {
            try {
                // Restore scroll position after content update
                setTimeout(() => {
                    const collapseElement = document.querySelector('[id*="collapse"]');
                    if (collapseElement) {
                        const scrollTop = sessionStorage.getItem('figure_collapse_scroll_position');
                        if (scrollTop !== null && scrollTop !== undefined) {
                            collapseElement.scrollTop = parseInt(scrollTop);
                        }
                    }
                }, 100);
            } catch (error) {
                console.log('Error restoring scroll position:', error);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output({"type": "scroll-restore", "index": MATCH}, "data"),
        Input({"type": "collapse", "index": MATCH}, "children"),
        prevent_initial_call=True,
    )

    # Removed separate initial setup callback to avoid race conditions

    # Mode toggle callback - handles both initial setup and user interactions
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
        """Handle initial setup and user toggling between UI and Code modes"""
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

        if mode == "code":
            # Switch to code mode interface
            ui_content_style = {"display": "none"}
            code_content_style = {"display": "block"}
            code_interface_children = create_code_mode_interface(component_index)
            logger.info(f"Switched to CODE MODE for {component_index}")
        else:
            # Switch to UI mode interface
            ui_content_style = {"display": "block"}
            code_content_style = {"display": "none"}
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
        """Store generated code when switching to code mode"""

        logger.info("=== store_generated_code CALLBACK CALLED ===")
        logger.info(f"Mode: {mode}")
        logger.info(f"Dict kwargs: {dict_kwargs}")
        logger.info(f"Visualization type label: {visu_type_label}")
        logger.info(f"Current code content: {bool(current_code_content)}")
        logger.info(
            f"Stored metadata code: {bool(stored_metadata and stored_metadata.get('code_content'))}"
        )

        if mode == "code":
            # Check if we already have existing code content - preserve it!
            existing_code = None

            # Priority 1: stored metadata code_content (from saved component)
            if stored_metadata and isinstance(stored_metadata, dict):
                metadata_code = stored_metadata.get("code_content", "")
                if metadata_code and metadata_code.strip():
                    existing_code = metadata_code
                    logger.info("Using existing code from stored metadata")

            # Priority 2: current code content store
            if not existing_code and current_code_content and current_code_content.strip():
                existing_code = current_code_content
                logger.info("Using existing code from code content store")

            # If we have existing code, preserve it
            if existing_code:
                logger.info("Preserving existing code content, not generating new code")
                return existing_code

            # Only generate new code if no existing code
            logger.info("No existing code found, generating code from UI parameters")
            if dict_kwargs:
                # visu_type_label is now the visualization name (lowercase) from dropdown
                visu_type = "scatter"  # Default fallback
                if visu_type_label:
                    visu_type = visu_type_label.lower()

                logger.info(f"Converting to visu_type: {visu_type}")

                # Convert UI parameters to code
                generated_code = convert_ui_params_to_code(dict_kwargs, visu_type)
                logger.info(f"Generated code: {generated_code}")

                if generated_code:
                    return generated_code
            else:
                logger.info("No dict_kwargs, returning executable template")
                # Return a more executable default template
                return "# Example: Basic scatter plot\nfig = px.scatter(df, x=df.columns[0] if len(df.columns) > 0 else None, y=df.columns[1] if len(df.columns) > 1 else None)"

        logger.info("Not in code mode, returning no_update")
        return dash.no_update

    # Update code editor from stored code and handle clear button
    @app.callback(
        Output({"type": "code-editor", "index": MATCH}, "value"),
        [
            Input({"type": "code-content-store", "index": MATCH}, "data"),
            Input({"type": "code-clear-btn", "index": MATCH}, "n_clicks"),
        ],
        prevent_initial_call=False,
    )
    def update_code_editor(stored_code, clear_clicks):
        """Update code editor from stored code or clear button"""

        ctx = dash.callback_context

        # Handle initial load (no trigger) - load stored code if available
        if not ctx.triggered:
            logger.info(f"=== update_code_editor INITIAL LOAD: stored_code={stored_code} ===")
            if stored_code:
                logger.info("Loading initial code content into Ace editor")
                return stored_code
            else:
                logger.info("No initial code content, keeping empty editor")
                return ""

        triggered_prop = ctx.triggered[0]["prop_id"]
        logger.info(f"=== update_code_editor TRIGGERED by: {triggered_prop} ===")

        # Check if clear button was clicked
        if "code-clear-btn" in triggered_prop:
            logger.info("Clear button clicked, clearing code editor")
            return ""

        # Check if stored code was updated
        if "code-content-store" in triggered_prop:
            logger.info(f"Stored code updated: {stored_code}")
            if stored_code:
                return stored_code

        return dash.no_update

    # Parameter preservation callback - Code to UI
    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data", allow_duplicate=True),
        [
            Input({"type": "figure-mode-toggle", "index": MATCH}, "value"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State({"type": "code-content-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def preserve_code_to_ui(mode, current_kwargs, stored_code):
        """Preserve parameters when switching to UI mode"""
        logger.info(f"Code to UI preservation triggered: mode={mode}")
        logger.info(f"Current kwargs: {current_kwargs}")
        logger.info(f"Stored code: {stored_code}")

        # Only sync when switching to UI mode
        if mode == "ui" and stored_code:
            try:
                # Check if the code is just placeholder/template code
                if _is_placeholder_code(stored_code):
                    logger.info(
                        "Code appears to be placeholder/template, skipping parameter extraction"
                    )
                    return dash.no_update

                # Extract parameters from the stored code
                extracted_params = extract_params_from_code(stored_code)

                logger.info(f"Extracted params from code: {extracted_params}")

                # Merge with existing parameters, prioritizing extracted ones
                if extracted_params:
                    updated_kwargs = {**(current_kwargs or {}), **extracted_params}
                    logger.info(f"Updated kwargs for UI mode: {updated_kwargs}")
                    return updated_kwargs

            except Exception as e:
                logger.error(f"Failed to extract parameters from code: {e}")

        return dash.no_update

    # Automatic code execution when switching to code mode with existing code
    @app.callback(
        [
            Output({"type": "code-generated-figure", "index": MATCH}, "data", allow_duplicate=True),
            Output({"type": "code-status", "index": MATCH}, "children", allow_duplicate=True),
            Output({"type": "code-status", "index": MATCH}, "color", allow_duplicate=True),
            Output({"type": "code-status", "index": MATCH}, "title", allow_duplicate=True),
        ],
        [
            Input({"type": "figure-mode-store", "index": MATCH}, "data"),
        ],
        [
            State({"type": "code-content-store", "index": MATCH}, "data"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State("local-store", "data"),
        ],
        prevent_initial_call="initial_duplicate",  # Required for allow_duplicate with initial calls
    )
    def auto_execute_code_on_mode_switch(
        mode, stored_code, workflow_id, data_collection_id, local_data
    ):
        """Automatically execute code when switching to code mode with existing code"""
        logger.info(f"=== AUTO CODE EXECUTION: mode={mode}, has_code={bool(stored_code)} ===")

        # Get component index to check if it's a stepper component
        ctx = dash.callback_context
        component_index = "unknown"
        try:
            if ctx.outputs_list:
                output_id = ctx.outputs_list[0]["id"]
                if isinstance(output_id, dict):
                    component_index = output_id.get("index", "unknown")
        except Exception:
            pass

        # Skip auto-execution for stepper components (they don't have code interface yet)
        if component_index.endswith("-tmp"):
            logger.info(f"Skipping auto-execution for stepper component: {component_index}")
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # Only auto-execute when switching to code mode and we have meaningful code
        if mode != "code" or not stored_code or not stored_code.strip():
            logger.info("Not executing: not in code mode or no code available")
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # Don't auto-execute template/placeholder code
        if _is_placeholder_code(stored_code):
            logger.info("Not executing: code appears to be template/placeholder")
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if not local_data or not workflow_id or not data_collection_id:
            logger.info("Not executing: missing required data")
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        try:
            # Get dataset from actual data collection
            from depictio.api.v1.deltatables_utils import load_deltatable_lite

            TOKEN = local_data["access_token"]
            loaded_df = load_deltatable_lite(workflow_id, data_collection_id, TOKEN=TOKEN)
            df = loaded_df

            # Execute code securely
            from depictio.dash.modules.figure_component.simple_code_executor import (
                SimpleCodeExecutor,
            )

            executor = SimpleCodeExecutor()
            success, result, message = executor.execute_code(stored_code, df)

            if success and result:
                # Store the figure data with metadata for further processing
                figure_data = {
                    "figure": result.to_dict(),
                    "code": stored_code,
                    "workflow_id": workflow_id,
                    "data_collection_id": data_collection_id,
                }
                logger.info("✅ Auto-executed code successfully on mode switch")
                return (
                    figure_data,
                    "Code executed automatically",
                    "green",
                    "Auto-Execution Success",
                )
            else:
                logger.warning(f"Auto-execution failed: {message}")
                return (None, f"Auto-execution failed: {message}", "red", "Auto-Execution Error")

        except Exception as e:
            error_msg = f"Auto-execution error: {str(e)}"
            logger.error(error_msg)
            return (None, error_msg, "red", "Auto-Execution Error")

    # Manual code execution callback (Execute button)
    @app.callback(
        [
            Output({"type": "code-generated-figure", "index": MATCH}, "data"),
            Output({"type": "code-status", "index": MATCH}, "children"),
            Output({"type": "code-status", "index": MATCH}, "color"),
            Output({"type": "code-status", "index": MATCH}, "title"),
            Output({"type": "dict_kwargs", "index": MATCH}, "data", allow_duplicate=True),
            # Output(
            #     {"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True
            # ),
        ],
        [
            Input({"type": "code-execute-btn", "index": MATCH}, "n_clicks"),
        ],
        [
            State({"type": "code-editor", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            # State({"type": "stored-metadata-component", "index": MATCH}, "data"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    # def execute_code(n_clicks, code, workflow_id, data_collection_id, stored_metadata, local_data):
    def execute_code(n_clicks, code, workflow_id, data_collection_id, local_data):
        """Execute Python code and generate figure"""
        logger.info(
            f"execute_code called: n_clicks={n_clicks}, code_length={len(code) if code else 0}, workflow_id={workflow_id}, data_collection_id={data_collection_id}"
        )
        if not n_clicks or not code:
            logger.info("Skipping execution: no clicks or no code")
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if not local_data:
            return (
                html.Div("Authentication required"),
                "Authentication required to execute code",
                "red",
                "Error",
                dash.no_update,
            )

        try:
            # Get dataset from actual data collection
            if workflow_id and data_collection_id:
                from depictio.api.v1.deltatables_utils import load_deltatable_lite

                TOKEN = local_data["access_token"]
                loaded_df = load_deltatable_lite(workflow_id, data_collection_id, TOKEN=TOKEN)
                # Use Polars DataFrame directly - Plotly Express now supports Polars natively
                df = loaded_df
            else:
                return (
                    None,
                    "Please select a workflow and data collection",
                    "orange",
                    "Warning",
                    dash.no_update,
                )

            # Execute code securely
            executor = SimpleCodeExecutor()
            success, result, message = executor.execute_code(code, df)

            if success and result:
                # Extract parameters from executed code for dict_kwargs
                extracted_params = extract_params_from_code(code)
                logger.info(f"Extracted parameters from executed code: {extracted_params}")

                # Evaluate parameters that reference df in the execution context
                evaluated_params = evaluate_params_in_context(extracted_params, df)
                logger.info(f"Evaluated parameters with df context: {evaluated_params}")

                # Store the figure data with metadata for further processing
                figure_data = {
                    "figure": result.to_dict(),
                    "code": code,
                    "workflow_id": workflow_id,
                    "data_collection_id": data_collection_id,
                }
                logger.info(
                    f"Code execution successful, storing figure data with keys: {list(figure_data.keys())}"
                )
                return (
                    figure_data,
                    "Code executed successfully!",
                    "green",
                    "Success",
                    evaluated_params,
                )
            else:
                return (None, message, "red", "Error", dash.no_update)

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Code execution error: {error_msg}")
            return (None, error_msg, "red", "Error", dash.no_update)

    # Update figure when code is executed successfully
    @app.callback(
        Output({"type": "figure-body", "index": MATCH}, "children", allow_duplicate=True),
        Input({"type": "code-generated-figure", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_figure_from_code(figure_data):
        """Update the figure display when code execution succeeds"""
        logger.info(f"update_figure_from_code called with figure_data: {bool(figure_data)}")

        # Extract code from figure_data if available
        code = None
        if isinstance(figure_data, dict) and "code" in figure_data:
            code = figure_data.get("code")

        code_params = extract_params_from_code(code) if code else {}
        logger.info(f"Extracted code parameters: {code_params}")

        if figure_data:
            # Handle both old format (direct figure) and new format (with metadata)
            if isinstance(figure_data, dict) and "figure" in figure_data:
                return dcc.Graph(figure=figure_data["figure"], style={"height": "100%"})
            else:
                # Backward compatibility - direct figure data
                return dcc.Graph(figure=figure_data, style={"height": "100%"})
        return dash.no_update

    # Create/update stored-metadata-component for save functionality when code executes
    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data", allow_duplicate=True),
        [Input({"type": "code-generated-figure", "index": MATCH}, "data")],
        [State({"type": "stored-metadata-component", "index": MATCH}, "data")],
        prevent_initial_call=True,
    )
    def create_metadata_for_code_figure(figure_data, existing_metadata):
        """
        Create/update stored-metadata-component for code-generated figures
        to ensure code-generated figures are saved properly to the dashboard.
        """
        logger.debug(
            f"create_metadata_for_code_figure triggered with figure_data: {bool(figure_data)}"
        )

        if not figure_data:
            logger.warning("No figure_data provided, skipping metadata creation")
            return dash.no_update

        from datetime import datetime

        # Get component index from callback context - use triggered instead of outputs_list
        ctx = dash.callback_context
        component_index = "unknown"

        # Get the index from the triggered input ID instead
        if ctx.triggered:
            try:
                import json

                triggered_prop_id = ctx.triggered[0]["prop_id"]
                # Extract the ID part before the dot (e.g., '{"index":"abc","type":"code-generated-figure"}.data')
                id_part = triggered_prop_id.split(".")[0]
                id_dict = json.loads(id_part)
                if isinstance(id_dict, dict) and "index" in id_dict:
                    component_index = id_dict["index"]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                # Fallback: try to extract from outputs if available
                try:
                    if hasattr(ctx, "outputs") and ctx.outputs:
                        output_id = ctx.outputs.get("id", {})
                        if isinstance(output_id, dict):
                            component_index = output_id.get("index", "unknown")
                except Exception:
                    component_index = "unknown"

        # Extract data from the figure_data structure
        if isinstance(figure_data, dict) and "code" in figure_data:
            code = figure_data.get("code")
            workflow_id = figure_data.get("workflow_id")
            data_collection_id = figure_data.get("data_collection_id")
        else:
            # Backward compatibility - no metadata available
            code = None
            workflow_id = None
            data_collection_id = None

        # Extract the code parameters for metadata
        code_params = extract_params_from_code(code) if code else {}

        # Extract the visualization type from the code
        visu_type = extract_visualization_type_from_code(code) if code else "scatter"

        # Start with existing metadata if available, otherwise create new
        if existing_metadata and isinstance(existing_metadata, dict):
            metadata = existing_metadata.copy()
            logger.debug(f"Merging with existing metadata for {component_index}")
        else:
            metadata = {}
            logger.debug(f"Creating new metadata for {component_index}")

        # Create/update metadata for code mode figure
        # For stepper mode, store with clean index (without -tmp) so Done button logic works
        # The Done button expects metadata.index + "-tmp" == triggered_index
        clean_index = (
            component_index.replace("-tmp", "")
            if component_index.endswith("-tmp")
            else component_index
        )

        # Update metadata fields, preserving existing values when new ones are not available
        metadata.update(
            {
                "index": clean_index,
                "component_type": "figure",
                "last_updated": datetime.now().isoformat(),
            }
        )

        # Ensure parent_index is always present (required by draggable.py)
        if "parent_index" not in metadata:
            metadata["parent_index"] = None

        # Only update these fields if we have new data from code mode
        if code:
            metadata.update(
                {
                    "dict_kwargs": code_params,
                    "visu_type": visu_type,
                    "mode": "code",
                    "code_content": code,
                }
            )

        # Only update workflow/dc IDs if we have them (preserve existing if not)
        if workflow_id is not None:
            metadata["wf_id"] = workflow_id
        if data_collection_id is not None:
            metadata["dc_id"] = data_collection_id

        logger.info(
            f"Updated stored metadata for component {clean_index}: wf_id={metadata.get('wf_id')}, dc_id={metadata.get('dc_id')}, has_dict_kwargs={bool(metadata.get('dict_kwargs'))}"
        )
        logger.debug(f"Full metadata: {metadata}")
        return metadata

    #     if isinstance(figure_data, dict) and "code" in figure_data:
    #         code = figure_data.get("code")
    #         workflow_id = figure_data.get("workflow_id")
    #         data_collection_id = figure_data.get("data_collection_id")
    #     else:
    #         # Backward compatibility - no metadata available
    #         code = None
    #         workflow_id = None
    #         data_collection_id = None

    #     # Extract the code parameters for metadata
    #     code_params = extract_params_from_code(code) if code else {}

    #     # Extract the visualization type from the code
    #     visu_type = extract_visualization_type_from_code(code) if code else "scatter"

    #     # Create metadata for code mode figure
    #     # For stepper mode, store with clean index (without -tmp) so Done button logic works
    #     # The Done button expects metadata.index + "-tmp" == triggered_index
    #     clean_index = (
    #         component_index.replace("-tmp", "")
    #         if component_index.endswith("-tmp")
    #         else component_index
    #     )
    #     metadata = {
    #         "index": clean_index,
    #         "component_type": "figure",
    #         "dict_kwargs": code_params,
    #         "visu_type": visu_type,  # Use extracted visualization type from code
    #         "wf_id": workflow_id,
    #         "dc_id": data_collection_id,
    #         "last_updated": datetime.now().isoformat(),
    #         "mode": "code",  # Track that this was generated via code mode
    #         "code_content": code,  # Store the code for potential future use
    #     }

    #     logger.debug(
    #         f"Created metadata for code mode {visu_type} figure with clean index {clean_index} (from {component_index}): {metadata}"
    #     )
    #     return metadata

    # #     if isinstance(figure_data, dict) and "code" in figure_data:
    # #         code = figure_data.get("code")
    # #         workflow_id = figure_data.get("workflow_id")
    # #         data_collection_id = figure_data.get("data_collection_id")
    # #     else:
    # #         # Backward compatibility - no metadata available
    # #         code = None
    # #         workflow_id = None
    # #         data_collection_id = None

    # #     # Extract the code parameters for metadata
    # #     code_params = extract_params_from_code(code) if code else {}

    # #     # Update the stored metadata with code mode information
    # #     updated_metadata = stored_metadata.copy()

    # #     # Ensure the index matches the component's current state (with -tmp if in stepper mode)
    # #     # This is crucial for the "Done" button to find the metadata
    # #     component_index = stored_metadata.get("index", "")

    # #     # Check if this is a stepper component by looking at callback context
    # #     ctx = dash.callback_context
    # #     if ctx.outputs_list and len(ctx.outputs_list) > 0:
    # #         output_id = ctx.outputs_list[0].get("id", {})
    # #         if isinstance(output_id, dict):
    # #             output_index = output_id.get("index", "")

    # #             # Handle stepper mode index synchronization
    # #             if output_index.endswith("-tmp"):
    # #                 # This is a stepper component, ensure metadata index matches
    # #                 if not component_index.endswith("-tmp"):
    # #                     updated_metadata["index"] = output_index
    # #                     logger.info(
    # #                         f"Updated metadata index to match stepper component: {output_index} (was: {component_index})"
    # #                     )
    # #                 else:
    # #                     logger.info(
    # #                         f"Stepper component metadata index already correct: {component_index}"
    # #                     )
    # #             elif component_index.endswith("-tmp") and not output_index.endswith("-tmp"):
    # #                 # Component is transitioning out of stepper mode, update to clean index
    # #                 updated_metadata["index"] = output_index
    # #                 logger.info(
    # #                     f"Updated metadata index to clean component: {output_index} (was: {component_index})"
    # #                 )

    # #     updated_metadata.update(
    # #         {
    # #             "dict_kwargs": code_params,
    # #             "visu_type": "code",  # Special type for code-generated figures
    # #             "wf_id": workflow_id,
    # #             "dc_id": data_collection_id,
    # #             "last_updated": datetime.now().isoformat(),
    # #             "mode": "code",  # Track that this was generated via code mode
    # #             "code_content": code,  # Store the code for potential future use
    # #         }
    # #     )

    # #     logger.info(
    # #         f"Code mode figure metadata updated for component {stored_metadata.get('index')}"
    # #     )
    # #     logger.info(f"Updated metadata: {updated_metadata}")
    # #     return updated_metadata

    # Populate DataFrame columns information in code mode
    @app.callback(
        Output({"type": "columns-info", "index": MATCH}, "children"),
        Input({"type": "figure-mode-toggle", "index": MATCH}, "value"),
        State("local-store", "data"),
        State("url", "pathname"),
        # State({"type": "columns-info", "index": MATCH}, "id"),
        State({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        prevent_initial_call=False,
    )
    def update_columns_info(mode, local_data, pathname, workflow_id, data_collection_id):
        """Update the available columns information for code mode"""
        logger.info("\n")
        logger.info(f"update_columns_info called: mode={mode}")

        # Only update when in code mode
        if mode != "code":
            logger.info("Not in code mode, skipping update")
            return dash.no_update

        if not local_data:
            logger.info("No local data available")
            return "Authentication required."

        try:
            # Get component index from the callback context
            dashboard_id = pathname.split("/")[-1]

            logger.info(f"Getting component data for index: dashboard: {dashboard_id}")

            if not workflow_id or not data_collection_id:
                return "Please ensure workflow and data collection are selected in the component."

            from depictio.api.v1.deltatables_utils import load_deltatable_lite

            TOKEN = local_data["access_token"]
            loaded_df = load_deltatable_lite(workflow_id, data_collection_id, TOKEN=TOKEN)

            # Use Polars DataFrame directly to get column info - no pandas conversion needed
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
            logger.error(f"Error loading column information: {e}")
            return f"Error loading column information: {str(e)}"

    # Combined callback for Select All button and features info display
    @app.callback(
        [
            Output({"type": "param-features", "index": MATCH}, "value"),
            Output({"type": "features-info-features", "index": MATCH}, "children"),
        ],
        [
            Input({"type": "select-all-features", "index": MATCH}, "n_clicks"),
            Input({"type": "param-features", "index": MATCH}, "value"),
        ],
        [
            State({"type": "param-features", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_features_selection(n_clicks, selected_features, options_data):
        """Handle Select All button and update features info display."""
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        triggered_prop = ctx.triggered[0]["prop_id"]

        # Check if Select All button was clicked
        if "select-all-features" in triggered_prop and n_clicks:
            # Extract all available values from the options data
            if options_data:
                all_values = [opt["value"] for opt in options_data]
                info_text = f"Selected all {len(all_values)} numeric columns"
                return all_values, info_text
            else:
                return selected_features or [], "No numeric columns available"

        # Update info display when selection changes
        elif "param-features" in triggered_prop:
            if not selected_features:
                return (
                    selected_features,
                    "No features selected (will use all numeric columns automatically)",
                )

            total_numeric = len(options_data) if options_data else 0
            selected_count = len(selected_features)

            info_text = f"Selected {selected_count} of {total_numeric} numeric columns: {', '.join(selected_features[:3])}{'...' if len(selected_features) > 3 else ''}"
            return selected_features, info_text

        raise dash.exceptions.PreventUpdate

    # Callback to update ace editor theme based on app theme
    @app.callback(
        Output({"type": "code-editor", "index": MATCH}, "theme"),
        [Input("theme-store", "data")],
        prevent_initial_call=False,  # Allow initial call to set theme on page load
    )
    def update_ace_editor_theme(theme_data):
        """Update ace editor theme based on the app theme."""
        logger.info(
            f"Ace editor theme update triggered with theme_data: {theme_data} (type: {type(theme_data)})"
        )

        # Handle different theme_data formats
        if isinstance(theme_data, dict):
            is_dark = theme_data.get("colorScheme") == "dark"
        elif isinstance(theme_data, str):
            is_dark = theme_data == "dark"
        else:
            is_dark = False

        if is_dark:
            logger.info("Setting ace editor to monokai (dark) theme")
            return "monokai"  # Dark theme for ace editor
        else:
            logger.info("Setting ace editor to github (light) theme")
            return "github"  # Light theme for ace editor

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

    @app.callback(
        Output({"type": "graph", "index": MATCH}, "figure"),
        Input("theme-store", "data"),
        prevent_initial_call=True,  # Only update on theme changes, not initial load
    )
    def update_theme_figure(theme_data):
        """Update figure theme based on current theme using Patch."""

        # Handle different theme_data formats robustly
        if isinstance(theme_data, dict):
            is_dark = theme_data.get("colorScheme") == "dark"
        elif isinstance(theme_data, str):
            is_dark = theme_data == "dark"
        else:
            is_dark = False

        # Use mantine templates for consistency
        template_name = "mantine_dark" if is_dark else "mantine_light"

        # Debug: Check what's actually in the mantine templates
        import plotly.io as pio

        template = pio.templates[template_name]

        patch = Patch()
        # Pass template object, not string name
        patch.layout.template = template

        # Remove explicit colors - let the template handle everything

        logger.info(
            f"🎨 SERVER PATCH: Applied template {template_name} via Patch with explicit colors (theme_data: {theme_data})"
        )
        return patch


def design_figure(id, component_data=None):
    # Get all available visualizations
    all_vizs = get_available_visualizations()

    # Group visualizations by their group
    from .models import VisualizationGroup

    grouped_vizs = {}
    for viz in all_vizs:
        group = viz.group
        if group not in grouped_vizs:
            grouped_vizs[group] = []
        grouped_vizs[group].append(viz)

    # Define group order and labels (Geographic and Specialized hidden from dropdown display)
    group_info = {
        VisualizationGroup.CORE: {"label": "Core", "order": 1},
        VisualizationGroup.ADVANCED: {"label": "Advanced", "order": 2},
        VisualizationGroup.THREE_D: {"label": "3D", "order": 3},
        VisualizationGroup.CLUSTERING: {"label": "Clustering", "order": 4},
        # Note: Geographic and Specialized groups exist but are hidden from dropdown
        # VisualizationGroup.GEOGRAPHIC: {"label": "Geographic", "order": 5},
        # VisualizationGroup.SPECIALIZED: {"label": "Specialized", "order": 6},
    }

    # Create flat options ordered by group (DMC Select doesn't support true groups)
    viz_options = []
    for group in sorted(grouped_vizs.keys(), key=lambda g: group_info.get(g, {}).get("order", 99)):
        if group in grouped_vizs and grouped_vizs[group] and group in group_info:
            # Add group header as disabled option
            group_label = group_info.get(group, {"label": group.title()})["label"]
            viz_options.append(
                {
                    "label": f"─── {group_label} ───",
                    "value": f"__group__{group}",
                    "disabled": True,
                }
            )

            # Add visualizations in this group
            for viz in sorted(grouped_vizs[group], key=lambda x: x.label):
                viz_options.append({"label": f"  {viz.label}", "value": viz.name.lower()})

            # Add separator except for last group
            if (
                group
                != list(
                    sorted(
                        grouped_vizs.keys(), key=lambda g: group_info.get(g, {}).get("order", 99)
                    )
                )[-1]
            ):
                viz_options.append(
                    {"label": "", "value": f"__separator__{group}", "disabled": True}
                )

    # Default to scatter if no component data
    default_value = "scatter"
    if component_data and "visu_type" in component_data:
        # Use the visualization name (lowercase) as value
        default_value = component_data["visu_type"].lower()

    # Set initial mode based on component_data mode field
    initial_mode = "ui"  # Default to UI mode
    if component_data and component_data.get("mode") == "code":
        initial_mode = "code"
        logger.info(
            f"Setting initial mode to code for component {id['index']} based on stored metadata"
        )
    else:
        logger.info(f"Setting initial mode to UI for component {id['index']}")

    # Create layout optimized for fullscreen modal
    figure_row = [
        # Mode toggle (central and prominent)
        dmc.Center(
            [
                dmc.SegmentedControl(
                    id={"type": "figure-mode-toggle", "index": id["index"]},
                    data=[
                        {
                            "value": "ui",
                            "label": dmc.Center(
                                [
                                    DashIconify(icon="tabler:eye", width=16),
                                    html.Span("UI Mode"),
                                ],
                                style={
                                    "gap": 10,
                                    "width": "250px",
                                    # "display": "flex",
                                    # "justifyContent": "center",
                                    # "alignItems": "center"
                                },
                            ),
                        },
                        {
                            "value": "code",
                            "label": dmc.Center(
                                [
                                    DashIconify(icon="tabler:code", width=16),
                                    html.Span("Code Mode (Beta)"),
                                ],
                                style={
                                    "gap": 10,
                                    "width": "250px",
                                    # "display": "flex",
                                    # "justifyContent": "center",
                                    # "alignItems": "center"
                                },
                            ),
                        },
                    ],
                    value=initial_mode,  # Use initial_mode based on component_data
                    size="lg",
                    style={"marginBottom": "15px"},
                    # style={"marginBottom": "15px", "width": "520px"},
                )
            ]
        ),
        # UI mode header - now empty since controls moved to right column
        html.Div(
            id={"type": "ui-mode-header", "index": id["index"]},
            style={"display": "block", "height": "0px"},  # Keep visible for callback but no height
        ),
        # Main content area - side-by-side layout
        html.Div(
            id={"type": "main-content-area", "index": id["index"]},
            children=[
                # Left side - Shared figure container (used by both UI and Code modes)
                html.Div(
                    build_figure_frame(index=id["index"]),
                    id={
                        "type": "component-container",
                        "index": id["index"],
                    },
                    style={
                        "width": "60%",
                        "height": "100%",  # FIXED: Allow full height instead of fixed 60vh
                        "display": "inline-block",
                        "verticalAlign": "top",
                        "marginRight": "2%",
                        "minHeight": "400px",  # Provide reasonable minimum
                        "border": "1px solid #eee",
                    },
                ),
                # Right side - Mode-specific controls
                html.Div(
                    children=[
                        # UI Mode Layout (default) - simple controls
                        html.Div(
                            [
                                html.Div(
                                    [
                                        # Visualization and Edit button row (2/3 + 1/3 layout)
                                        html.Div(
                                            [
                                                # Visualization section (full width)
                                                html.Div(
                                                    [
                                                        dmc.Group(
                                                            [
                                                                DashIconify(
                                                                    icon="mdi:chart-line",
                                                                    width=18,
                                                                    height=18,
                                                                ),
                                                                dmc.Text(
                                                                    "Visualization Type:",
                                                                    fw="bold",
                                                                    size="md",
                                                                    style={"fontSize": "16px"},
                                                                ),
                                                            ],
                                                            gap="xs",
                                                            align="center",
                                                            style={"marginBottom": "10px"},
                                                        ),
                                                        dmc.Select(
                                                            data=viz_options,
                                                            value=default_value,
                                                            id={
                                                                "type": "segmented-control-visu-graph",
                                                                "index": id["index"],
                                                            },
                                                            placeholder="Choose visualization type...",
                                                            clearable=False,
                                                            searchable=True,
                                                            size="md",
                                                            style={
                                                                "width": "100%",
                                                                "fontSize": "14px",
                                                            },
                                                            renderOption={
                                                                "function": "renderVisualizationOption"
                                                            },
                                                        ),
                                                    ],
                                                    style={
                                                        "width": "100%",
                                                    },
                                                ),
                                            ],
                                            style={"marginBottom": "20px"},
                                        ),
                                        # Hidden edit button for callback compatibility
                                        html.Div(
                                            dmc.Button(
                                                "Edit",
                                                id={
                                                    "type": "edit-button",
                                                    "index": id["index"],
                                                },
                                                n_clicks=1,  # Start clicked to show parameters
                                                style={"display": "none"},
                                            )
                                        ),
                                        # Edit panel (always open)
                                        dmc.Collapse(
                                            id={
                                                "type": "collapse",
                                                "index": id["index"],
                                            },
                                            opened=True,
                                            style={
                                                "overflowY": "auto",
                                                # "maxHeight": "35vh",
                                            },
                                        ),
                                    ],
                                    style={"padding": "20px"},
                                ),
                            ],
                            id={"type": "ui-mode-content", "index": id["index"]},
                            style={"display": "block"},
                        ),
                        # Code Mode Layout (hidden by default) - code interface
                        html.Div(
                            [
                                html.Div(
                                    id={"type": "code-mode-interface", "index": id["index"]},
                                    style={
                                        "width": "100%",
                                        "height": "100%",  # FIXED: Allow full height instead of fixed 60vh
                                        "minHeight": "400px",  # Provide reasonable minimum
                                    },
                                ),
                            ],
                            id={"type": "code-mode-content", "index": id["index"]},
                            style={"display": "none"},
                        ),
                    ],
                    style={
                        "width": "38%",
                        "display": "inline-block",
                        "verticalAlign": "top",
                        "height": "100%",  # FIXED: Allow full height instead of fixed 60vh
                        "minHeight": "400px",  # Provide reasonable minimum
                    },
                ),
            ],
            style={"width": "100%", "marginTop": "10px"},
        ),
        # Store components
        dcc.Store(
            id={"type": "dict_kwargs", "index": id["index"]},
            data={},  # Initialize empty to trigger default generation
            storage_type="memory",
        ),
        # CRITICAL: Create stored-metadata-component store for code mode compatibility
        # This ensures the store exists before any callbacks try to update it
        dcc.Store(
            id={"type": "stored-metadata-component", "index": id["index"]},
            data={
                "index": id["index"],
                "component_type": "figure",
                "dict_kwargs": component_data.get("dict_kwargs", {}) if component_data else {},
                "visu_type": component_data.get("visu_type", "scatter")
                if component_data
                else "scatter",
                "wf_id": component_data.get("wf_id") if component_data else None,
                "dc_id": component_data.get("dc_id") if component_data else None,
                "mode": component_data.get("mode", "ui") if component_data else "ui",
                "code_content": component_data.get("code_content", "") if component_data else "",
                "last_updated": component_data.get("last_updated") if component_data else None,
                "parent_index": component_data.get("parent_index") if component_data else None,
            },
            storage_type="memory",
        ),
        # Mode management stores
        dcc.Store(
            id={"type": "figure-mode-store", "index": id["index"]},
            data=initial_mode,  # Use detected initial mode (ui or code)
            storage_type="memory",
        ),
        dcc.Store(
            id={"type": "code-content-store", "index": id["index"]},
            data=component_data.get("code_content", "")
            if component_data
            else "",  # Initialize with existing code
            storage_type="memory",
        ),
        dcc.Store(
            id={"type": "code-generated-figure", "index": id["index"]},
            data=None,  # Store for code-generated figure data
            storage_type="memory",
        ),
        # Hidden stores for scroll position preservation
        dcc.Store(
            id={"type": "scroll-store", "index": id["index"]},
            data={},
            storage_type="memory",
        ),
        dcc.Store(
            id={"type": "scroll-restore", "index": id["index"]},
            data={},
            storage_type="memory",
        ),
    ]
    return figure_row


def create_stepper_figure_button(n, disabled=None):
    """
    Create the stepper figure button

    Args:
        n (_type_): _description_
        disabled (bool, optional): Override enabled state. If None, uses metadata.

    Returns:
        _type_: _description_
    """
    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("figure")

    button = dmc.Button(
        "Figure",
        id={
            "type": "btn-option",
            "index": n,
            "value": "Figure",
        },
        n_clicks=0,
        style=UNSELECTED_STYLE,
        size="xl",
        color=get_dmc_button_color("figure"),
        leftSection=DashIconify(icon="mdi:graph-box", color="white"),
        disabled=disabled,
    )
    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "Figure",
        },
        data=0,
        storage_type="memory",
    )
    return button, store
