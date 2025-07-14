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
            else:
                required_params = ["x", "y"]  # Default for most plots

        return required_params

    except Exception:
        # Fallback if visualization definition not found
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

        # Determine visualization type from segmented control
        if visu_type:  # visu_type is the label from segmented control
            # Convert label to name using visualization definitions
            available_vizs = get_available_visualizations()
            visu_name = "scatter"  # Default fallback
            for viz in available_vizs:
                if viz.label == visu_type:
                    visu_name = viz.name
                    break
            visu_type = visu_name
        elif component_data and "visu_type" in component_data:
            visu_type = component_data["visu_type"]
        else:
            visu_type = "scatter"  # Default fallback

        # Ensure visualization type is lowercase for consistency
        visu_type = visu_type.lower()

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
            component_builder = ComponentBuilder(component_index, columns)
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
                        parameters[param_name] = value
                    elif isinstance(value, bool):  # Include boolean False
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
        ],
        prevent_initial_call=True,
    )
    def update_figure(*args):
        dict_kwargs = args[0]
        visu_type_label = args[1]  # This is the label from segmented control
        theme_data = args[2]  # Theme is 3rd in the State list
        workflow_id = args[3]
        data_collection_id = args[4]
        component_id_dict = args[5]
        parent_index = args[6]
        local_data = args[7]
        pathname = args[8]

        logger.info("=== UPDATE FIGURE CALLBACK ===")
        logger.info(f"Received dict_kwargs: {dict_kwargs}")
        logger.info(f"Visualization type label: {visu_type_label}")
        logger.info(f"Workflow ID: {workflow_id}")
        logger.info(f"Data Collection ID: {data_collection_id}")
        logger.info(f"Component ID dict: {component_id_dict}")
        logger.info(f"Parent index: {parent_index}")

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

        # Convert visualization label to name using new robust system
        visu_type = "scatter"  # Default fallback
        if visu_type_label:
            available_vizs = get_available_visualizations()
            for viz in available_vizs:
                if viz.label == visu_type_label:
                    visu_type = viz.name
                    break

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
            workflow_id = workflow_id or component_data.get("wf_id", "")
            data_collection_id = data_collection_id or component_data.get("dc_id", "")
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

            # Convert visualization label to name
            visu_type = "scatter"  # Default fallback
            if visu_type_label:
                available_vizs = get_available_visualizations()
                for viz in available_vizs:
                    if viz.label == visu_type_label:
                        visu_type = viz.name
                        break

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

            # Convert visualization label to name (default to scatter)
            visu_type = "scatter"
            if visu_type_label:
                available_vizs = get_available_visualizations()
                for viz in available_vizs:
                    if viz.label == visu_type_label:
                        visu_type = viz.name
                        break

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
    ):
        logger.info("=== GENERATE DEFAULT FIGURE CALLBACK ===")
        logger.info(f"Visualization type label: {visu_type_label}")
        logger.info(f"Component index: {component_index}")
        logger.info(f"Current parameters: {dict_kwargs}")
        logger.info(f"dict_kwargs.keys: {len(list(dict_kwargs.keys()))}")
        logger.info(f"Workflow ID: {workflow_id}")
        logger.info(f"Data Collection ID: {data_collection_id}")
        logger.info(f"parent_index: {parent_index}")
        logger.info(f"pathname: {pathname}")

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

            # Convert visualization label to name
            visu_type = "scatter"  # Default fallback
            if visu_type_label:
                available_vizs = get_available_visualizations()
                for viz in available_vizs:
                    if viz.label == visu_type_label:
                        visu_type = viz.name
                        break

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


def design_figure(id, component_data=None):
    # Get limited set of visualizations for user request: Scatter, Bar, Box, Line only
    all_vizs = get_available_visualizations()

    # Filter to only the requested visualization types
    allowed_types = {"scatter", "bar", "box", "line"}
    filtered_vizs = [viz for viz in all_vizs if viz.name.lower() in allowed_types]

    viz_options = [
        {"label": viz.label, "value": viz.label}
        for viz in sorted(filtered_vizs, key=lambda x: x.label)
    ]

    # Default to scatter if no component data
    default_value = "Scatter"
    if component_data and "visu_type" in component_data:
        # Find the label for the visualization type from filtered list
        for viz in filtered_vizs:
            if viz.name.lower() == component_data["visu_type"].lower():
                default_value = viz.label
                break

    # Create layout optimized for fullscreen modal
    figure_row = [
        # Compact header with controls
        dmc.Group(
            [
                # Styled visualization selector
                dmc.Group(
                    [
                        DashIconify(icon="mdi:chart-line", width=18, color="#228be6"),
                        dmc.Text(
                            "Visualization",
                            fw="bold",
                            size="sm",
                            c="dark",
                            style={"marginRight": "8px"},
                        ),
                        dmc.Select(
                            data=viz_options,
                            value=default_value,
                            id={
                                "type": "segmented-control-visu-graph",
                                "index": id["index"],
                            },
                            placeholder="Choose type...",
                            clearable=False,
                            searchable=False,
                            size="sm",
                            style={"width": "160px"},
                            comboboxProps={"withinPortal": False},
                        ),
                    ],
                    gap="xs",
                    align="center",
                ),
                # Edit button - close to visualization selector
                dmc.Button(
                    "Edit Figure",
                    id={
                        "type": "edit-button",
                        "index": id["index"],
                    },
                    n_clicks=0,
                    size="sm",
                    leftSection=DashIconify(icon="mdi:cog", width=16),
                    variant="outline",
                    color="blue",
                    style={"fontWeight": 500},
                ),
            ],
            justify="flex-start",
            align="center",
            gap="lg",
            style={"marginBottom": "10px", "width": "100%", "padding": "0 5px"},
        ),
        # Main content area - split layout for fullscreen
        html.Div(
            [
                # Figure display - left side, smaller for fullscreen
                html.Div(
                    build_figure_frame(index=id["index"]),
                    id={
                        "type": "component-container",
                        "index": id["index"],
                    },
                    style={
                        "width": "60%",  # Smaller width for fullscreen
                        "height": "60vh",  # Fixed height for better space usage
                        "display": "inline-block",
                        "verticalAlign": "top",
                        "marginRight": "2%",
                    },
                ),
                # Collapsible edit panel - right side
                html.Div(
                    dbc.Collapse(
                        id={
                            "type": "collapse",
                            "index": id["index"],
                        },
                        is_open=False,
                        style={
                            "height": "60vh",
                            "overflowY": "auto",
                            "scrollBehavior": "smooth",  # Smooth scrolling
                        },
                    ),
                    style={
                        "width": "38%",  # Remaining width
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
