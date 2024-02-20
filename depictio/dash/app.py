import sys

import yaml

from CLI_client.cli import list_workflows

print(sys.path)

print("\n\n\n")
print("STARTING")
print("\n\n\n")


# Import necessary libraries
import numpy as np
from dash import html, dcc, Input, Output, State, ALL, MATCH, ctx, callback
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import dash_draggable

import inspect
import pandas as pd
import plotly.express as px
import re
from dash_iconify import DashIconify
import ast
import dash_ag_grid as dag
import json

min_step = 0
max_step = 3
active = 0

token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2NGE4NDI4NDJiZjRmYTdkZWFhM2RiZWQiLCJleHAiOjE3ODQ5ODY3ODV9.a5bkSctoCNYXVh035g_wt-bio3iC3uuM9anFKiJOKrmBHDH0tmcL2O9Rc1HIQtAxCH-mc1K4q4aJsAO8oeayuPyA3w7FPIUnLsZGRHB8aBoDCoxEIpmACi0nEH8hF9xd952JuBt6ggchyMyrnxHC65Qc8mHC9PeylWonHvNl5jGZqi-uhbeLpsjuPcsyg76X2aqu_fip67eJ8mdr6yuII6DLykpfbzALpn0k66j79YzOzDuyn4IjBfBPWiqZzl_9oDMLK7ODebu6FTDmQL0ZGto_dxyIJtkf1CdxPaYkgiXVOh00Y6sXJ24jHSqfNP-dqvAQ3G8izuurq6B4SNgtDw"


app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        {
            "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
            "rel": "stylesheet",
        },
    ],
    suppress_callback_exceptions=True,
    title="Depictio",
)
application = app.server


from depictio.dash.modules.card_component.frontend import (
    design_card,
    register_callbacks_card_component,
)
from depictio.dash.modules.interactive_component.frontend import (
    design_interactive,
    register_callbacks_interactive_component,
)
from depictio.dash.modules.figure_component.frontend import (
    design_figure,
    register_callbacks_figure_component,
)
from depictio.dash.modules.jbrowse_component.frontend import (
    design_jbrowse,
    register_callbacks_jbrowse_component,
)

from depictio.dash.layouts.stepper import (
    register_callbacks_stepper,
)

register_callbacks_card_component(app)
register_callbacks_interactive_component(app)
register_callbacks_figure_component(app)
register_callbacks_jbrowse_component(app)
register_callbacks_stepper(app)

from depictio.dash.utils import (
    # create_initial_figure,
    load_data,
    load_deltatable,
    list_workflows_for_dropdown,
    list_data_collections_for_dropdown,
    get_columns_from_data_collection,
    SELECTED_STYLE,
    UNSELECTED_STYLE,
)


from depictio.dash.layouts.stepper import (
    # create_stepper_dropdowns,
    # create_stepper_buttons,
    create_stepper_output,
)


# Data


def return_deltatable(
    workflow_id: str = None, data_collection_id: str = None, raw=False
):
    df = load_deltatable(workflow_id, data_collection_id, raw=raw)
    # print(df)
    return df


df = load_deltatable(workflow_id=None, data_collection_id=None)


# df = pd.read_csv(
#     "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
# )
# print(df)


data = load_data()
# data = dict()
init_layout = data["stored_layout_data"] if data else {}
init_children = data["stored_children_data"] if data else list()
init_nclicks_add_button = data["stored_add_button"] if data else {"count": 0}
init_nclicks_edit_dashboard_mode_button = (
    data["stored_edit_dashboard_mode_button"] if data else [int(0)]
)
if data:
    print("Data loaded from JSON")
    print("stored_add_button")
    print(data["stored_add_button"])
    print("stored_edit_dashboard_mode_button")
    print(data["stored_edit_dashboard_mode_button"])
    print(init_nclicks_add_button)
    print(init_nclicks_edit_dashboard_mode_button)
else:
    print("data")
    print(data)
    print(init_nclicks_add_button)
    print(init_nclicks_edit_dashboard_mode_button)

backend_components = html.Div(
    [
        dcc.Interval(
            id="interval",
            interval=1000,  # Save input value every 1 second
            n_intervals=0,
        ),
        dcc.Interval(
            id="interval_long",
            interval=50000,  # Save input value every 1 second
            n_intervals=0,
        ),
        dcc.Store(id="stored-children", storage_type="memory"),
        # dcc.Store(id="stored-children", storage_type="session"),
        dcc.Store(id="stored-layout", storage_type="memory"),
        # dcc.Store(id="stored-layout", storage_type="session"),
    ]
)

modal_save_button = dbc.Modal(
    [
        dbc.ModalHeader(
            html.H1(
                "Success!",
                className="text-success",
            )
        ),
        dbc.ModalBody(
            html.H5(
                "Your amazing dashboard was successfully saved!",
                className="text-success",
            ),
            style={"background-color": "#F0FFF0"},
        ),
        dbc.ModalFooter(
            dbc.Button(
                "Close",
                id="success-modal-close",
                className="ml-auto",
                color="success",
            )
        ),
    ],
    id="success-modal-dashboard",
    centered=True,
)


header_style = {
    "display": "flex",
    "alignItems": "center",
    "justifyContent": "space-between",
    "padding": "10px 20px",
    "backgroundColor": "#f5f5f5",
    "borderBottom": "1px solid #eaeaea",
    "fontFamily": "'Open Sans', sans-serif",
}

title_style = {"fontWeight": "bold", "fontSize": "24px", "color": "#333"}

button_style = {"margin": "0 10px", "fontWeight": "500"}

header = html.Div(
    [
        html.H1("Depictio", style=title_style),
        html.Div(
            [
                dmc.Button(
                    "Add new component",
                    id="add-button",
                    size="lg",
                    radius="xl",
                    variant="gradient",
                    n_clicks=init_nclicks_add_button["count"],
                    style=button_style,
                ),
                modal_save_button,
                dmc.Button(
                    "Save",
                    id="save-button-dashboard",
                    size="lg",
                    radius="xl",
                    variant="gradient",
                    gradient={"from": "teal", "to": "lime", "deg": 105},
                    n_clicks=0,
                    style={"...": "..."},
                ),  # Add your specific styles here
            ],
            style={"display": "flex", "alignItems": "center"},
        ),
        dbc.Checklist(
            id="edit-dashboard-mode-button",
            style={"fontSize": "22px"},
            options=[{"label": "Edit dashboard", "value": 0}],
            value=init_nclicks_edit_dashboard_mode_button,
            switch=True,
        ),
        dcc.Store(
            id="stored-add-button",
            storage_type="memory",
            # storage_type="session",
            data=init_nclicks_add_button,
        ),
        dcc.Store(
            id="stored-edit-dashboard-mode-button",
            storage_type="memory",
            # storage_type="session",
            data=init_nclicks_edit_dashboard_mode_button,
        ),
    ],
    style=header_style,
)


# header = html.Div(
#     [
#         html.H1("Depictio"),
#         dmc.Button(
#             "Add new component",
#             id="add-button",
#             size="lg",
#             radius="xl",
#             variant="gradient",
#             n_clicks=init_nclicks_add_button["count"],
#         ),
#         modal_save_button,
#         dmc.Button(
#             "Save",
#             id="save-button-dashboard",
#             size="lg",
#             radius="xl",
#             variant="gradient",
#             gradient={"from": "teal", "to": "lime", "deg": 105},
#             n_clicks=0,
#             style={"margin-left": "5px"},
#         ),
#         dbc.Checklist(
#             id="edit-dashboard-mode-button",
#             # color="secondary",
#             style={"margin-left": "20px", "font-size": "22px"},
#             # size="lg",
#             # n_clicks=0,
#             options=[
#                 {"label": "Edit dashboard", "value": 0},
#             ],
#             value=init_nclicks_edit_dashboard_mode_button,
#             switch=True,
#         ),

#     ],
# )


# init_layout = dict()
# init_children = list()


app.layout = dbc.Container(
    [
        html.Div(
            [
                backend_components,
                header,
                dash_draggable.ResponsiveGridLayout(
                    id="draggable",
                    clearSavedLayout=True,
                    layouts=init_layout,
                    children=init_children,
                    isDraggable=True,
                    isResizable=True,
                ),
            ],
        ),
    ],
    fluid=True,
)


@app.callback(
    Output({"type": "modal", "index": MATCH}, "is_open"),
    [Input({"type": "btn-done", "index": MATCH}, "n_clicks")],
    prevent_initial_call=True,
)
def close_modal(n_clicks):
    print("\n\n\n")
    print("close_modal")
    print(n_clicks)
    if n_clicks > 0:
        return False
    return True


@app.callback(
    Output("success-modal-dashboard", "is_open"),
    [
        Input("save-button-dashboard", "n_clicks"),
        Input("success-modal-close", "n_clicks"),
    ],
    [State("success-modal-dashboard", "is_open")],
)
def toggle_success_modal_dashboard(n_save, n_close, is_open):
    ctx = dash.callback_context

    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    # print(trigger_id, n_save, n_close)

    if trigger_id == "save-button-dashboard":
        if n_save is None or n_save == 0:
            raise dash.exceptions.PreventUpdate
        else:
            return True

    elif trigger_id == "success-modal-close":
        if n_close is None or n_close == 0:
            raise dash.exceptions.PreventUpdate
        else:
            return False

    return is_open


