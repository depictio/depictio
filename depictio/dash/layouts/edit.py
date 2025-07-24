import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
from dash import html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.stepper import create_stepper_output_edit
from depictio.dash.utils import get_component_data


def _create_component_buttons(
    component_type,
    component_data,
    btn_index,
    create_drag_handle,
    create_remove_button,
    create_edit_button,
    create_duplicate_button,
    create_reset_button,
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
        "table": {"orientation": "horizontal", "buttons": ["drag", "remove", "duplicate"]},
        "jbrowse": {"orientation": "horizontal", "buttons": ["drag", "remove", "duplicate"]},
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

    from dash_iconify import DashIconify

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
                "border": "1px solid var(--app-border-color, #ddd)",
                "borderRadius": "8px",
                "background": "var(--app-surface-color, #ffffff)",
                "position": "relative",
                "minHeight": "100px",
                "transition": "all 0.3s ease",
                # Critical flexbox properties for vertical growing
                "display": "flex",
                "flexDirection": "column",
            },
        )
    else:
        # Non-edit mode: simple content div without buttons
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
                "border": "1px solid var(--app-border-color, #ddd)",
                "borderRadius": "8px",
                "background": "var(--app-surface-color, #ffffff)",
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
