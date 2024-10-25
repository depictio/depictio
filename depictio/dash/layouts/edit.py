import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html

from depictio.api.v1.configs.logging import logger
from depictio.dash.layouts.stepper import create_stepper_output_edit
from depictio.dash.utils import get_component_data


def edit_component(index, active=0, component_data=None, TOKEN=None):
    logger.info(f"Editing component {index}")

    current_draggable_children = create_stepper_output_edit(index, active, component_data, TOKEN)

    return current_draggable_children


def enable_box_edit_mode(box, switch_state=True, dashboard_id=None, TOKEN=None):
    # logger.info(box)
    # logger.info(box["props"])
    btn_index = box["props"]["id"]["index"]

    component_type = None
    if dashboard_id and TOKEN:
        component_data = get_component_data(input_id=btn_index, dashboard_id=dashboard_id, TOKEN=TOKEN)
        if component_data:
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

    remove_button = dmc.Button(
        "Remove",
        id={"type": "remove-box-button", "index": f"{btn_index}"},
        color="red",
        leftIcon=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    )

    edit_button = dmc.Button(
        "Edit",
        id={"type": "edit-box-button", "index": f"{btn_index}"},
        color="blue",
        leftIcon=DashIconify(icon="mdi:pen", width=16, color="white"),
    )
    category_button = dmc.Select(
        # label="Category",
        placeholder="Select category type",
        value="Default category",
        data=[
            {"label": "Default category", "value": "Default category"},
            {"label": "Custom", "value": "Custom"},
        ],
        id={"type": "category-box-button", "index": f"{btn_index}"},
        variant="filled",
        # size="sm",
        # leftSection=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    )

    if switch_state:
        buttons = dmc.Group([remove_button, category_button], grow=False, spacing="xl", style={"margin-left": "12px"})
        if component_type:
            if component_type != "table":
                buttons = dmc.Group([remove_button, edit_button, category_button], grow=False, spacing="xl", style={"margin-left": "12px"})
        box_components_list = dmc.Stack([buttons, box], spacing="md")

    else:
        box_components_list = [box]

    new_draggable_child = html.Div(
        box_components_list,
        id=f"box-{str(btn_index)}",
    )

    return new_draggable_child
