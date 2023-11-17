import sys

print(sys.path)


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
    # register_callbacks_figure_component,
)

from depictio.dash.layouts.stepper import (
    register_callbacks_stepper,
)

register_callbacks_card_component(app)
register_callbacks_interactive_component(app)
register_callbacks_figure_component(app)
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

# Data


def return_deltatable(workflow_id: str = None, data_collection_id: str = None):
    df = load_deltatable(workflow_id, data_collection_id)
    # print(df)
    return df


df = load_deltatable(workflow_id=None, data_collection_id=None)


# df = pd.read_csv(
#     "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
# )
# print(df)


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
        dcc.Store(id="stored-children", storage_type="session"),
        dcc.Store(id="stored-layout", storage_type="session"),
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

header = html.Div(
    [
        html.H1("Depictio"),
        dmc.Button(
            "Add new component",
            id="add-button",
            size="lg",
            radius="xl",
            variant="gradient",
            n_clicks=0,
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
            style={"margin-left": "5px"},
        ),
        dbc.Checklist(
            id="edit-dashboard-mode-button",
            # color="secondary",
            style={"margin-left": "20px", "font-size": "22px"},
            # size="lg",
            # n_clicks=0,
            options=[
                {"label": "Edit dashboard", "value": 0},
            ],
            value=[0],
            switch=True,
        ),
        dcc.Store(
            id="stored-edit-dashboard-mode-button",
            storage_type="session",
            data={"count": 0},
        ),
    ],
)


# init_layout = dict()
# init_children = list()


data = load_data()
init_layout = data["stored_layout_data"] if data else {}
init_children = data["stored_children_data"] if data else list()

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
    fluid=False,
)


@app.callback(
    Output({"type": "modal", "index": MATCH}, "is_open"),
    [Input({"type": "btn-done", "index": MATCH}, "n_clicks")],
    prevent_initial_call=True,
)
def close_modal(n_clicks):
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
    # State("stored-year", "data"),
)
def save_data_dashboard(
    n_clicks,
    stored_layout_data,
    stored_children_data,
    # stored_year_data,
):
    # print(dash.callback_context.triggered[0]["prop_id"].split(".")[0], n_clicks)
    if n_clicks > 0:
        data = {
            "stored_layout_data": stored_layout_data,
            "stored_children_data": stored_children_data,
            # "stored_year_data": stored_year_data,
        }
        with open("data.json", "w") as file:
            json.dump(data, file)
        return n_clicks
    return n_clicks


def enable_box_edit_mode(box, switch_state=True):
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
    if switch_state:
        box_components_list = [remove_button, edit_button, box]
    else:
        box_components_list = [box]

    new_draggable_child = html.Div(
        box_components_list,
        id={"type": f"draggable-{btn_index}", "index": btn_index},
    )

    return new_draggable_child


def enable_box_edit_mode_dev(sub_child, switch_state=True):
    # print("enable_box_edit_mode_dev")
    # print(switch_state)

    # Extract the required substructure based on the depth analysis
    box = sub_child["props"]["children"]
    # print(box)

    # Check if the children attribute is a list
    if isinstance(box["props"]["children"], list):
        # print("List")

        # Identify if edit and remove buttons are present
        edit_button_exists = any(
            child.get("props", {}).get("id", {}).get("type") == "edit-box-button"
            for child in box["props"]["children"]
        )
        remove_button_exists = any(
            child.get("props", {}).get("id", {}).get("type") == "remove-box-button"
            for child in box["props"]["children"]
        )

        # print(switch_state, edit_button_exists, remove_button_exists)

        # If switch_state is true and buttons are not yet added, add them
        if switch_state and not (edit_button_exists and remove_button_exists):
            # Assuming that the ID for box is structured like: {'type': '...', 'index': 1}
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


