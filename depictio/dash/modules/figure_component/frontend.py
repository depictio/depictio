# Import necessary libraries
from collections import defaultdict
from typing import Any, Dict, List

import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import httpx
from dash import ALL, MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.figure_component.code_executor import SecureCodeExecutor
from depictio.dash.modules.figure_component.code_mode import (
    convert_ui_params_to_code,
    create_code_mode_interface,
    extract_params_from_code,
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
        ],
        prevent_initial_call=True,  # Prevent initial call to avoid loops
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
    ):
        """Build parameter interface using the new robust system."""

        if not local_data:
            raise dash.exceptions.PreventUpdate

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

    # Universal parameter change listener using pattern matching
    # This callback listens to ANY component with pattern {"type": "param-*", "index": MATCH}
    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data"),
        [
            # This Input will match ANY parameter component dynamically
            Input({"type": ALL, "index": MATCH}, "value"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def extract_parameters_universal(all_values, existing_kwargs):
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

                    # Get value from the triggered values
                    value = input_item.get("value")

                    # Include non-empty values
                    if value is not None and value != "" and value != []:
                        # Convert string values back to their original types
                        converted_value = _convert_parameter_value(param_name, value)
                        parameters[param_name] = converted_value
                    elif isinstance(value, bool):  # Include boolean False
                        parameters[param_name] = value
                    elif value == "":  # Include empty string for optional parameters like parents
                        # For hierarchical charts (sunburst, treemap), empty string is valid for parents
                        parameters[param_name] = value

        logger.info(f"Extracted parameters: {parameters}")
        logger.info(f"Parameter count: {len(parameters)}")

        return parameters if parameters else (existing_kwargs or {})

    @app.callback(
        Output(
            {
                "type": "collapse",
                "index": MATCH,
            },
            "is_open",
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
                "is_open",
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
        ],
        prevent_initial_call=True,
    )
    def disable_done_button(value):
        if value:
            return False
        return True

    # Removed old fragile parameter extraction callback - replaced with robust version above

    @app.callback(
        Output({"type": "figure-body", "index": MATCH}, "children"),
        [
            Input({"type": "dict_kwargs", "index": MATCH}, "data"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
            State("theme-store", "data"),  # Keep as State - theme handled separately
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "segmented-control-visu-graph", "index": MATCH}, "id"),
            State("current-edit-parent-index", "data"),  # Retrieve parent_index
            State("local-store", "data"),
            State("url", "pathname"),
            State({"type": "figure-mode-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def update_figure(*args):
        dict_kwargs = args[0]
        visu_type_label = args[1]  # This is now the visualization name from dropdown
        theme_data = args[2]  # Theme is 3rd in the State list
        workflow_id = args[3]
        data_collection_id = args[4]
        component_id_dict = args[5]
        parent_index = args[6]
        local_data = args[7]
        pathname = args[8]
        current_mode = args[9]  # Current mode from figure-mode-store

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

        # Use component data to override if available
        if component_data:
            if "visu_type" in component_data:
                visu_type = component_data["visu_type"]
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
            needs_defaults = _needs_default_parameters(visu_type, dict_kwargs)

            if needs_defaults:
                logger.info(f"Setting default parameters for {visu_type} visualization")
                default_params = _get_default_parameters(visu_type, columns_specs_reformatted)

                # Update dict_kwargs with defaults (preserve existing params)
                dict_kwargs = {**default_params, **dict_kwargs}

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
            }

            if parent_index:
                figure_kwargs["parent_index"] = parent_index

            logger.info("CALLING build_figure WITH:")
            logger.info(f"  dict_kwargs: {figure_kwargs['dict_kwargs']}")
            logger.info(f"  visu_type: {figure_kwargs['visu_type']}")
            logger.info(f"  wf_id: {figure_kwargs['wf_id']}")
            logger.info(f"  dc_id: {figure_kwargs['dc_id']}")
            logger.info(f"  theme: {figure_kwargs['theme']}")
            logger.info(f"  parent_index: {figure_kwargs.get('parent_index', 'None')}")

            figure_result = build_figure(**figure_kwargs)
            logger.info(f"build_figure RETURNED: {type(figure_result)}")
            return figure_result

        except Exception as e:
            logger.error(f"Failed to build figure: {e}")
            return html.Div(
                [
                    dmc.Alert(
                        f"Error building figure: {str(e)}", title="Figure Build Error", color="red"
                    )
                ]
            )

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

            # If no parameters set, generate defaults
            if not dict_kwargs or dict_kwargs in [{}, {"x": None, "y": None}]:
                columns_json = get_columns_from_data_collection(
                    workflow_id, data_collection_id, TOKEN
                )
                columns_specs_reformatted = defaultdict(list)
                {columns_specs_reformatted[v["type"]].append(k) for k, v in columns_json.items()}

                dict_kwargs = _get_default_parameters(visu_type, columns_specs_reformatted)
                logger.info(f"Generated default parameters for {visu_type}: {dict_kwargs}")

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
            }

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

    # Mode switching callback
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
        prevent_initial_call=True,
    )
    def handle_mode_switch(mode, current_mode, dict_kwargs, visu_type_label, current_code):
        """Handle switching between UI and Code modes"""
        logger.info(f"Mode switch triggered: {current_mode} -> {mode}")

        component_id = dash.callback_context.triggered[0]["prop_id"].split(".")[0]
        component_index = eval(component_id)["index"]
        logger.info(f"Component index for mode switch: {component_index}")
        logger.info(f"Current code content: {current_code}")
        logger.info(f"Current mode: {current_mode}")
        logger.info(f"Current dict_kwargs: {dict_kwargs}")
        logger.info(f"Visualization type label: {visu_type_label}")

        if mode == "ui":
            # Switch to UI mode
            ui_content_style = {"display": "block"}
            code_content_style = {"display": "none"}
            code_interface_children = []
        else:
            # Switch to Code mode
            ui_content_style = {"display": "none"}
            code_content_style = {"display": "block"}

            # Create code mode interface
            code_interface_children = create_code_mode_interface(component_index)

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
        ],
        prevent_initial_call=False,
    )
    def store_generated_code(mode, dict_kwargs, visu_type_label):
        """Store generated code when switching to code mode"""

        logger.info("=== store_generated_code CALLBACK CALLED ===")
        logger.info(f"Mode: {mode}")
        logger.info(f"Dict kwargs: {dict_kwargs}")
        logger.info(f"Visualization type label: {visu_type_label}")

        if mode == "code":
            logger.info("Switching to code mode, generating code from UI parameters")
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
                logger.info("No dict_kwargs, returning template")
                return "# Add your Plotly code here\n# Available: df (DataFrame), px (plotly.express), go (plotly.graph_objects)\n# Example:\n# fig = px.scatter(df, x='your_x_column', y='your_y_column')"

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
        if not ctx.triggered:
            return dash.no_update

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

    # Code execution callback
    @app.callback(
        [
            Output({"type": "code-generated-figure", "index": MATCH}, "data"),
            Output({"type": "code-status", "index": MATCH}, "children"),
            Output({"type": "code-status", "index": MATCH}, "color"),
            Output({"type": "code-status", "index": MATCH}, "title"),
        ],
        [
            Input({"type": "code-execute-btn", "index": MATCH}, "n_clicks"),
        ],
        [
            State({"type": "code-editor", "index": MATCH}, "value"),
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def execute_code(n_clicks, code, workflow_id, data_collection_id, local_data):
        """Execute Python code and generate figure"""
        if not n_clicks or not code:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if not local_data:
            return (
                html.Div("Authentication required"),
                "Authentication required to execute code",
                "red",
                "Error",
            )

        try:
            # Get dataset from actual data collection
            import pandas as pd

            if workflow_id and data_collection_id:
                from depictio.api.v1.deltatables_utils import load_deltatable_lite

                TOKEN = local_data["access_token"]
                loaded_df = load_deltatable_lite(workflow_id, data_collection_id, TOKEN=TOKEN)
                # Convert Polars DataFrame to Pandas DataFrame
                df = (
                    loaded_df.to_pandas()
                    if hasattr(loaded_df, "to_pandas")
                    else pd.DataFrame(loaded_df)
                )
            else:
                return (
                    None,
                    "Please select a workflow and data collection",
                    "orange",
                    "Warning",
                )

            # Execute code securely
            executor = SecureCodeExecutor()
            success, result, message = executor.execute_code(code, df)

            if success and result:
                # Store the figure data for further processing
                figure_data = result.to_dict()
                return (figure_data, "Code executed successfully!", "green", "Success")
            else:
                return (None, message, "red", "Error")

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Code execution error: {error_msg}")
            return (None, error_msg, "red", "Error")

    # Update figure when code is executed successfully
    @app.callback(
        Output({"type": "figure-body", "index": MATCH}, "children", allow_duplicate=True),
        [
            Input({"type": "code-generated-figure", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def update_figure_from_code(figure_data):
        """Update the figure display when code execution succeeds"""
        if figure_data:
            return dcc.Graph(figure=figure_data, style={"height": "100%"})
        return dash.no_update

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

            # Convert to pandas to get column info
            import pandas as pd

            df = (
                loaded_df.to_pandas()
                if hasattr(loaded_df, "to_pandas")
                else pd.DataFrame(loaded_df)
            )

            if df.empty:
                return "No data available in the selected data collection."

            # Create formatted column information
            columns_info = []
            for col in df.columns:
                dtype = str(df[col].dtype)
                # Simplify dtype names
                if dtype.startswith("int"):
                    dtype = "integer"
                elif dtype.startswith("float"):
                    dtype = "float"
                elif dtype == "object":
                    dtype = "text"
                elif dtype.startswith("datetime"):
                    dtype = "datetime"

                columns_info.append(f"• {col} ({dtype})")

            columns_text = (
                f"DataFrame shape: {df.shape[0]} rows × {df.shape[1]} columns\n\n"
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
                                style={"gap": 10},
                            ),
                        },
                        {
                            "value": "code",
                            "label": dmc.Center(
                                [DashIconify(icon="tabler:code", width=16), html.Span("Code Mode")],
                                style={"gap": 10},
                            ),
                        },
                    ],
                    value="ui",  # Default to UI mode
                    size="sm",
                    style={"marginBottom": "15px"},
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
                        "type": "shared-figure-container",
                        "index": id["index"],
                    },
                    style={
                        "width": "60%",
                        "height": "60vh",
                        "display": "inline-block",
                        "verticalAlign": "top",
                        "marginRight": "2%",
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
                                                # Visualization section (2/3 width)
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
                                                        "width": "65%",
                                                        "display": "inline-block",
                                                        "verticalAlign": "top",
                                                        "marginRight": "5%",
                                                    },
                                                ),
                                                # Edit button section (1/3 width)
                                                html.Div(
                                                    [
                                                        dmc.Text(
                                                            " ",  # Empty space to align with label
                                                            fw="bold",
                                                            size="sm",
                                                            style={"marginBottom": "8px"},
                                                        ),
                                                        dmc.Button(
                                                            "Edit",
                                                            id={
                                                                "type": "edit-button",
                                                                "index": id["index"],
                                                            },
                                                            n_clicks=0,
                                                            size="sm",
                                                            leftSection=DashIconify(
                                                                icon="mdi:cog", width=16
                                                            ),
                                                            variant="outline",
                                                            color="blue",
                                                            fullWidth=True,
                                                        ),
                                                    ],
                                                    style={
                                                        "width": "30%",
                                                        "display": "inline-block",
                                                        # "verticalAlign": "top",
                                                        "marginTop": "20px",
                                                    },
                                                ),
                                            ],
                                            style={"marginBottom": "20px"},
                                        ),
                                        # Edit panel
                                        dbc.Collapse(
                                            id={
                                                "type": "collapse",
                                                "index": id["index"],
                                            },
                                            is_open=False,
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
                                        "height": "60vh",
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
                        "height": "60vh",
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
        # Mode management stores
        dcc.Store(
            id={"type": "figure-mode-store", "index": id["index"]},
            data="ui",  # Default to UI mode
            storage_type="memory",
        ),
        dcc.Store(
            id={"type": "code-content-store", "index": id["index"]},
            data="",  # Store for code content
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


def create_stepper_figure_button(n, disabled=False):
    """
    Create the stepper figure button

    Args:
        n (_type_): _description_

    Returns:
        _type_: _description_
    """

    button = dbc.Col(
        dmc.Button(
            "Figure",
            id={
                "type": "btn-option",
                "index": n,
                "value": "Figure",
            },
            n_clicks=0,
            style=UNSELECTED_STYLE,
            size="xl",
            color="grape",
            leftSection=DashIconify(icon="mdi:graph-box", color="white"),
            disabled=disabled,
        )
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
