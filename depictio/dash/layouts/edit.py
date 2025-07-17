import dash_bootstrap_components as dbc
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
    btn_index = box["props"]["id"]["index"]

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

    edit_button = dbc.Button(
        "Edit",
        id={
            "type": "edit-box-button",
            "index": f"{btn_index}",
        },
        color="secondary",
        style={"margin-left": "12px"},
        # size="lg",
    )
    from dash_iconify import DashIconify

    remove_button = dmc.ActionIcon(
        # remove_button = dmc.Button(
        # "Remove",
        id={"type": "remove-box-button", "index": f"{btn_index}"},
        color="red",
        variant="filled",
        children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        # leftIcon=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    )

    edit_button = dmc.ActionIcon(
        # edit_button = dmc.Button(
        # "Edit",
        id={"type": "edit-box-button", "index": f"{btn_index}"},
        color="blue",
        variant="filled",
        children=DashIconify(icon="mdi:pen", width=16, color="white"),
        # leftIcon=DashIconify(icon="mdi:pen", width=16, color="white"),
    )

    duplicate_button = dmc.ActionIcon(
        # duplicate_button = dmc.Button(
        # "Duplicate",
        id={"type": "duplicate-box-button", "index": f"{btn_index}"},
        color="gray",
        variant="filled",
        children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
        # leftIcon=DashIconify(icon="mdi:content-copy", width=16, color="white"),
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

    reset_selection_button = dmc.ActionIcon(
        id={"type": "reset-selection-graph-button", "index": f"{btn_index}"},
        color="orange",
        variant="filled",
        children=DashIconify(icon="bx:reset", width=16, color="white"),
    )

    if switch_state:
        # buttons = dmc.Group([remove_button, category_button], grow=False, gap="xl", style={"margin-left": "12px"})
        # if component_type:
        #     if component_type != "table":
        buttons = dmc.Group(
            [remove_button, edit_button, duplicate_button],
            grow=False,
            gap="xs",
            style={"margin-left": "12px"},
        )
        # logger.info(f"ENABLE BOX EDIT MODE - component_type: {component_type}")

        if component_type:
            visu_type = component_data.get("visu_type", None)
            if (
                component_type == "figure"
                and visu_type is not None
                and visu_type.lower() == "scatter"
            ):
                buttons = dmc.Group(
                    [
                        remove_button,
                        edit_button,
                        duplicate_button,
                        reset_selection_button,
                    ],
                    grow=False,
                    gap="xs",
                    style={"margin-left": "12px"},
                )

            elif component_type in ["table", "jbrowse"]:
                buttons = dmc.Group(
                    [remove_button, duplicate_button],
                    grow=False,
                    gap="xs",
                    style={"margin-left": "12px"},
                )
        else:
            buttons = dmc.Group(
                [remove_button, duplicate_button],
                grow=False,
                gap="xs",
                style={"margin-left": "12px"},
            )
        # if fresh:
        #     buttons = dmc.Group([remove_button], grow=False, gap="xl", style={"margin-left": "12px"})
        box_components_list = dmc.Stack([buttons, box], gap="md")

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
        style={
            "overflowY": "hidden",  # Hide overflow to prevent scrollbar
            "width": "100%",  # Ensure it takes full width of the parent
            "height": "100%",  # Ensure it takes full height of the parent
            "display": "flex",  # Use flexbox for better layout control
            "flexDirection": "column",  # Arrange children vertically
            "boxSizing": "border-box",  # Include padding in the element's total width and height
            "padding": "10px",  # Add some padding
            "border": "1px solid #ddd",  # Add a subtle border
            "borderRadius": "5px",  # Add rounded corners
            "background": "#ffffff",  # White background
        },
    )

    # Create DraggableWrapper with the UUID as ID (like in the prototype)
    draggable_wrapper = dgl.DraggableWrapper(
        id=box_uuid,  # Use UUID as ID for layout tracking
        children=[content_div],
        handleText="Move Component",  # Handle text for dragging
    )

    return draggable_wrapper