@app.callback(
    Output({"type": "add-content", "index": MATCH}, "children"),
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
    # print("update_button")
    # children = [children[4]]
    # print(len(children))
    # print(children)
    children["props"]["id"]["type"] = "updated-" + children["props"]["id"]["type"]

    btn_index = btn_id["index"]  # Extracting index from btn_id dict

    switch_state_bool = True if len(switch_state) > 0 else False

    new_draggable_child = enable_box_edit_mode(children, switch_state_bool)
    # new_draggable_child = enable_box_edit_mode(children, btn_index, switch_state_bool)

    return new_draggable_child


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
def freeze_layout(value):
    # switch based on button's value
    switch_state = True if len(value) > 0 else False
    if switch_state is False:
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
    # print("update")
    # print(back, next_, current, workflow_selection, data_selection, btn_component)

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


@app.callback(
    Output({"type": "dropdown-output", "index": MATCH}, "children"),
    Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
    Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
    prevent_initial_call=True,
)
def update_step_2(workflow_selection, data_collection_selection):
    if workflow_selection is not None and data_collection_selection is not None:
        df = return_deltatable(workflow_selection, data_collection_selection)
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
        # print(df.head(20).to_dict("records"))
        grid = dag.AgGrid(
            id="get-started-example-basic",
            rowData=df.head(20).to_dict("records"),
            columnDefs=columnDefs,
            dashGridOptions={"tooltipShowDelay": 500},
        )
        layout = [run_nb_title, html.Hr(), data_previz_title, html.Hr(), grid]
        # print(layout)
        return layout
    else:
        return html.Div()


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
            df = return_deltatable(workflow_selection, data_collection_selection)

            components_list = ["Figure", "Card", "Interactive", "Genome browser"]
            component_selected = components_list[btn_index[0]]
            id = ids[btn_index[0]]
            if component_selected == "Figure":
                return design_figure(id, df), btn_component
            elif component_selected == "Card":
                return design_card(id, df), btn_component
            elif component_selected == "Interactive":
                return design_interactive(id, df), btn_component
            elif component_selected == "Genome browser":
                return design_jbrowse(id), btn_component

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
    ],
    # [
    #     Input(f"add-plot-button-{plot_type.lower().replace(' ', '-')}", "n_clicks")
    #     for plot_type in AVAILABLE_PLOT_TYPES.keys()
    # ]
    # +
    [
        Input("add-button", "n_clicks"),
        Input("edit-dashboard-mode-button", "value"),
        Input(
            {"type": "remove-box-button", "index": dash.dependencies.ALL}, "n_clicks"
        ),
        Input({"type": "input-component", "index": dash.dependencies.ALL}, "value"),
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
    ctx = dash.callback_context
    ctx_triggered = ctx.triggered
    print(f"CTX triggered: {ctx.triggered}")

    triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
    print(triggered_input)
    print(f"REMOVE BUTTON ARGS {args[-10]}")

    stored_layout_data = args[-8]
    stored_children_data = args[-7]
    new_layouts = args[-6]
    # print(args[-10])

    # remove-button -7
    # selected_year = args[-6]

    current_draggable_children = args[-5]
    # print("\n\n\n")
    # print("\n\n\n")
    # print("\n\n\n")
    # print("current_draggable_children")
    # print(current_draggable_children)
    # print("\n\n\n")
    # print("\n\n\n")
    # print("\n\n\n")
    current_layouts = args[-4]
    stored_layout = args[-3]
    stored_figures = args[-2]
    stored_edit_dashboard = args[-1]

    switch_state = True if len(args[-11]) > 0 else False
    switch_state_index = -1 if switch_state is True else -1
    # print(f"Switch state: {switch_state}")
    # print(f"Switch state value: {stored_edit_dashboard}")

    ######################################################################
    # filter_dict = {}
    # # Enumerate through all the children
    # for j, child in enumerate(current_draggable_children):
    #     # print(f"TOTO-{j}")
    #     # print(child["props"]["id"])
    #     # print(child["props"]["children"][switch_state_index]["props"])

    #     # Filter out those children that are not input components
    #     if (
    #         "-input" in child["props"]["id"]
    #         and "value"
    #         in child["props"]["children"][switch_state_index]["props"]["children"][-1][
    #             "props"
    #         ]
    #     ):
    #         # Extract the id and the value of the input component
    #         # print(f"TATA-{j}")

    #         id_components = child["props"]["children"][switch_state_index]["props"][
    #             "children"
    #         ][-1]["props"]["id"]["index"].split("-")[2:]
    #         value = child["props"]["children"][switch_state_index]["props"]["children"][
    #             -1
    #         ]["props"]["value"]

    #         # Construct the key for the dictionary
    #         key = "-".join(id_components)

    #         # Add the key-value pair to the dictionary
    #         filter_dict[key] = value
    ######################################################################

    # if current_draggable_children is None:
    #     current_draggable_children = []
    # if current_layouts is None:
    #     current_layouts = dict()

    from depictio.dash.layouts.stepper import (
        create_stepper_dropdowns,
        create_stepper_buttons,
        create_stepper_output,
    )

    # Add a new box to the dashboard
    if "add-button" in triggered_input:
        # Retrieve index of the button that was clicked - this is the number of the plot

        n = ctx.triggered[0]["value"]
        new_plot_id = f"{n}"

        stepper_dropdowns = create_stepper_dropdowns(n)
        stepper_buttons = create_stepper_buttons(n)
        stepper_output = create_stepper_output(
            n, active, new_plot_id, stepper_dropdowns, stepper_buttons
        )
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
        )

    #     return (
    #         updated_draggable_children,
    #         updated_layouts,
    #         # selected_year,
    #         updated_layouts,
    #         updated_draggable_children,
    #         # selected_year,
    #     )

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
            stored_edit_dashboard
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
                )
            else:
                return (
                    current_draggable_children,
                    {},
                    stored_layout,
                    stored_figures,
                    stored_edit_dashboard,
                )

    elif triggered_input == "draggable":
        return (
            dash.no_update,
            # current_draggable_children,
            new_layouts,
            # selected_year,
            new_layouts,
            dash.no_update,
            # current_draggable_children,
            stored_edit_dashboard
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
        stored_edit_dashboard["count"] = (
            stored_edit_dashboard["count"] + 1
            if switch_state
            else stored_edit_dashboard["count"]
        )

        # switch_state = True if len(ctx.triggered[0]["value"]) > 0 else False
        # print(switch_state)
        # print(stored_edit_dashboard)
        # print(current_draggable_children)
        # assuming the switch state is added as the first argument in args
        print("\n\n\n")
        updated_draggable_children = []
        print(
            current_draggable_children,
            len(current_draggable_children),
            type(current_draggable_children),
        )
        analyze_structure(current_draggable_children)
        # print(current_draggable_children[0]["props"]["children"])
        # print(len(current_draggable_children[0]["props"]["children"]))
        # print(
        #     current_draggable_children[0]["props"]["children"][:-1],
        #     type(current_draggable_children[0]["props"]["children"][:-1]),
        #     len(current_draggable_children[0]["props"]["children"][:-1]),
        # )
        for j, child in enumerate(current_draggable_children):
            for i, sub_child in enumerate(child["props"]["children"]):
                if i != (len(child["props"]["children"]) - 1):
                    print("\n\n")
                    print("sub_child")
                    print(sub_child)
                    print("\n\n")
                    print("\n\n")
                    print("\n\n")
                    print("\n\n")
                    print("\n\n")
                    analyze_structure(sub_child)
                    print(sub_child)
                    print(switch_state)
                    try:
                        updated_sub_child = enable_box_edit_mode_dev(
                            sub_child, switch_state
                        )
                    except Exception as e:
                        print(f"Error when calling enable_box_edit_mode_dev: {e}")
                    # print(updated_sub_child)
                    print("\n\n")
                    child["props"]["children"][i] = updated_sub_child
                else:
                    child["props"]["children"][i] = sub_child
            updated_draggable_children.append(child)
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
            stored_edit_dashboard
            # selected_year,
        )

    # # Add an else condition to return the current layout when there's no triggering input
    else:
        raise dash.exceptions.PreventUpdate


if __name__ == "__main__":
    app.run_server(debug=True, port="5080")