@app.callback(
    Output("save-button-dashboard", "n_clicks"),
    Input("save-button-dashboard", "n_clicks"),
    State("stored-layout", "data"),
    State("stored-children", "data"),
    State("stored-edit-dashboard-mode-button", "data"),
    State("stored-add-button", "data"),
    # State("stored-year", "data"),
    prevent_initial_call=True,
)
def save_data_dashboard(
    n_clicks,
    stored_layout_data,
    stored_children_data,
    edit_dashboard_mode_button,
    add_button,
    # stored_year_data,
):
    print("save_data_dashboard")
    print(n_clicks)
    print(edit_dashboard_mode_button)
    print(add_button)
    # print(dash.callback_context.triggered[0]["prop_id"].split(".")[0], n_clicks)
    if n_clicks > 0:
        data = {
            "stored_layout_data": stored_layout_data,
            "stored_children_data": stored_children_data,
            "stored_edit_dashboard_mode_button": edit_dashboard_mode_button,
            "stored_add_button": add_button,
            # "stored_year_data": stored_year_data,
        }
        with open("data.json", "w") as file:
            json.dump(data, file)
        return n_clicks
    return n_clicks


def enable_box_edit_mode(box, switch_state=True):
    print("\n\n\n")
    print("enable_box_edit_mode")
    # print(box["props"]["children"]["props"]["children"][1])
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
    remove_button = dbc.Button(
        "Remove",
        id={"type": "remove-box-button", "index": f"{btn_index}"},
        color="danger",
    )

    # reset_button = dbc.Button(
    #     "Reset",
    #     id={"type": "reset-box-button", "index": f"{btn_index}"},
    #     color="info",
    #     style={"margin-left": "24px"},
    # )

    if switch_state:
        box_components_list = [remove_button, edit_button, box]
        # if box["props"]["children"]["props"]["children"][1]["props"]["id"]["type"] == "interactive-component":
        #     box_components_list.append(reset_button)
    else:
        box_components_list = [box]

    new_draggable_child = html.Div(
        box_components_list,
        id={"type": f"draggable-{btn_index}", "index": btn_index},
    )

    return new_draggable_child


def enable_box_edit_mode_dev(sub_child, switch_state=True):
    print("enable_box_edit_mode_dev")
    print(switch_state)

    # Extract the required substructure based on the depth analysis
    box = sub_child["props"]["children"]
    print(box)

    # Check if the children attribute is a list
    if isinstance(box["props"]["children"], list):
        print("List")

        # Identify if edit and remove buttons are present
        edit_button_exists = any(
            child.get("props", {}).get("id", {}).get("type") == "edit-box-button"
            for child in box["props"]["children"]
        )
        remove_button_exists = any(
            child.get("props", {}).get("id", {}).get("type") == "remove-box-button"
            for child in box["props"]["children"]
        )

        print(switch_state, edit_button_exists, remove_button_exists)

        # If switch_state is true and buttons are not yet added, add them
        if switch_state and not (edit_button_exists and remove_button_exists):
            # Assuming that the ID for box is structured like: {'type': '...', 'index': 1}
            print("\n\n\n")
            print("Adding buttons")
            print(box["props"]["id"])
            btn_index = box["props"]["id"]["index"]

            edit_button = dbc.Button(
                "Edit",
                id={
                    "type": "edit-box-button",
                    "index": f"{btn_index}",
                },
                color="secondary",
                style={"margin-left": "12px"},
            )
            remove_button = dbc.Button(
                "Remove",
                id={"type": "remove-box-button", "index": f"{btn_index}"},
                color="danger",
            )

            # Place buttons at the beginning of the children list
            box["props"]["children"] = [remove_button, edit_button] + box["props"][
                "children"
            ]

        # If switch_state is false and buttons are present, remove them
        elif not switch_state and edit_button_exists and remove_button_exists:
            # print("Removing buttons")
            # Assuming the last element is the main content box
            # print(analyze_structure(box))
            # print(box)
            content_box = box["props"]["children"][-1]
            # print(content_box)
            box["props"]["children"] = [content_box]
            # print(box)

    sub_child["props"]["children"] = box
    # print(sub_child)
    # Return the modified sub_child structure
    return sub_child


def analyze_structure(struct, depth=0):
    """
    Recursively analyze a nested plotly dash structure.

    Args:
    - struct: The nested structure.
    - depth: Current depth in the structure. Default is 0 (top level).
    """

    if isinstance(struct, list):
        # print("  " * depth + f"Depth {depth} Type: List with {len(struct)} elements")
        for idx, child in enumerate(struct):
            print(
                "  " * depth
                + f"Element {idx} ID: {child.get('props', {}).get('id', None)}"
            )
            analyze_structure(child, depth=depth + 1)
        return

    # Base case: if the struct is not a dictionary, we stop the recursion
    if not isinstance(struct, dict):
        return

    # Extracting id if available

    id_value = struct.get("props", {}).get("id", None)
    children = struct.get("props", {}).get("children", None)

    # Printing the id value
    print("  " * depth + f"Depth {depth} ID: {id_value}")

    if isinstance(children, dict):
        print("  " * depth + f"Depth {depth} Type: Dict")
        # Recursive call
        analyze_structure(children, depth=depth + 1)

    elif isinstance(children, list):
        print("  " * depth + f"Depth {depth} Type: List with {len(children)} elements")
        for idx, child in enumerate(children):
            print(
                "  " * depth
                + f"Element {idx} ID: {child.get('props', {}).get('id', None)}"
            )
            # Recursive call
            analyze_structure(child, depth=depth + 1)


def analyze_structure_and_get_deepest_type(
    struct, depth=0, max_depth=0, deepest_type=None
):
    """
    Recursively analyze a nested plotly dash structure and return the type of the deepest element (excluding 'stored-metadata-component').

    Args:
    - struct: The nested structure.
    - depth: Current depth in the structure.
    - max_depth: Maximum depth encountered so far.
    - deepest_type: Type of the deepest element encountered so far.

    Returns:
    - tuple: (Maximum depth of the structure, Type of the deepest element)
    """

    # Update the maximum depth and deepest type if the current depth is greater
    current_type = None
    if isinstance(struct, dict):
        id_value = struct.get("props", {}).get("id", None)
        if (
            isinstance(id_value, dict)
            and id_value.get("type") != "stored-metadata-component"
        ):
            current_type = id_value.get("type")

    if depth > max_depth:
        max_depth = depth
        deepest_type = current_type
    elif depth == max_depth and current_type is not None:
        deepest_type = current_type

    if isinstance(struct, list):
        for child in struct:
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(
                child, depth=depth + 1, max_depth=max_depth, deepest_type=deepest_type
            )
    elif isinstance(struct, dict):
        children = struct.get("props", {}).get("children", None)
        if isinstance(children, (list, dict)):
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(
                children,
                depth=depth + 1,
                max_depth=max_depth,
                deepest_type=deepest_type,
            )

    return max_depth, deepest_type


@app.callback(
    Output({"type": "add-content", "index": MATCH}, "children"),
    Output(
        {"type": "test-container", "index": MATCH}, "children", allow_duplicate=True
    ),
    [
        Input({"type": "btn-done", "index": MATCH}, "n_clicks"),
    ],
    [
        State({"type": "test-container", "index": MATCH}, "children"),
        State({"type": "btn-done", "index": MATCH}, "id"),
        State("stored-edit-dashboard-mode-button", "data"),
        # State({"type": "graph", "index": MATCH}, "figure"),
    ],
    prevent_initial_call=True,
)
def update_button(n_clicks, children, btn_id, switch_state):
    print("\n\n\n")
    print("update_button")
    # print(children)
    # print(analyze_structure(children))
    # print(len(children))

    # Depth 0 ID: {'type': 'graph', 'index': 32}

    # Element 0 ID: {'type': 'stored-metadata-component', 'index': 33}
    # Depth 1 ID: {'type': 'stored-metadata-component', 'index': 33}
    # Element 1 ID: {'type': 'graph', 'index': 33}
    # Depth 1 ID: {'type': 'graph', 'index': 33}

    # Depth 0 ID: {'type': 'interactive', 'index': 33}
    # Depth 0 Type: Dict
    #   Depth 1 ID: {'type': 'card-body', 'index': 33}
    #   Depth 1 Type: List with 3 elements
    #   Element 0 ID: None
    #     Depth 2 ID: None
    #   Element 1 ID: {'type': 'card-value', 'index': 33}
    #     Depth 2 ID: {'type': 'card-value', 'index': 33}
    #   Element 2 ID: {'type': 'stored-metadata-component', 'index': 33}
    #     Depth 2 ID: {'type': 'stored-metadata-component', 'index': 33}

    # Depth 0 ID: None
    # Depth 0 Type: List with 2 elements
    # Element 0 ID: {'type': 'stored-metadata-component', 'index': 33}
    #   Depth 1 ID: {'type': 'stored-metadata-component', 'index': 33}
    # Element 1 ID: {'type': 'graph', 'index': 33}
    #   Depth 1 ID: {'type': 'graph', 'index': 33}

    # print(children["props"]["id"])
    # children = [children[4]]
    # print(len(children))
    # print(children)

    children["props"]["id"]["type"] = "updated-" + children["props"]["id"]["type"]
    # print(children)

    btn_index = btn_id["index"]  # Extracting index from btn_id dict

    # switch_state_bool = True if len(switch_state) > 0 else False

    # new_draggable_child = children
    new_draggable_child = enable_box_edit_mode(children, switch_state)
    # new_draggable_child = enable_box_edit_mode(children, btn_index, switch_state_bool)

    return new_draggable_child, []


