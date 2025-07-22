import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
from dash import html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.stepper import create_stepper_output_edit
from depictio.dash.utils import get_component_data


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
    # logger.info(box)
    # logger.info(box["props"])

    # Handle cases where component doesn't have an id in props
    try:
        btn_index = box["props"]["id"]["index"]
    except (KeyError, TypeError):
        # Fallback: generate a unique index if component doesn't have one
        import uuid

        btn_index = str(uuid.uuid4())
        logger.warning(f"Component missing id in props, generated fallback: {btn_index}")

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
            color="gray",
            variant="subtle",
            size="sm",
            children=DashIconify(
                icon="mdi:dots-grid", width=14, color="#888"
            ),  # More subtle grid icon
            className="react-grid-dragHandle",  # This tells DashGridLayout it's a drag handle
            style={"cursor": "grab"},
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
            size="lg",
            children=DashIconify(icon="bx:reset", width=16, color="white"),
        )

    if switch_state:
        # Default buttons for most components
        buttons = dmc.ActionIconGroup(
            [
                create_drag_handle(),
                create_remove_button(),
                create_edit_button(),
                create_duplicate_button(),
            ],
            orientation="horizontal",
        )

        # logger.info(f"ENABLE BOX EDIT MODE - component_type: {component_type}")

        if component_type:
            visu_type = component_data.get("visu_type", None)
            if (
                component_type == "figure"
                and visu_type is not None
                and visu_type.lower() == "scatter"
            ):
                # Add reset button for scatter plots
                buttons = dmc.ActionIconGroup(
                    [
                        create_drag_handle(),
                        create_remove_button(),
                        create_edit_button(),
                        create_duplicate_button(),
                        create_reset_button(),
                    ],
                    orientation="horizontal",
                )

            elif component_type in ["table", "jbrowse"]:
                # Limited buttons for table and jbrowse components
                buttons = dmc.ActionIconGroup(
                    [
                        create_drag_handle(),
                        create_remove_button(),
                        create_duplicate_button(),
                    ],
                    orientation="horizontal",
                )
        else:
            # Fallback for unknown component types
            buttons = dmc.ActionIconGroup(
                [
                    create_drag_handle(),
                    create_remove_button(),
                    create_duplicate_button(),
                ],
                orientation="horizontal",
            )
        # if fresh:
        #     buttons = dmc.Group([remove_button], grow=False, gap="xl", style={"margin-left": "12px"})
        # Remove buttons from content - will be added separately to DraggableWrapper
        box_components_list = box

    else:
        box_components_list = [box]

    # Create a DraggableWrapper for dash-dynamic-grid-layout
    # This preserves the UUID and makes the component draggable

    # Generate proper UUID for the draggable component (following prototype pattern)
    box_uuid = f"box-{str(btn_index)}"

    logger.info(f"Creating DraggableWrapper with UUID: {box_uuid}")

    # Create the content div with edit buttons (if in edit mode)
    content_div = html.Div(
        box_components_list,
        id=f"content-{box_uuid}",
        className="dashboard-component-hover",  # Add hover effects
        style={
            "overflow": "visible",  # Allow content to be visible and interactive
            "width": "100%",  # Ensure it takes full width of the parent
            "height": "100%",  # Ensure it takes full height of the parent
            "boxSizing": "border-box",  # Include padding in the element's total width and height
            "padding": "40px 10px 10px 10px",  # Extra top padding for overlay controls
            "border": "1px solid var(--app-border-color, #ddd)",  # Theme-aware border
            "borderRadius": "8px",  # Add rounded corners
            "background": "var(--app-surface-color, #ffffff)",  # Theme-aware background
            "position": "relative",  # Enable positioning for absolutely positioned buttons
            "minHeight": "100px",  # Ensure minimum height for content
            "transition": "all 0.3s ease",  # Smooth transitions
        },
    )

    # Create DraggableWrapper with the UUID as ID (like in the prototype)
    draggable_wrapper = dgl.DraggableWrapper(
        id=box_uuid,  # Use UUID as ID for layout tracking
        children=[content_div],
        handleText="Drag",  # Handle text for dragging
    )

    if switch_state:
        # Create a wrapper container with buttons positioned over the drag handle area
        return html.Div(
            [
                draggable_wrapper,
                # Buttons positioned absolutely to align with drag handle
                html.Div(
                    buttons,
                    style={
                        "position": "absolute",
                        "top": "8px",  # Overlay on content
                        "right": "8px",  # Match drag handle positioning
                        "zIndex": 1000,  # Very high z-index
                        # pointerEvents and display removed - CSS handles hover behavior
                        "alignItems": "center",
                        "height": "auto",  # Auto height for better fit
                        "background": "transparent",  # Remove visible background
                        "borderRadius": "6px",  # Rounded corners
                        "padding": "4px",  # Comfortable padding
                    },
                ),
            ],
            style={
                "position": "relative",  # Enable absolute positioning for buttons
                "width": "100%",
                "height": "100%",
            },
        )
    else:
        return draggable_wrapper
