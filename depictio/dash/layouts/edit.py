import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
from dash import html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.header import _is_different_from_default
from depictio.dash.layouts.stepper import create_stepper_output_edit
from depictio.dash.utils import get_component_data


def register_reset_button_callbacks(app):
    """Register callbacks to update reset button colors based on filter activity."""

    # # Use clientside callback for better performance and direct DOM manipulation
    # app.clientside_callback(
    #     """
    #     function(interactive_values, pathname) {
    #         console.log('🔄 Clientside callback triggered with:', interactive_values);

    #         if (!interactive_values) {
    #             console.log('No interactive values, skipping update');
    #             return '';
    #         }

    #         // Find all reset buttons
    #         const resetButtons = document.querySelectorAll('[id*="reset-selection-graph-button"]');
    #         console.log('Found reset buttons:', resetButtons.length);

    #         resetButtons.forEach(button => {
    #             try {
    #                 // Extract component index from button ID
    #                 const buttonId = button.id;
    #                 console.log('Processing button:', buttonId);

    #                 // Parse the component index from the ID
    #                 let componentIndex = null;
    #                 const match = buttonId.match(/index":"([^"]+)"/);
    #                 if (match) {
    #                     componentIndex = match[1];
    #                     console.log('Found component index:', componentIndex);

    #                     // Check if this component has active filters
    #                     const hasFilter = checkComponentFilter(interactive_values, componentIndex);
    #                     console.log('Component', componentIndex, 'has filter:', hasFilter);

    #                     if (hasFilter) {
    #                         // Make button orange and always visible
    #                         button.setAttribute('data-color', 'orange');
    #                         button.classList.add('reset-button-filtered');
    #                         button.style.opacity = '1';
    #                         button.style.pointerEvents = 'auto';
    #                         button.style.display = 'flex';
    #                         button.style.visibility = 'visible';
    #                         console.log('Set button to orange/visible for component', componentIndex);
    #                     } else {
    #                         // Make button gray and follow normal hover behavior
    #                         button.setAttribute('data-color', 'gray');
    #                         button.classList.remove('reset-button-filtered');
    #                         console.log('Set button to gray/normal for component', componentIndex);
    #                     }
    #                 }
    #             } catch (error) {
    #                 console.error('Error processing button:', error);
    #             }
    #         });

    #         return 'updated';

    #         function checkComponentFilter(interactive_values, componentIndex) {
    #             try {
    #                 let interactive_data = [];

    #                 if (interactive_values.interactive_components_values) {
    #                     interactive_data = interactive_values.interactive_components_values;
    #                 } else if (typeof interactive_values === 'object') {
    #                     for (const [key, value] of Object.entries(interactive_values)) {
    #                         if (value && typeof value === 'object' && value.value !== undefined) {
    #                             interactive_data.push(value);
    #                         }
    #                     }
    #                 }

    #                 console.log('Checking', interactive_data.length, 'components for index', componentIndex);

    #                 for (const component of interactive_data) {
    #                     if (component.metadata && component.metadata.index === componentIndex) {
    #                         const currentValue = component.value;
    #                         const defaultState = component.metadata.default_state;

    #                         console.log('Found component', componentIndex, 'value:', currentValue, 'default:', defaultState);

    #                         if (!defaultState || currentValue === null || currentValue === undefined) {
    #                             return false;
    #                         }

    #                         // Check if different from default
    #                         if (defaultState.default_range) {
    #                             return JSON.stringify(currentValue) !== JSON.stringify(defaultState.default_range);
    #                         } else if (defaultState.default_value !== undefined) {
    #                             // Special handling for MultiSelect: both empty array [] and null should be considered equivalent
    #                             const isCurrentEmpty = currentValue === null || currentValue === undefined || (Array.isArray(currentValue) && currentValue.length === 0);
    #                             const isDefaultEmpty = defaultState.default_value === null || defaultState.default_value === undefined || (Array.isArray(defaultState.default_value) && defaultState.default_value.length === 0);

    #                             if (isCurrentEmpty && isDefaultEmpty) {
    #                                 return false; // Both are empty, so no difference
    #                             }

    #                             return currentValue !== defaultState.default_value;
    #                         }

    #                         return false;
    #                     }
    #                 }

    #                 console.log('Component', componentIndex, 'not found in interactive data');
    #                 return false;
    #             } catch (error) {
    #                 console.error('Error checking component filter:', error);
    #                 return false;
    #             }
    #         }
    #     }
    #     """,
    #     # Output("button-style-tracker", "data"),
    #     [
    #         Input("interactive-values-store", "data", allow_optional=True),
    #         Input("url", "pathname"),  # Also trigger when page changes
    #     ],
    #     prevent_initial_call=True,
    # )