# Add a callback to update the isDraggable property
@app.callback(
    [
        Output("draggable", "isDraggable"),
        Output("draggable", "isResizable"),
        Output("add-button", "disabled"),
        Output("save-button-dashboard", "disabled"),
    ],
    [Input("edit-dashboard-mode-button", "value")],
)
def freeze_layout(switch_state):
    # print("\n\n\n")
    # print("freeze_layout")
    # print(switch_state)
    print("\n\n\n")
    # switch based on button's value
    # switch_state = True if len(value) > 0 else False

    if len(switch_state) == 0:
        return False, False, True, True
    else:
        return True, True, False, False


@app.callback(
    Output({"type": "stepper-basic-usage", "index": MATCH}, "active"),
    Output({"type": "next-basic-usage", "index": MATCH}, "disabled"),
    Input({"type": "back-basic-usage", "index": MATCH}, "n_clicks"),
    Input({"type": "next-basic-usage", "index": MATCH}, "n_clicks"),
    Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
    Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
    Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
    State({"type": "stepper-basic-usage", "index": MATCH}, "active"),
    prevent_initial_call=True,
)
def update(back, next_, workflow_selection, data_selection, btn_component, current):
    print("update")
    print(back, next_, current, workflow_selection, data_selection, btn_component)

    if back is None and next_ is None:
        if workflow_selection is not None and data_selection is not None:
            disable_next = False
        else:
            disable_next = True

        # print(current, disable_next)
        return current, disable_next
    else:
        button_id = ctx.triggered_id
        # print(button_id)
        step = current if current is not None else active

        if button_id["type"] == "back-basic-usage":
            step = step - 1 if step > min_step else step
            return step, False

        else:
            step = step + 1 if step < max_step else step
            return step, False


# TODO: optimise to match the modular architecture
@app.callback(
    [
        Output({"type": "btn-option", "index": MATCH, "value": "Figure"}, "style"),
        Output({"type": "btn-option", "index": MATCH, "value": "Card"}, "style"),
        Output({"type": "btn-option", "index": MATCH, "value": "Interactive"}, "style"),
    ],
    [
        Input({"type": "btn-option", "index": MATCH, "value": "Figure"}, "n_clicks"),
        Input({"type": "btn-option", "index": MATCH, "value": "Card"}, "n_clicks"),
        Input(
            {"type": "btn-option", "index": MATCH, "value": "Interactive"}, "n_clicks"
        ),
    ],
    prevent_initial_call=True,
)
def update_button_style(figure_clicks, card_clicks, interactive_clicks):
    ctx_triggered = dash.callback_context.triggered

    # Reset all buttons to unselected style
    figure_style = UNSELECTED_STYLE
    card_style = UNSELECTED_STYLE
    interactive_style = UNSELECTED_STYLE

    # Check which button was clicked and update its style
    if ctx_triggered:
        button_id = ctx_triggered[0]["prop_id"].split(".")[0]
        button_value = eval(button_id)["value"]

        if button_value == "Figure":
            figure_style = SELECTED_STYLE
        elif button_value == "Card":
            card_style = SELECTED_STYLE
        elif button_value == "Interactive":
            interactive_style = SELECTED_STYLE

    return figure_style, card_style, interactive_style


from depictio.dash.modules.figure_component.frontend import create_stepper_figure_button
from depictio.dash.modules.card_component.frontend import create_stepper_card_button
from depictio.dash.modules.interactive_component.frontend import (
    create_stepper_interactive_button,
)
from depictio.dash.modules.jbrowse_component.frontend import (
    create_stepper_jbrowse_button,
)


@app.callback(
    Output({"type": "buttons-list", "index": MATCH}, "children"),
    Output({"type": "store-list", "index": MATCH}, "children"),
    Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
    Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
    Input("add-button", "n_clicks"),
    prevent_initial_call=True,
)
def update_button_list(workflow_selection, data_collection_selection, n):
    print("\n\n\n")
    print("update_button_list")
    print(n)
    print(workflow_selection, data_collection_selection)
    print("\n\n\n")

    workflows = list_workflows(token)

    workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_selection][0][
        "_id"
    ]
    data_collection_id = [
        f
        for e in workflows
        if e["_id"] == workflow_id
        for f in e["data_collections"]
        if f["data_collection_tag"] == data_collection_selection
    ][0]["_id"]

    import httpx

    API_BASE_URL = "http://localhost:8058"

    print(data_collection_selection)

    dc_specs = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
        headers={
            "Authorization": f"Bearer {token}",
        },
    ).json()

    # print(dc_specs)

    data_collection_type = dc_specs["config"]["type"]


    if data_collection_type == "Table":
        (
            figure_stepper_button,
            figure_stepper_button_store,
        ) = create_stepper_figure_button(n, disabled=False)
        card_stepper_button, card_stepper_button_store = create_stepper_card_button(
            n, disabled=False
        )

        (
            interactive_stepper_button,
            interactive_stepper_button_store,
        ) = create_stepper_interactive_button(n, disabled=False)

        (
            jbrowse_stepper_button,
            jbrowse_stepper_button_store,
        ) = create_stepper_jbrowse_button(n, disabled=True)

        standard_components = [
            figure_stepper_button,
            card_stepper_button,
            interactive_stepper_button,
        ]
        special_components = [jbrowse_stepper_button]

    elif data_collection_type == "Genome Browser":
        (
            figure_stepper_button,
            figure_stepper_button_store,
        ) = create_stepper_figure_button(n, disabled=True)
        card_stepper_button, card_stepper_button_store = create_stepper_card_button(
            n, disabled=True
        )

        (
            interactive_stepper_button,
            interactive_stepper_button_store,
        ) = create_stepper_interactive_button(n, disabled=True)

        (
            jbrowse_stepper_button,
            jbrowse_stepper_button_store,
        ) = create_stepper_jbrowse_button(n, disabled=False)

        standard_components = [
            figure_stepper_button,
            card_stepper_button,
            interactive_stepper_button,
        ]
        special_components = [jbrowse_stepper_button]

    buttons_list = html.Div(
        [
            html.H5("Standard components", style={"margin-top": "20px"}),
            html.Hr(),
            dmc.Center(dbc.Row(standard_components)),
            html.Br(),
            html.H5("Special components", style={"margin-top": "20px"}),
            html.Hr(),
            dmc.Center(dbc.Row(special_components)),
        ]
    )

    store_list = [
        figure_stepper_button_store,
        card_stepper_button_store,
        interactive_stepper_button_store,
        jbrowse_stepper_button_store,
    ]
    return buttons_list, store_list


