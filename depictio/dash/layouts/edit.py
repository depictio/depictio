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
        leftIcon=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    )

    if switch_state:
        box_components_list = [remove_button, box]

    else:
        box_components_list = [box]

    new_draggable_child = html.Div(
        box_components_list,
        id=f"box-{str(btn_index)}",
    )

    return new_draggable_child
