import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html


def enable_box_edit_mode(box, switch_state=True):
    # logger.info(box)
    # logger.info(box["props"])
    btn_index = box["props"]["id"]["index"]
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
        leftSection=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    )
    edit_button = dmc.Button(
        "Edit",
        id={"type": "edit-box-button", "index": f"{btn_index}"},
        color="blue",
        leftSection=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    )
    category_button = dmc.Select(
        label="Category",
        placeholder="Select category type",
        value="Default",
        
        data=[
            {"label": "Default", "value": "Default"},
            {"label": "Custom", "value": "Custom"},
        ],
        id={"type": "category-box-button", "index": f"{btn_index}"},
        variant="filled",
        # size="sm",
        # leftSection=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    )

    if switch_state:
        box_components_list = [dmc.Group(children=[remove_button, edit_button, category_button]), box]

    else:
        box_components_list = [box]

    new_draggable_child = html.Div(
        box_components_list,
        id=f"box-{str(btn_index)}",
        # style={ "background-color": "red"}
    )

    return new_draggable_child