def _check_component_filter_activity(interactive_values, component_index):
    """Check if a specific component has active filters."""
    logger.info(f"🔍 _check_component_filter_activity for component {component_index}")

    if not interactive_values:
        logger.info("📭 No interactive_values provided")
        return False

    # Handle different possible structures in interactive_values
    interactive_values_data = []

    if "interactive_components_values" in interactive_values:
        interactive_values_data = interactive_values["interactive_components_values"]
        logger.info(f"📦 Found interactive_components_values: {len(interactive_values_data)} items")
    elif isinstance(interactive_values, dict):
        # Look for any values that might be interactive components
        for key, value in interactive_values.items():
            if isinstance(value, dict) and "value" in value:
                interactive_values_data.append(value)
        logger.info(f"📦 Extracted from dict structure: {len(interactive_values_data)} items")

    if not interactive_values_data:
        logger.info("📭 No interactive component data found")
        return False

    logger.info(
        f"🔍 Searching for component {component_index} among {len(interactive_values_data)} components"
    )

    # Find the specific component by index
    for i, component_data in enumerate(interactive_values_data):
        if isinstance(component_data, dict):
            component_metadata = component_data.get("metadata", {})
            component_id = component_metadata.get("index")

            logger.info(f"  Component {i}: ID={component_id}, looking for {component_index}")

            # Check if this is the component we're looking for
            if str(component_id) == str(component_index):
                component_value = component_data.get("value")
                default_state = component_metadata.get("default_state", {})

                logger.info(f"  ✅ Found target component {component_index}")
                logger.info(f"    Current value: {component_value}")
                logger.info(f"    Default state: {default_state}")

                if component_value is None or not default_state:
                    logger.info("  ❌ No value or default_state, returning False")
                    return False

                # Use the same logic as the header reset button
                is_different = _is_different_from_default(component_value, default_state)
                logger.info(f"  🎯 Is different from default: {is_different}")
                return is_different

    logger.info(f"❌ Component {component_index} not found in interactive values")
    return False


def _create_component_buttons(
    component_type,
    component_data,
    btn_index,
    create_drag_handle,
    create_remove_button,
    create_edit_button,
    create_duplicate_button,
    create_reset_button,
    create_alignment_button=None,
):
    """Create action buttons based on component type and configuration.

    Returns:
        dmc.ActionIconGroup: Configured button group for the component
    """
    # Define button configurations for different component types
    button_configs = {
        "figure": {
            "orientation": "vertical",
            "buttons": ["drag", "remove", "edit", "duplicate"],
            "scatter_buttons": [
                "drag",
                "remove",
                "edit",
                "duplicate",
                "reset",
            ],  # Special case for scatter plots
        },
        "interactive": {
            "orientation": "horizontal",
            "buttons": [
                "drag",
                "remove",
                "edit",
                "duplicate",
                "reset",
            ],  # Interactive components get reset button
        },
        "table": {"orientation": "horizontal", "buttons": ["drag", "remove", "duplicate"]},
        "jbrowse": {"orientation": "horizontal", "buttons": ["drag", "remove", "duplicate"]},
        "text": {
            "orientation": "horizontal",
            "buttons": ["drag", "remove", "duplicate", "alignment"],
        },  # Text components get alignment button (no edit button)
        "default": {
            "orientation": "horizontal",
            "buttons": ["drag", "remove", "edit", "duplicate"],
        },
    }

    # Get configuration for this component type
    config = button_configs.get(component_type, button_configs["default"])

    # Special handling for scatter plot figures
    if component_type == "figure":
        visu_type = component_data.get("visu_type", None) if component_data else None
        if visu_type and visu_type.lower() == "scatter":
            button_list = config["scatter_buttons"]
        else:
            button_list = config["buttons"]
    else:
        button_list = config["buttons"]

    # Map button names to functions
    button_functions = {
        "drag": create_drag_handle,
        "remove": create_remove_button,
        "edit": create_edit_button,
        "duplicate": create_duplicate_button,
        "reset": create_reset_button,
    }

    # Add alignment button only if the function is provided
    if create_alignment_button is not None:
        button_functions["alignment"] = create_alignment_button

    # Create the actual button components
    button_components = [button_functions[btn]() for btn in button_list]

    # Log configuration for debugging
    if component_type:
        logger.debug(
            f"Creating {config['orientation']} buttons for {component_type}: {button_list}"
        )

    return dmc.ActionIconGroup(button_components, orientation=config["orientation"])


