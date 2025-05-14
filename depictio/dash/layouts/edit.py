import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.stepper import create_stepper_output_edit
from depictio.dash.utils import get_component_data


def edit_component(index, parent_id, active=0, component_data=None, TOKEN=None):
    logger.info(f"Editing component {parent_id}")

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

    logger.info(f"ENABLE BOX EDIT MODE - index: {btn_index}")
    logger.info(f"ENABLE BOX EDIT MODE - component_data: {component_data}")

    component_type = None
    if not component_data:
        if dashboard_id and TOKEN:
            component_data = get_component_data(
                input_id=btn_index, dashboard_id=dashboard_id, TOKEN=TOKEN
            )
            logger.info(f"ENABLE BOX EDIT MODE - component_data: {component_data}")
            if component_data:
                component_type = component_data.get("component_type", None)
    else:
        component_type = component_data.get("component_type", None)
    logger.info(f"ENABLE BOX EDIT MODE - index - component_type: {btn_index} - {component_type}")

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
        # buttons = dmc.Group([remove_button, category_button], grow=False, spacing="xl", style={"margin-left": "12px"})
        # if component_type:
        #     if component_type != "table":
        buttons = dmc.Group(
            [remove_button, edit_button, duplicate_button],
            grow=False,
            spacing="xs",
            style={"margin-left": "12px"},
        )
        logger.info(f"ENABLE BOX EDIT MODE - component_type: {component_type}")

        if component_type:
            if (
                component_type == "figure"
                and component_data.get("visu_type", None).lower() == "scatter"
            ):
                buttons = dmc.Group(
                    [
                        remove_button,
                        edit_button,
                        duplicate_button,
                        reset_selection_button,
                    ],
                    grow=False,
                    spacing="xs",
                    style={"margin-left": "12px"},
                )

            elif component_type in ["table", "jbrowse"]:
                buttons = dmc.Group(
                    [remove_button, duplicate_button],
                    grow=False,
                    spacing="xs",
                    style={"margin-left": "12px"},
                )
        else:
            buttons = dmc.Group(
                [remove_button, duplicate_button],
                grow=False,
                spacing="xs",
                style={"margin-left": "12px"},
            )
        # if fresh:
        #     buttons = dmc.Group([remove_button], grow=False, spacing="xl", style={"margin-left": "12px"})
        box_components_list = dmc.Stack([buttons, box], spacing="md")

    else:
        box_components_list = [box]

    new_draggable_child = html.Div(
        box_components_list,
        id=f"box-{str(btn_index)}",
        style={
            # "overflowY": "auto",
            "overflowY": "hidden",  # Hide overflow to prevent scrollbar
            "width": "100%",  # Ensure it takes full width of the parent
            # "height": "auto",  # Ensure it takes full height of the parent
            "height": "100%",  # Ensure it takes full height of the parent
            "display": "flex",  # Use flexbox for better layout control
            "flexDirection": "column",  # Arrange children vertically
            # "padding": "5px",  # Reduce padding to save space
            "boxSizing": "border-box",  # Include padding in the element's total width and height
        },
    )

    return new_draggable_child