@app.callback(
    Output({"type": "dropdown-output", "index": MATCH}, "children"),
    Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
    Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
    prevent_initial_call=True,
)
def update_step_2(workflow_selection, data_collection_selection):
    workflows = list_workflows(token)

    workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_selection][0][
        "_id"
    ]
    data_collection_id = [
        f
        for e in workflows
        if e["_id"] == workflow_id
        for f in e["data_collections"]
        if f["data_collection_tag"] == data_collection_selection
    ][0]["_id"]

    import httpx

    API_BASE_URL = "http://localhost:8058"

    # print(data_collection_selection)

    dc_specs = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
        headers={
            "Authorization": f"Bearer {token}",
        },
    ).json()

    # print(dc_specs)

    # n = 0

    # store_list = [
    #     figure_stepper_button_store,
    #     card_stepper_button_store,
    #     interactive_stepper_button_store,
    #     jbrowse_stepper_button_store,
    # ]
    # data_collection_type  = dc_specs["config"]["type"]

    # if data_collection_type == "Table":
    #     figure_stepper_button, figure_stepper_button_store = create_stepper_figure_button(n, disabled=False)
    #     card_stepper_button, card_stepper_button_store = create_stepper_card_button(n, disabled=False)

    #     (
    #         interactive_stepper_button,
    #         interactive_stepper_button_store,
    #     ) = create_stepper_interactive_button(n, disabled=False)

    #     (
    #         jbrowse_stepper_button,
    #         jbrowse_stepper_button_store,
    #     ) = create_stepper_jbrowse_button(n, disabled=True)

    #     standard_components = [
    #         figure_stepper_button,
    #         card_stepper_button,
    #         interactive_stepper_button,
    #     ]
    #     special_components = [jbrowse_stepper_button]

    # elif data_collection_type == "Genome Browser":

    #     figure_stepper_button, figure_stepper_button_store = create_stepper_figure_button(n, disabled=True)
    #     card_stepper_button, card_stepper_button_store = create_stepper_card_button(n, disabled=True)

    #     (
    #         interactive_stepper_button,
    #         interactive_stepper_button_store,
    #     ) = create_stepper_interactive_button(n, disabled=True)

    #     (
    #         jbrowse_stepper_button,
    #         jbrowse_stepper_button_store,
    #     ) = create_stepper_jbrowse_button(n, disabled=False)

    #     standard_components = [
    #         figure_stepper_button,
    #         card_stepper_button,
    #         interactive_stepper_button,
    #     ]
    #     special_components = [jbrowse_stepper_button]

    # buttons_list = html.Div([
    #     html.H5("Standard components", style={"margin-top": "20px"}),
    #     html.Hr(),
    #     dmc.Center(dbc.Row(standard_components)),
    #     html.Br(),
    #     html.H5("Special components", style={"margin-top": "20px"}),
    #     html.Hr(),
    #     dmc.Center(dbc.Row(special_components)),
    # ])

    if workflow_selection is not None and data_collection_selection is not None:
        config_title = dmc.Title(
            "Data collection config", order=3, align="left", weight=500
        )
        json_formatted = yaml.dump(dc_specs["config"], indent=2)
        prism = dbc.Col(
            [
                dmc.AccordionPanel(
                    dmc.Prism(
                        f"""{json_formatted}""",
                        language="yaml",
                        colorScheme="light",
                        noCopy=True,
                    )
                ),
            ],
            width=6,
        )

        dc_main_info = dmc.Title("Main info", order=3, align="left", weight=500)

        main_info = html.Table(
            [
                html.Tr(
                    [
                        html.Td(
                            "Type:",
                            style={
                                "font-weight": "bold",
                                "text-align": "left",
                                "width": "20%",
                            },
                        ),
                        html.Td(
                            dc_specs["config"]["type"], style={"text-align": "left"}
                        ),
                    ]
                ),
                html.Tr(
                    [
                        html.Td(
                            "Name:",
                            style={
                                "font-weight": "bold",
                                "text-align": "left",
                                "width": "20%",
                            },
                        ),
                        html.Td(
                            dc_specs["data_collection_tag"],
                            style={"text-align": "left"},
                        ),
                    ]
                ),
                html.Tr(
                    [
                        html.Td(
                            "Description:",
                            style={
                                "font-weight": "bold",
                                "text-align": "left",
                                "width": "20%",
                            },
                        ),
                        html.Td(dc_specs["description"], style={"text-align": "left"}),
                    ]
                ),
                html.Tr(
                    [
                        html.Td(
                            "MongoDB ID:",
                            style={
                                "font-weight": "bold",
                                "text-align": "left",
                                "width": "20%",
                            },
                        ),
                        html.Td(dc_specs["_id"], style={"text-align": "left"}),
                    ]
                ),
            ],
            style={"width": "100%", "table-layout": "fixed"},
        )

        # turn main_info into 4 rows with 2 columns

        layout = [dc_main_info, html.Hr(), main_info, html.Hr()]
        if dc_specs["config"]["type"] == "Table":
            df = return_deltatable(
                workflow_selection, data_collection_selection, raw=True
            )
            cols = get_columns_from_data_collection(
                workflow_selection, data_collection_selection
            )
            # print(cols)
            columnDefs = [
                {"field": c, "headerTooltip": f"Column type: {e['type']}"}
                for c, e in cols.items()
            ]
            # print(columnDefs)

            run_nb = cols["depictio_run_id"]["specs"]["nunique"]
            run_nb_title = dmc.Title(
                f"Run Nb : {run_nb}", order=3, align="left", weight=500
            )

            data_previz_title = dmc.Title(
                "Data previsualization", order=3, align="left", weight=500
            )
            config_title = dmc.Title(
                "Data collection configuration", order=3, align="left", weight=500
            )
            # print(df.head(20).to_dict("records"))
            # cellClicked, cellDoubleClicked, cellRendererData, cellValueChanged, className, columnDefs, columnSize, columnSizeOptions, columnState, csvExportParams, dangerously_allow_code, dashGridOptions, defaultColDef, deleteSelectedRows, deselectAll, detailCellRendererParams, enableEnterpriseModules, exportDataAsCsv, filterModel, getDetailRequest, getDetailResponse, getRowId, getRowStyle, getRowsRequest, getRowsResponse, id, licenseKey, masterDetail, paginationGoTo, paginationInfo, persisted_props, persistence, persistence_type, resetColumnState, rowClass, rowClassRules, rowData, rowModelType, rowStyle, rowTransaction, scrollTo, selectAll, selectedRows, style, suppressDragLeaveHidesColumns, updateColumnState, virtualRowData
            grid = dag.AgGrid(
                id="get-started-example-basic",
                rowData=df.head(2000).to_dict("records"),
                columnDefs=columnDefs,
                dashGridOptions={
                    "tooltipShowDelay": 500,
                    "pagination": True,
                    "paginationAutoPageSize": False,
                    "animateRows": False,
                },
                columnSize="sizeToFit",
                defaultColDef={"resizable": True, "sortable": True, "filter": True},
                # use the parameters above
            )
            # layout += [run_nb_title, html.Hr(), data_previz_title, html.Hr(), grid]
            # print(layout)

            layout += [
                dmc.Accordion(
                    children=[
                        dmc.AccordionItem(
                            [
                                dmc.AccordionControl(data_previz_title),
                                dmc.AccordionPanel(grid),
                            ],
                            value="data_collection_table_previz",
                        ),
                        dmc.AccordionItem(
                            [
                                dmc.AccordionControl(config_title),
                                dmc.AccordionPanel(prism),
                            ],
                            value="data_collection_config",
                        ),
                    ],
                ),
                # buttons_list
            ]

        elif dc_specs["config"]["type"] == "Genome Browser":
            if dc_specs["config"]["jbrowse_template_location"]:
                template_json = json.load(
                    open(dc_specs["config"]["jbrowse_template_location"])
                )
                print(template_json)
                template_title = dmc.Title(
                    "JBrowse template", order=3, align="left", weight=500
                )
                prism_template = dbc.Col(
                    [
                        dmc.Prism(
                            f"""{json.dumps(template_json, indent=2)}""",
                            language="json",
                            colorScheme="light",
                            noCopy=True,
                        ),
                    ],
                    width=6,
                )
                layout += [
                    dmc.Accordion(
                        children=[
                            dmc.AccordionItem(
                                [
                                    dmc.AccordionControl(config_title),
                                    dmc.AccordionPanel(prism),
                                ],
                                value="data_collection_config",
                            ),
                            dmc.AccordionItem(
                                [
                                    dmc.AccordionControl(template_title),
                                    dmc.AccordionPanel(prism_template),
                                ],
                                value="jbrowse_template",
                            ),
                        ],
                    )
                    # ,buttons_list
                ]

    else:
        layout = html.Div("No data to display")

    return layout


# TODO: optimise to match the modular architecture
@app.callback(
    Output({"type": "output-stepper-step-3", "index": MATCH}, "children"),
    Output({"type": "store-btn-option", "index": MATCH, "value": ALL}, "data"),
    Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
    Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
    Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
    Input({"type": "store-btn-option", "index": MATCH, "value": ALL}, "data"),
    State({"type": "btn-option", "index": MATCH, "value": ALL}, "id"),
    # prevent_initial_call=True,
)
def update_step_2(
    workflow_selection,
    data_collection_selection,
    btn_component,
    store_btn_component,
    ids,
):

    components_list = [
        "Figure",
        "Card",
        "Interactive",
        "Genome browser",
        "Graph",
        "Map",
    ]    

    if (
        workflow_selection is not None
        and data_collection_selection is not None
        and btn_component is not None
    ):
        # print("update_step_2")
        # retrieve value in btn_component that is higher than the previous value in store_btn_component at the same index
        btn_index = [
            i
            for i, (x, y) in enumerate(zip(btn_component, store_btn_component))
            if x > y
        ]
        if btn_index:
            component_selected = components_list[btn_index[0]]
            id = ids[btn_index[0]]

            if component_selected not in ["Genome browser", "Graph", "Map"]:
                
                df = return_deltatable(
                    workflow_selection, data_collection_selection, raw=True
                )



            if component_selected == "Figure":
                return design_figure(id, df), btn_component
            elif component_selected == "Card":
                return design_card(id, df), btn_component
            elif component_selected == "Interactive":
                return design_interactive(id, df), btn_component
            elif component_selected == "Genome browser":
                print("Genome browser")
                return_values = design_jbrowse(id)
                print("return_values")
                print(return_values)
                print("btn_component")
                print(btn_component)

                return return_values, btn_component
            # TODO: update this
            elif component_selected == "Graph":
                return dash.no_update, dash.no_update
            elif component_selected == "Map":
                return dash.no_update, dash.no_update
            else: 
                return html.Div("Not implemented yet"), dash.no_update

        else:
            raise dash.exceptions.PreventUpdate

    else:
        raise dash.exceptions.PreventUpdate