def edit_component(index, parent_id, active=0, component_data=None, TOKEN=None):
    logger.info("=== EDIT COMPONENT ===")
    logger.info("Function parameters:")
    logger.info(f"  index: {index}")
    logger.info(f"  parent_id: {parent_id}")
    logger.info(f"  active: {active}")
    logger.info(f"  component_data type: {type(component_data)}")
    logger.info(f"  component_data: {component_data}")
    logger.info(f"  TOKEN: {'***' if TOKEN else None}")

    current_draggable_children = create_stepper_output_edit(
        index, parent_id, active, component_data, TOKEN
    )

    return current_draggable_children


def enable_box_edit_mode(
    box,
    switch_state=True,
    dashboard_id=None,
    fresh=False,
    component_data=dict(),
    TOKEN=None,
):
    # Extract component ID from native Dash component or JSON
    def extract_component_id(component):
        """Extract component ID from native Dash component or JSON representation."""

        # PRIORITY: Try to get ID from component_data first (metadata)
        if component_data and isinstance(component_data, dict):
            if "index" in component_data:
                logger.debug(f"Using component ID from metadata: {component_data['index']}")
                return component_data["index"]
        # Handle native Dash components
        if hasattr(component, "id") and component.id:
            if isinstance(component.id, dict) and "index" in component.id:
                return component.id["index"]
            elif isinstance(component.id, str):
                return component.id

        # Handle JSON representation (legacy)
        if isinstance(component, dict) and "props" in component:
            try:
                return component["props"]["id"]["index"]
            except (KeyError, TypeError):
                pass

        # Fallback: generate a unique index
        import uuid

        # DEBUG: Log the component structure to understand why ID extraction failed
        logger.warning(f"Component ID extraction failed. Component structure: {type(component)}")
        if isinstance(component, dict):
            logger.warning(f"Component keys: {list(component.keys())}")
            if "props" in component:
                logger.warning(f"Props keys: {list(component.get('props', {}).keys())}")
                if "id" in component.get("props", {}):
                    logger.warning(f"ID structure: {component['props']['id']}")

        fallback_id = str(uuid.uuid4())
        logger.warning(f"Component missing id, generated fallback: {fallback_id}")
        return fallback_id

    btn_index = extract_component_id(box)

    logger.debug(f"ENABLE BOX EDIT MODE - index: {btn_index}")

    component_type = None
    if not component_data:
        if dashboard_id and TOKEN:
            component_data = get_component_data(
                input_id=btn_index, dashboard_id=dashboard_id, TOKEN=TOKEN
            )
            if component_data:
                component_type = component_data.get("component_type", None)
    else:
        component_type = component_data.get("component_type", None)

    def create_drag_handle():
        return dmc.ActionIcon(
            id={"type": "drag-handle", "index": f"{btn_index}"},
            # Use style override instead of color parameter to avoid type errors
            variant="filled",
            size="sm",
            children=DashIconify(
                icon="mdi:dots-grid", width=14, color="black"
            ),  # More subtle grid icon
            className="react-grid-dragHandle",  # This tells DashGridLayout it's a drag handle
            style={"cursor": "grab", "backgroundColor": "#f2f2f2"},
        )

    def create_remove_button():
        return dmc.ActionIcon(
            id={"type": "remove-box-button", "index": f"{btn_index}"},
            color="red",
            variant="filled",
            size="sm",
            children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        )

    def create_edit_button():
        return dmc.ActionIcon(
            id={"type": "edit-box-button", "index": f"{btn_index}"},
            color="blue",
            variant="filled",
            size="sm",
            children=DashIconify(icon="mdi:pen", width=16, color="white"),
        )

    def create_duplicate_button():
        return dmc.ActionIcon(
            id={"type": "duplicate-box-button", "index": f"{btn_index}"},
            color="gray",
            variant="filled",
            size="sm",
            children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
        )

    # category_button = dmc.Select(
    #     # label="Category",
    #     placeholder="Select category type",
    #     value="Default category",
    #     data=[
    #         {"label": "Default category", "value": "Default category"},
    #         {"label": "Custom", "value": "Custom"},
    #     ],
    #     id={"type": "category-box-button", "index": f"{btn_index}"},
    #     variant="filled",
    #     # size="sm",
    #     # leftSection=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    # )

    def create_reset_button():
        return dmc.ActionIcon(
            id={"type": "reset-selection-graph-button", "index": f"{btn_index}"},
            color="orange",
            variant="filled",
            size="sm",
            children=DashIconify(icon="bx:reset", width=16, color="white"),
        )

    def create_alignment_button():
        from depictio.dash.component_metadata import get_dmc_button_color

        return dmc.Menu(
            [
                dmc.MenuTarget(
                    dmc.ActionIcon(
                        DashIconify(icon="tabler:align-left", width=16),
                        id={"type": "alignment-menu-btn", "index": f"{btn_index}"},
                        color=get_dmc_button_color("text"),
                        variant="filled",
                        size="sm",
                    )
                ),
                dmc.MenuDropdown(
                    [
                        dmc.MenuItem(
                            "Align Left",
                            id={"type": "align-left-btn", "index": f"{btn_index}"},
                            leftSection=DashIconify(icon="tabler:align-left", width=16),
                            n_clicks=0,
                        ),
                        dmc.MenuItem(
                            "Align Center",
                            id={"type": "align-center-btn", "index": f"{btn_index}"},
                            leftSection=DashIconify(icon="tabler:align-center", width=16),
                            n_clicks=0,
                        ),
                        dmc.MenuItem(
                            "Align Right",
                            id={"type": "align-right-btn", "index": f"{btn_index}"},
                            leftSection=DashIconify(icon="tabler:align-right", width=16),
                            n_clicks=0,
                        ),
                    ]
                ),
            ],
            id={"type": "alignment-menu", "index": f"{btn_index}"},
        )

    if switch_state:
        # Create buttons based on component type and configuration
        buttons = _create_component_buttons(
            component_type,
            component_data,
            btn_index,
            create_drag_handle,
            create_remove_button,
            create_edit_button,
            create_duplicate_button,
            create_reset_button,
            create_alignment_button,
        )
        # if fresh:
        #     buttons = dmc.Group([remove_button], grow=False, gap="xl", style={"margin-left": "12px"})
        # Handle native Dash component - wrap in list for consistent processing
        if hasattr(box, "children") or hasattr(box, "figure") or hasattr(box, "id"):
            # Native Dash component
            box_components_list = box
        else:
            # JSON representation (legacy)
            box_components_list = box

    else:
        # Non-edit mode: handle both native components and JSON
        if hasattr(box, "children") or hasattr(box, "figure") or hasattr(box, "id"):
            # Native Dash component
            box_components_list = box
        else:
            # JSON representation (legacy)
            box_components_list = [box]

    # Create a DraggableWrapper for dash-dynamic-grid-layout
    # This preserves the UUID and makes the component draggable

    # Generate proper UUID for the draggable component (following prototype pattern)
    box_uuid = f"box-{str(btn_index)}"

    logger.info(f"Creating DraggableWrapper with UUID: {box_uuid}")

    if switch_state:
        # Create content div with embedded buttons (matching prototype pattern)
        # NUCLEAR: Remove intermediate wrapper div that breaks flex chain
        content_children = []

        # Add component content - handle both native components and lists
        if (
            hasattr(box_components_list, "children")
            or hasattr(box_components_list, "figure")
            or hasattr(box_components_list, "id")
        ):
            # Native Dash component
            content_children.append(box_components_list)
        elif isinstance(box_components_list, list):
            # List of components
            content_children.extend(box_components_list)
        else:
            # Single component or JSON
            content_children.append(box_components_list)

        # Add buttons positioned absolutely
        content_children.append(
            html.Div(
                buttons,
                style={
                    "position": "absolute",
                    "top": "4px",
                    "right": "8px",
                    "zIndex": 1000,
                    "alignItems": "center",
                    "height": "auto",
                    "background": "transparent",
                    "borderRadius": "6px",
                    "padding": "4px",
                },
            )
        )

        content_div = html.Div(
            content_children,
            id=f"content-{box_uuid}",
            className="dashboard-component-hover responsive-content",
            style={
                "overflow": "visible",
                "width": "100%",
                "height": "100%",
                "boxSizing": "border-box",
                "padding": "5px",
                "border": "1px solid transparent",
                "borderRadius": "8px",
                "position": "relative",
                "minHeight": "100px",
                "transition": "all 0.3s ease",
                # Critical flexbox properties for vertical growing
                "display": "flex",
                "flexDirection": "column",
            },
        )
    else:
        # Non-edit mode: simple content div without buttons (except reset for scatter plots)
        # Handle both native components and JSON
        content_children = []
        if (
            hasattr(box_components_list, "children")
            or hasattr(box_components_list, "figure")
            or hasattr(box_components_list, "id")
        ):
            # Native Dash component
            content_children.append(box_components_list)
        elif isinstance(box_components_list, list):
            # List of components
            content_children.extend(box_components_list)
        else:
            # Single component or JSON
            content_children.append(box_components_list)

        # Check if this component should have a reset button in non-edit mode
        show_reset_in_non_edit = False
        if component_data:
            # Show reset for scatter plot figures
            if component_type == "figure":
                visu_type = component_data.get("visu_type", None)
                if visu_type and visu_type.lower() == "scatter":
                    show_reset_in_non_edit = True
            # Show reset for all interactive components
            elif component_type == "interactive":
                show_reset_in_non_edit = True

        # Add reset button for scatter plots and interactive components even in non-edit mode
        if show_reset_in_non_edit:
            reset_button = dmc.ActionIconGroup([create_reset_button()], orientation="horizontal")
            content_children.append(
                html.Div(
                    reset_button,
                    className="reset-button-container-non-edit",  # Add specific class for CSS targeting
                    style={
                        "position": "absolute",
                        "top": "4px",
                        "right": "8px",
                        "zIndex": 1000,
                        "alignItems": "center",
                        "height": "auto",
                        "borderRadius": "6px",
                        "padding": "4px",
                    },
                )
            )

        content_div = html.Div(
            content_children,
            id=f"content-{box_uuid}",
            className="dashboard-component-hover responsive-content",
            style={
                "overflow": "visible",
                "width": "100%",
                "height": "100%",
                "boxSizing": "border-box",
                "padding": "5px",
                "border": "1px solid transparent",
                "borderRadius": "8px",
                "position": "relative",
                "minHeight": "100px",
                "transition": "all 0.3s ease",
                # Critical flexbox properties for vertical growing
                "display": "flex",
                "flexDirection": "column",
            },
        )

    # Create DraggableWrapper with the UUID as ID (like in the prototype)
    draggable_wrapper = dgl.DraggableWrapper(
        id=box_uuid,  # Use UUID as ID for layout tracking
        children=[content_div],
        handleText="Drag",  # Handle text for dragging
    )

    # Return with responsive-wrapper class to match working prototype pattern
    return html.Div(
        draggable_wrapper,
        id=box_uuid,  # CRITICAL: Add the ID to the outer wrapper so it can be found for duplication
        className="responsive-wrapper",  # Critical: This class makes it work!
        style={
            "position": "relative",
            "width": "100%",
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "flex": "1",  # Critical: Allow vertical growing
        },
    )