@app.callback(
    [
        Output("draggable", "children"),
        Output("draggable", "layouts"),
        Output("stored-layout", "data"),
        Output("stored-children", "data"),
        Output("stored-edit-dashboard-mode-button", "data"),
        Output("stored-add-button", "data"),
    ],
    # [
    #     Input(f"add-plot-button-{plot_type.lower().replace(' ', '-')}", "n_clicks")
    #     for plot_type in AVAILABLE_PLOT_TYPES.keys()
    # ]
    # +
    [
        # Input({"type": "workflow-selection-label", "index": ALL}, "value"),
        # Input({"type": "datacollection-selection-label", "index": ALL}, "value"),
        State(
            {
                "type": "interactive-component",
                # "value": dash.dependencies.ALL,
                "index": dash.dependencies.ALL,
            },
            "id",
        ),
        State(
            {
                "type": "stored-metadata-component",
                # "value": dash.dependencies.ALL,
                "index": dash.dependencies.ALL,
            },
            "data",
        ),
        Input("add-button", "n_clicks"),
        Input("edit-dashboard-mode-button", "value"),
        State("stored-add-button", "data"),
        Input(
            {"type": "remove-box-button", "index": dash.dependencies.ALL}, "n_clicks"
        ),
        Input(
            {
                "type": "interactive-component",
                # "value": dash.dependencies.ALL,
                "index": dash.dependencies.ALL,
            },
            "value",
        ),
        # Input("time-input", "value"),
        Input("stored-layout", "data"),
        Input("stored-children", "data"),
        Input("draggable", "layouts"),
    ],
    [
        State("draggable", "children"),
        State("draggable", "layouts"),
        State("stored-layout", "data"),
        State("stored-children", "data"),
        State("stored-edit-dashboard-mode-button", "data"),
    ],
    prevent_initial_call=True,
)
def update_draggable_children(
    # n_clicks, selected_year, current_draggable_children, current_layouts, stored_figures
    *args,
):
    
    print("\n\n\n")
    print("-------------------------")
    print("update_draggable_children")


    # workflow_label = args[-17]
    # data_collection_label = args[-16]
    interactive_component_ids = args[-15]
    stored_metadata = args[-14]
    add_button_nclicks = args[-13]
    switch_state = args[-12]
    stored_add_button = args[-11]
    remove_box_button_values = args[-10]
    interactive_component_values = args[-9]
    stored_layout_data = args[-8]
    stored_children_data = args[-7]
    new_layouts = args[-6]
    current_draggable_children = args[-5]
    current_layouts = args[-4]
    stored_layout = args[-3]
    stored_figures = args[-2]
    stored_edit_dashboard = args[-1]


    ctx = dash.callback_context
    ctx_triggered = ctx.triggered

    print("CTX triggered: ")
    print(ctx_triggered)

    triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
    print(triggered_input)

    switch_state_index = -1 if switch_state is True else -1

    stored_metadata_interactive = [
        e for e in stored_metadata if e["component_type"] == "interactive_component"
    ]
    # print(stored_metadata_interactive)
    interactive_components_dict = {
        id["index"]: {"value": value, "metadata": metadata}
        for (id, value, metadata) in zip(
            interactive_component_ids,
            interactive_component_values,
            stored_metadata_interactive,
        )
    }
    # print(interactive_components_dict)

    check_value = False
    if "interactive-component" in triggered_input:
        # print(triggered_input)
        triggered_input_eval = ast.literal_eval(triggered_input)
        # print(triggered_input_eval)
        triggered_input_eval_index = int(triggered_input_eval["index"])
        # print(triggered_input_eval_index)

        value = interactive_components_dict[triggered_input_eval_index]["value"]
        # print(value)
        # print(interactive_components_dict[triggered_input_eval_index])
        if (
            interactive_components_dict[triggered_input_eval_index]["metadata"][
                "interactive_component_type"
            ]
            != "TextInput"
        ):
            check_value = True if value is not None else False
        else:
            check_value = True if value is not "" else False

    # print("CHECK VALUE")
    # print(check_value)
    # print("\n\n\n")

    other_components_dict = {
        id["index"]: {"value": value, "metadata": metadata}
        for (id, value, metadata) in zip(
            interactive_component_ids,
            interactive_component_values,
            stored_metadata_interactive,
        )
    }
    # print(other_components_dict)

    # print("\n\n\n")
    # print(current_draggable_children)
    # print(analyze_structure(current_draggable_children))
    # # current_draggable_children_to_keep = current_draggable_children[0]["props"]["children"]
    # print("\n\n\n")
    new_draggable_children = []
    for child in current_draggable_children:
        # print(child["props"]["id"])
        for sub_child in child["props"]["children"]:
            if sub_child["props"]["id"]["type"] == "add-content":
                # print(sub_child["props"]["id"])
                # print(sub_child["props"]["children"])
                child["props"]["children"] = [sub_child]
                continue
            # else:
            #     # child["props"]["children"] = child["props"]["children"].remove(sub_child)
            #     print("Removed sub_child with id " + str(sub_child["props"]["id"]))

    # print("\n\n\n")
    # print(current_draggable_children)
    # print("\n\n\n")
    print("END")

    # Add a new box to the dashboard
    if triggered_input == "add-button":
        # Retrieve index of the button that was clicked - this is the number of the plot
        if add_button_nclicks > stored_add_button["count"]:
            print("\n\n\n")
            print("add-button compared to stored_add_button")
            print(add_button_nclicks)
            print(stored_add_button["count"])
            print("\n\n\n")
            print("\n\n\n")
            print("\n\n\n")
            print("stored_metadata")
            print(stored_metadata)
            print("\n\n\n")
            print("\n\n\n")
            print("\n\n\n")
            # exit()

            n = ctx.triggered[0]["value"]
            new_plot_id = f"{n}"







            # print("\n\n\n")

            # print("workflow_label")
            # print(workflow_label)
            # print("data_collection_label")
            # print(data_collection_label)
            # print("add_button_nclicks")
            # print(add_button_nclicks)

            # import httpx

            # workflows = list_workflows(token)
            # if len(workflow_label) == 0 and len(data_collection_label) == 0:
            #     workflow_label = [workflows[0]["workflow_tag"]]
            #     data_collection_label = [
            #         workflows[0]["data_collections"][0]["data_collection_tag"]
            #     ]

            # print("workflow_label")
            # print(workflow_label)
            # print("data_collection_label")
            # print(data_collection_label)
            # print("\n\n\n")

            # workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_label[0]][0][
            #     "_id"
            # ]
            # data_collection_id = [
            #     f
            #     for e in workflows
            #     if e["_id"] == workflow_id
            #     for f in e["data_collections"]
            #     if f["data_collection_tag"] == data_collection_label[0]
            # ][0]["_id"]

            # API_BASE_URL = "http://localhost:8058"

            # dc_specs = httpx.get(
            #     f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
            #     headers={
            #         "Authorization": f"Bearer {token}",
            #     },
            # ).json()






            # stepper_dropdowns = create_stepper_dropdowns(n)
            # stepper_buttons = create_stepper_buttons(n, dc_specs["config"]["type"])
            stepper_output = create_stepper_output(
                n,
                active,
                new_plot_id,
                # dc_specs["config"]["type"],
                # n, active, new_plot_id, stepper_dropdowns, stepper_buttons, dc_specs["config"]["type"]
            )



            stored_add_button["count"] += 1

            # print("\n\n\n")
            # print("\n\n\n")
            # print("\n\n\n")
            # print("stepper_output")
            # print(stepper_output)
            # print("\n\n\n")
            # print("\n\n\n")
            # print("\n\n\n")

            current_draggable_children.append(stepper_output)

            # Define the default size and position for the new plot
            new_layout_item = {
                "i": f"{new_plot_id}",
                "x": 10 * ((len(current_draggable_children) + 1) % 2),
                "y": n * 10,
                "w": 6,
                "h": 5,
            }

            # Update the layouts property for both 'lg' and 'sm' sizes
            updated_layouts = {}
            for size in ["lg", "sm"]:
                if size not in current_layouts:
                    current_layouts[size] = []
                current_layouts[size] = current_layouts[size] + [new_layout_item]
            return (
                current_draggable_children,
                current_layouts,
                current_layouts,
                current_draggable_children,
                stored_edit_dashboard,
                stored_add_button,
            )
        else:
            raise dash.exceptions.PreventUpdate

    elif "interactive-component" in triggered_input and check_value:
        # print("\n\n\n")
        # print("\n\n\n")
        # print("\n\n\n")
        # print("================")
        # print("================")
        # print("================")
        # print("interactive-component PART")

        # Retrieve index of the interactive component that was clicked
        # triggered_input_eval = ast.literal_eval(triggered_input)
        # n = triggered_input_eval["index"]
        # n = int(n)
        # print(n, type(n))

        # print(interactive_components_dict)

        # Access the corresponding non interactive component with same workflow, data collection and column
        # print(stored_metadata)
        for j, e in enumerate(stored_metadata):
            print(j, e)
            if e["component_type"] != "interactive_component":
                # print("\n\n\n")
                # print("\n\n\n")
                # print("J : " + str(j))
                # print(e)
                new_df = return_deltatable(e["wf_id"], e["dc_id"])
                # print(new_df)
                # print("\n\n\n")

                for i, n in enumerate(list(interactive_components_dict.keys())):
                    # Retrieve corresponding metadata
                    n_dict = interactive_components_dict[n]
                    # print("\n\n\n")
                    # print("i : " + str(i))
                    # print("j : " + str(j))

                    # print("n_dict")
                    # print(n_dict)
                    # print(e["wf_id"])
                    # print(e["dc_id"])

                    # print(n_dict["metadata"]["wf_id"])
                    # print(n_dict["metadata"]["dc_id"])

                    if n_dict["metadata"]["dc_config"]["join"]:
                        n_join_dc = n_dict["metadata"]["dc_config"]["join"]
                    else:
                        n_join_dc = []

                    check_join = [
                        e["dc_id"]
                        for sub_join in n_join_dc
                        if e["dc_id"] in sub_join["with_dc"]
                    ]
                    # print("CHECK JOIN")
                    # print(n_join_dc)
                    # print(check_join)
                    # print(len(check_join))
                    # print((e["dc_id"] == n_dict["metadata"]["dc_id"]))
                    # print((len(check_join) > 0))

                    if e["wf_id"] == n_dict["metadata"]["wf_id"]:
                        if (e["dc_id"] == n_dict["metadata"]["dc_id"]) or (
                            len(check_join) > 0
                        ):
                            # print(e["component_type"])
                            # print(e["wf_id"])
                            # print(e["dc_id"])

                            # print(new_df)
                            # print(n_dict["metadata"]["type"])

                            # filter based on the column and the interactive component
                            # handle if the column is categorical or numerical

                            if n_dict["value"] is None or n_dict["value"] == []:
                                pass
                            else:
                                if n_dict["metadata"]["type"] == "object":
                                    # print("utf8")
                                    # print(
                                    #     n_dict["metadata"]["interactive_component_type"]
                                    # )
                                    # print(n_dict)
                                    # print(n_dict["value"])
                                    # print(n_dict["metadata"]["column_value"])
                                    if n_dict["metadata"][
                                        "interactive_component_type"
                                    ] in ["Select", "MultiSelect"]:
                                        # n_dict["value"] = list(n_dict["value"]) if type(n_dict["value"]) is str else n_dict["value"]
                                        print('n_dict["value"]')
                                        print(n_dict["value"])

                                        if n_dict["value"] is not None:
                                            n_dict["value"] = (
                                                list(n_dict["value"])
                                                if type(n_dict["value"]) is str
                                                else n_dict["value"]
                                            )
                                            new_df = new_df[
                                                new_df[
                                                    n_dict["metadata"]["column_value"]
                                                ].isin(n_dict["value"])
                                            ]
                                        else:
                                            new_df = new_df
                                    elif (
                                        n_dict["metadata"]["interactive_component_type"]
                                        == "TextInput"
                                    ):
                                        if n_dict["value"] != "":
                                            new_df = new_df[
                                                new_df[
                                                    n_dict["metadata"]["column_value"]
                                                ].str.contains(
                                                    n_dict["value"],
                                                    regex=True,
                                                    na=False,
                                                )
                                            ]
                                        else:
                                            new_df = new_df

                                elif (
                                    n_dict["metadata"]["type"] == "int64"
                                    or n_dict["metadata"]["type"] == "float64"
                                ):
                                    # print(
                                    #     n_dict["metadata"]["interactive_component_type"]
                                    # )
                                    # print(n_dict["value"])

                                    # handle if the input is a range or a single value
                                    if (
                                        n_dict["metadata"]["interactive_component_type"]
                                        == "RangeSlider"
                                    ):
                                        new_df = new_df[
                                            (
                                                new_df[
                                                    n_dict["metadata"]["column_value"]
                                                ]
                                                >= n_dict["value"][0]
                                            )
                                            & (
                                                new_df[
                                                    n_dict["metadata"]["column_value"]
                                                ]
                                                <= n_dict["value"][1]
                                            )
                                        ]
                                    elif (
                                        n_dict["metadata"]["interactive_component_type"]
                                        == "Slider"
                                    ):
                                        new_df = new_df[
                                            new_df[n_dict["metadata"]["column_value"]]
                                            == n_dict["value"]
                                        ]

                            # print("\n\n\n")
                            # print("new_df after filtering")
                            # print(new_df)

                            # replace the card value in the children props
                            for child in current_draggable_children:
                                # print(len(child["props"]["children"]))
                                # print("\n\n\n")
                                # print("analyzing child: child")
                                # analyze_structure(child)
                                # print("GET_MAX_DEPTH")
                                (
                                    max_depth,
                                    deepest_element_type,
                                ) = analyze_structure_and_get_deepest_type(child)
                                # print(max_depth, deepest_element_type)
                                # print('int(e["index"])')
                                # print(int(e["index"]))

                                # CARD PART UPDATE

                                if deepest_element_type == "card-value":
                                    # print("CARD PART UPDATE")
                                    # print(child["props"]["id"], int(e["index"]))
                                    if int(child["props"]["id"]) == int(e["index"]):
                                        # print("EQUAL")
                                        for k, sub_child in enumerate(
                                            child["props"]["children"][0]["props"][
                                                "children"
                                            ]["props"]["children"][-1]["props"][
                                                "children"
                                            ]["props"]["children"]
                                        ):
                                            # print("sub_child")
                                            # print(sub_child)
                                            # print(analyze_structure(sub_child))
                                            if "id" in sub_child["props"]:
                                                if (
                                                    sub_child["props"]["id"]["type"]
                                                    == "card-value"
                                                ):
                                                    # print(sub_child["props"]["children"])

                                                    aggregation = e["aggregation"]
                                                    new_value = new_df[
                                                        e["column_value"]
                                                    ].agg(aggregation)
                                                    if type(new_value) is np.float64:
                                                        new_value = round(new_value, 2)
                                                    sub_child["props"][
                                                        "children"
                                                    ] = new_value
                                                    # print(sub_child["props"]["children"])
                                                    continue

                                            # if type(sub_child["props"]["children"]) is dict:
                                            # for sub_sub_child in sub_child["props"]["children"]["props"]["children"]:
                                            #     if "id" in sub_sub_child["props"]:
                                            #         if sub_sub_child["props"]["id"]["type"] == "card-value":
                                            #             # CARD PART

                                            #             aggregation = e["aggregation"]
                                            #             new_value = new_df[e["column_value"]].agg(aggregation)
                                            #             # print(new_value, type(new_value))
                                            #             if type(new_value) is np.float64:
                                            #                 new_value = round(new_value, 2)
                                            #             # print(aggregation)
                                            #             # print(new_value)

                                            #             # print(sub_sub_child)
                                            #             # print(
                                            #             #     sub_sub_child["props"]["id"]
                                            #             # )
                                            #             sub_sub_child["props"]["children"] = new_value
                                            #             # print(
                                            #             #     sub_sub_child["props"][
                                            #             #         "children"
                                            #             #     ]
                                            #             # )
                                            #             continue
                                if deepest_element_type == "graph":
                                    # print("POTENTIAL GRAPH PART UPDATE")
                                    # print(stored_metadata)
                                    # print(child["props"]["id"], int(e["index"]))
                                    # print(analyze_structure(child))
                                    # print(child["props"].keys())
                                    # print(len(child["props"]["children"]))
                                    # print(child["props"]["children"][0]["props"]["children"]["props"].keys())
                                    # print(len(child["props"]["children"][0]["props"]["children"]["props"]["children"]))
                                    # print(int(child["props"]["id"]))
                                    # print(int(e["index"]))
                                    # print(child["props"]["children"][0]["props"]["children"]["props"]["children"][-1]["props"]["children"])
                                    if int(child["props"]["id"]) == int(e["index"]):
                                        # for k, sub_child in enumerate(child["props"]["children"][0]["props"]["children"]["props"]["children"]["props"]["children"]):
                                        for k, sub_child in enumerate(
                                            child["props"]["children"][0]["props"][
                                                "children"
                                            ]["props"]["children"][-1]["props"][
                                                "children"
                                            ]["props"]["children"]
                                        ):
                                            # print("sub_child")
                                            # print(sub_child)
                                            # print(analyze_structure(sub_child))
                                            if (
                                                sub_child["props"]["id"]["type"]
                                                == "graph"
                                            ):
                                                from depictio.dash.modules.figure_component.utils import (
                                                    plotly_vizu_dict,
                                                )

                                                new_figure = plotly_vizu_dict[
                                                    e["visu_type"].lower()
                                                ](new_df, **e["dict_kwargs"])
                                                sub_child["props"][
                                                    "figure"
                                                ] = new_figure

                                else:
                                    # print("OTHER")
                                    pass

                                    #     if sub_child["props"]["id"]["type"] == "card-value":
                                    #         print(sub_child)
                                    #         print(sub_child["props"]["id"])
                                    #         sub_child["props"]["children"] = new_value
                                    #         print(sub_child["props"]["children"])
                                    #         break
                                    # break

        return (
            current_draggable_children,
            current_layouts,
            current_layouts,
            current_draggable_children,
            stored_edit_dashboard,
            stored_add_button,
        )

        raise dash.exceptions.PreventUpdate

        return (
            updated_draggable_children,
            updated_layouts,
            # selected_year,
            updated_layouts,
            updated_draggable_children,
            # selected_year,
        )

    # if triggered_input.startswith("add-plot-button-"):
    #     plot_type = triggered_input.replace("add-plot-button-", "")

    #     n_clicks = ctx.triggered[0]["value"]
    #     print(n_clicks)

    #     new_plot_id = f"graph-{n_clicks}-{plot_type.lower().replace(' ', '-')}"
    #     new_plot_type = plot_type
    #     print(new_plot_type)

    #     if "-card" in new_plot_type:
    #         new_plot = html.Div(
    #             create_initial_figure(df, new_plot_type), id=new_plot_id
    #         )
    #     elif "-input" in new_plot_type:
    #         print(new_plot_id)
    #         # input_id = f"{plot_type.lower().replace(' ', '-')}"

    #         new_plot = create_initial_figure(df, new_plot_type, id=new_plot_id)
    #     else:
    #         new_plot = dcc.Graph(
    #             id=new_plot_id,
    #             figure=create_initial_figure(df, new_plot_type),
    #             responsive=True,
    #             style={
    #                 "width": "100%",
    #                 "height": "100%",
    #             },
    #             # config={"staticPlot": False, "editable": True},
    #         )
    #     # print(new_plot)

    #     # new_draggable_child = new_plot
    #     edit_button = dbc.Button(
    #         "Edit",
    #         id={
    #             "type": "edit-button",
    #             "index": f"edit-{new_plot_id}",
    #         },
    #         color="secondary",
    #         style={"margin-left": "10px"},
    #         # size="lg",
    #     )
    #     new_draggable_child = html.Div(
    #         [
    #             dbc.Button(
    #                 "Remove",
    #                 id={"type": "remove-button", "index": f"remove-{new_plot_id}"},
    #                 color="danger",
    #             ),
    #             edit_button,
    #             new_plot,
    #         ],
    #         id=f"draggable-{new_plot_id}",
    #     )
    #     # print(current_draggable_children)
    #     # print(len(current_draggable_children))

    #     updated_draggable_children = current_draggable_children + [new_draggable_child]

    #     # Define the default size and position for the new plot
    #     if "-card" not in new_plot_type:
    #         new_layout_item = {
    #             "i": f"draggable-{new_plot_id}",
    #             "x": 10 * ((len(updated_draggable_children) + 1) % 2),
    #             "y": n_clicks * 10,
    #             "w": 6,
    #             "h": 14,
    #         }
    #     else:
    #         new_layout_item = {
    #             "i": f"draggable-{new_plot_id}",
    #             "x": 10 * ((len(updated_draggable_children) + 1) % 2),
    #             "y": n_clicks * 10,
    #             "w": 4,
    #             "h": 5,
    #         }

    #     # Update the layouts property for both 'lg' and 'sm' sizes
    #     updated_layouts = {}
    #     for size in ["lg", "sm"]:
    #         if size not in current_layouts:
    #             current_layouts[size] = []
    #         updated_layouts[size] = current_layouts[size] + [new_layout_item]

    #     # Store the newly created figure in stored_figures
    #     # stored_figures[new_plot_id] = new_plot

    #     return (
    #         updated_draggable_children,
    #         updated_layouts,
    #         # selected_year,
    #         updated_layouts,
    #         updated_draggable_children,
    #         # selected_year,
    #     )

    # import ast

    # if "-input" in triggered_input and "remove-" not in triggered_input:
    #     input_id = ast.literal_eval(triggered_input)["index"]
    #     updated_draggable_children = []

    #     for j, child in enumerate(current_draggable_children):
    #         if child["props"]["id"].replace("draggable-", "") == input_id:
    #             updated_draggable_children.append(child)
    #         elif (
    #             child["props"]["id"].replace("draggable-", "") != input_id
    #             and "-input" not in child["props"]["id"]
    #         ):
    #             # print(child["props"]["id"]["index"])
    #             index = -1 if switch_state is True else 0
    #             graph = child["props"]["children"][index]
    #             if type(graph["props"]["id"]) is str:
    #                 # Extract the figure type and its corresponding function
    #                 figure_type = "-".join(graph["props"]["id"].split("-")[2:])
    #                 graph_id = graph["props"]["id"]
    #                 updated_fig = create_initial_figure(
    #                     df,
    #                     figure_type,
    #                     input_id="-".join(input_id.split("-")[2:]),
    #                     filter=filter_dict,
    #                 )

    #                 if "-card" in graph_id:
    #                     graph["props"]["children"] = updated_fig

    #                 else:
    #                     graph["props"]["figure"] = updated_fig
    #                 rm_button = dbc.Button(
    #                     "Remove",
    #                     id={
    #                         "type": "remove-button",
    #                         "index": child["props"]["id"],
    #                     },
    #                     color="danger",
    #                 )
    #                 edit_button = dbc.Button(
    #                     "Edit",
    #                     id={
    #                         "type": "edit-button",
    #                         "index": child["props"]["id"],
    #                     },
    #                     color="secondary",
    #                     style={"margin-left": "10px"},
    #                 )
    #                 children = (
    #                     [rm_button, edit_button, graph]
    #                     if switch_state is True
    #                     else [graph]
    #                 )
    #                 updated_child = html.Div(
    #                     children=children,
    #                     id=child["props"]["id"],
    #                 )

    #                 updated_draggable_children.append(updated_child)
    #         else:
    #             updated_draggable_children.append(child)

    #     return (
    #         updated_draggable_children,
    #         current_layouts,
    #         current_layouts,
    #         updated_draggable_children,
    #     )

    # if the remove button was clicked, return an empty list to remove all the plots

    elif "remove-" in triggered_input and [e for e in args[-10] if e]:
        print("\nREMOVE")
        print("Triggered Input:", triggered_input)

        input_id_dict = ast.literal_eval(triggered_input)
        input_id = input_id_dict["index"]
        print("Input ID:", input_id)

        # Use list comprehension to filter
        current_draggable_children = [
            child
            for child in current_draggable_children
            if child["props"]["id"] != input_id
        ]

        # elif "remove-" in triggered_input and [e for e in args[-10] if e]:
        #     print("\nREMOVE")
        #     print(triggered_input, type(triggered_input))
        #     # print(current_draggable_children)
        #     input_id = ast.literal_eval(triggered_input)["index"]
        #     print(input_id)

        #     # new_filter_dict = filter_dict
        #     # print(new_filter_dict)

        #     # Use a list comprehension to filter out the child with the matching ID
        #     current_draggable_children = [
        #         child for child in current_draggable_children
        #         if "-".join(child["props"]["id"].split("-")[1:]) != "-".join(input_id.split("-")[1:])
        #     ]
        # for child in current_draggable_children:
        #     print(child)
        #     # print("-".join(child["props"]["id"].split("-")[1:]))
        #     # print("-".join(input_id.split("-")[1:]))
        #     if "-".join(child["props"]["id"].split("-")[1:]) == "-".join(
        #         input_id.split("-")[1:]
        #     ):
        #         current_draggable_children.remove(child)
        #         input_id = "-".join(input_id.split("-")[2:])

        #         # Remove the corresponding entry from filter dictionary
        #         tmp_input_id = "-".join(input_id.split("-")[1:])
        #         if "-".join(input_id.split("-")[1:]) in new_filter_dict:
        #             del new_filter_dict[tmp_input_id]
        #         print(new_filter_dict)

        # updated_draggable_children = []

        # for j, child in enumerate(current_draggable_children):
        #     if child["props"]["id"].replace("draggable-", "") == input_id:
        #         updated_draggable_children.append(child)
        #     elif (
        #         child["props"]["id"].replace("draggable-", "") != input_id
        #         and "-input" not in child["props"]["id"]
        #     ):
        #         # print(child["props"]["id"]["index"])
        #         index = -1 if switch_state is True else 0
        #         graph = child["props"]["children"][index]
        #         if type(graph["props"]["id"]) is str:
        #             print("TEST")
        #             # Extract the figure type and its corresponding function
        #             figure_type = "-".join(graph["props"]["id"].split("-")[2:])
        #             graph_id = graph["props"]["id"]
        #             updated_fig = create_initial_figure(
        #                 df,
        #                 figure_type,
        #                 input_id="-".join(input_id.split("-")[2:]),
        #                 filter=new_filter_dict,
        #             )

        #             if "-card" in graph_id:
        #                 graph["props"]["children"] = updated_fig

        #             else:
        #                 graph["props"]["figure"] = updated_fig
        #             rm_button = dbc.Button(
        #                 "Remove",
        #                 id={
        #                     "type": "remove-button",
        #                     "index": child["props"]["id"],
        #                 },
        #                 color="danger",
        #             )
        #             edit_button = dbc.Button(
        #                 "Edit",
        #                 id={
        #                     "type": "edit-button",
        #                     "index": child["props"]["id"],
        #                 },
        #                 color="secondary",
        #                 style={"margin-left": "10px"},
        #             )
        #             children = (
        #                 [rm_button, edit_button, graph]
        #                 if switch_state is True
        #                 else [graph]
        #             )
        #             updated_child = html.Div(
        #                 children=children,
        #                 id=child["props"]["id"],
        #             )

        #             updated_draggable_children.append(updated_child)
        #     else:
        #         updated_draggable_children.append(child)

        return (
            current_draggable_children,
            new_layouts,
            # selected_year,
            new_layouts,
            current_draggable_children,
            stored_edit_dashboard,
            stored_add_button,
            # selected_year,
        )
        # return (
        #     updated_draggable_children,
        #     current_layouts,
        #     current_layouts,
        #     updated_draggable_children,
        # )

    elif triggered_input == "stored-layout" or triggered_input == "stored-children":
        if stored_layout_data and stored_children_data:
            return (
                stored_children_data,
                stored_layout_data,
                stored_layout_data,
                stored_children_data,
                stored_edit_dashboard,
                stored_add_button,
            )
        else:
            # Load data from the file if it exists
            loaded_data = load_data()
            if loaded_data:
                return (
                    loaded_data["stored_children_data"],
                    loaded_data["stored_layout_data"],
                    loaded_data["stored_layout_data"],
                    loaded_data["stored_children_data"],
                    stored_edit_dashboard,
                    stored_add_button,
                )
            else:
                return (
                    current_draggable_children,
                    {},
                    stored_layout,
                    stored_figures,
                    stored_edit_dashboard,
                    stored_add_button,
                )

    elif triggered_input == "draggable":
        # for child in current_draggable_children:
        #     print(child)
        return (
            dash.no_update,
            # current_draggable_children,
            new_layouts,
            # selected_year,
            new_layouts,
            dash.no_update,
            # current_draggable_children,
            stored_edit_dashboard,
            stored_add_button,
            # selected_year,
        )

    # div_index = 4 if box_type == "segmented-control-visu-graph" else 2
    # if box_type:
    #     if box_type == "segmented-control-visu-graph":
    #         child = children[div_index]["props"]["children"][0]["props"][
    #             "children"
    #         ]  # Figure
    #         child["props"]["id"]["type"] = (
    #             "updated-" + child["props"]["id"]["type"]
    #         )  # Figure

    #         # print(child)
    #         print("OK")
    #     elif box_type == "card":
    #         # print(children)
    #         child = children[div_index]["props"]["children"][1]["props"]["children"][
    #             1
    #         ]  # Card
    #         print(child)
    #         child["props"]["children"]["props"]["id"]["type"] = (
    #             "updated-" + child["props"]["children"]["props"]["id"]["type"]
    #         )  # Figure
    #     elif box_type == "input":
    #         # print(children)
    #         child = children[div_index]["props"]["children"][1]["props"]["children"][
    #             1
    #         ]  # Card
    #         print(child)
    #         child["props"]["children"]["props"]["id"]["type"] = (
    #             "updated-" + child["props"]["children"]["props"]["id"]["type"]

    # edit_button = dmc.Button(
    #     "Edit",
    #     id={
    #         "type": "edit-button",
    #         "index": f"edit-{btn_index}",
    #     },
    #     color="gray",
    #     variant="filled",
    #     leftIcon=DashIconify(icon="basil:edit-solid", color="white"),
    # )

    # remove_button = dmc.Button(
    #     "Remove",
    #     id={"type": "remove-button", "index": f"remove-{btn_index}"},
    #     color="red",
    #     variant="filled",
    #     leftIcon=DashIconify(icon="jam:trash", color="white"),
    # )

    # new_draggable_child = html.Div(
    #     [
    #         html.Div([remove_button, edit_button]),
    #         child,
    #     ],
    #     id=f"draggable-{btn_id}",
    # )

    elif triggered_input == "edit-dashboard-mode-button":
        # print("\n\n")

        # switch_state = True if len(ctx.triggered[0]["value"]) > 0 else False
        # print(switch_state)
        # print(stored_edit_dashboard)
        # print(current_draggable_children)
        # assuming the switch state is added as the first argument in args
        # updated_draggable_children = []
        updated_draggable_children = current_draggable_children
        # print("\n\n")
        # print("edit-dashboard-mode-button")
        # print(switch_state)
        # print(stored_edit_dashboard)

        # stored_edit_dashboard = switch_state

        # # analyze_structure(current_draggable_children)
        # # print(current_draggable_children[0]["props"]["children"])
        # # print(len(current_draggable_children[0]["props"]["children"]))
        # # print(
        # #     current_draggable_children[0]["props"]["children"][:-1],
        # #     type(current_draggable_children[0]["props"]["children"][:-1]),
        # #     len(current_draggable_children[0]["props"]["children"][:-1]),
        # # )
        # for j, child in enumerate(current_draggable_children):
        #     for i, sub_child in enumerate(child["props"]["children"]):
        #         if i != (len(child["props"]["children"]) - 1):
        #             try:
        #                 updated_sub_child = enable_box_edit_mode_dev(sub_child, switch_state)
        #             except Exception as e:
        #                 print(f"Error when calling enable_box_edit_mode_dev: {e}")
        #             # print(updated_sub_child)
        #             child["props"]["children"][i] = updated_sub_child
        #         else:
        #             child["props"]["children"][i] = sub_child
        #     updated_draggable_children.append(child)
        # if j != (len(current_draggable_children)-1):
        #         print("\n\n")
        #         print("updated_child")

        #         print(child)

        #         print("\n\n")
        #         print("\n\n")
        #         print("\n\n")
        #         print("\n\n")
        #         print("\n\n")
        #         analyze_structure(child)

        #         print(child)
        #         print(switch_state)
        #         try:
        # updated_child = enable_box_edit_mode_dev(child, switch_state)
        #         except Exception as e:
        #             print(f"Error when calling enable_box_edit_mode_dev: {e}")
        #         # print(updated_child)
        #         print("\n\n")

        # print(len(child))
        # print(child["props"]["id"])
        # print(len(child["props"]["children"]))
        # graph = child["props"]["children"][0]["props"]["children"][
        #     -2
        # ]  # Assuming graph is always the last child
        #     graph = child["props"]["children"][0]["props"]["children"][0]["props"]["children"]
        #     print(child["props"]["children"])
        # if switch_state:  # If switch is 'on', add the remove button
        #     # if "graph" in child["props"]["id"]:
        #     graph = child["props"]["children"][0]
        #     # print(graph["props"]["id"])

        #     edit_button = dmc.Button(
        #         "Edit",
        #         id={
        #             "type": "edit-button",
        #             "index": child["props"]["id"],
        #         },
        #         color="gray",
        #         variant="filled",
        #         leftIcon=DashIconify(icon="basil:edit-solid", color="white"),
        #     )

        #     remove_button = dmc.Button(
        #         "Remove",
        #         id={"type": "remove-button", "index": child["props"]["id"]},
        #         color="red",
        #         variant="filled",
        #         leftIcon=DashIconify(icon="jam:trash", color="white"),
        #     )

        #     updated_child = html.Div(
        #         [
        #             remove_button,
        #             edit_button,
        #             graph,
        #         ],
        #         id=child["props"]["id"],
        #     )

        #     # remove_button = dbc.Button(
        #     #     "Remove",
        #     #     id={
        #     #         "type": "remove-button",
        #     #         "index": child["props"]["id"],
        #     #     },
        #     #     color="danger",
        #     # )
        #     # edit_button = dbc.Button(
        #     #     "Edit",
        #     #     id={
        #     #         "type": "edit-button",
        #     #         "index": child["props"]["id"],
        #     #     },
        #     #     color="secondary",
        #     #     style={"margin-left": "10px"},
        #     # )

        #     # updated_child = html.Div(
        #     #     [remove_button, edit_button, graph],
        #     #     id=child["props"]["id"],
        #     # )
        # elif (
        #     switch_state is False and stored_edit_dashboard["count"] == 0
        # ):  # If switch is 'off', remove the button
        #     graph = child["props"]["children"][0]["props"]["children"]["props"][
        #         "children"
        #     ][2]
        #     # print(graph["props"]["id"])

        #     updated_child = html.Div(
        #         [graph],
        #         id=child["props"]["id"],
        #     )
        # else:
        #     graph = child["props"]["children"][-1]
        #     # print(child["props"]["id"])

        #     updated_child = html.Div(
        #         [graph],
        #         id=child["props"]["id"],
        #     )
        # updated_draggable_children.append(updated_child)
        # else:
        #     updated_draggable_children.append(child)
        # updated_draggable_children.append(child)

        return (
            updated_draggable_children,
            new_layouts,
            # selected_year,
            new_layouts,
            updated_draggable_children,
            stored_edit_dashboard,
            stored_add_button,
            # selected_year,
        )

    # # Add an else condition to return the current layout when there's no triggering input
    else:
        raise dash.exceptions.PreventUpdate


if __name__ == "__main__":
    app.run_server(debug=True, port="5080")
