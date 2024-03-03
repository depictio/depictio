import json
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash


def register_callbacks_header(app):
    @app.callback(
        Output("save-button-dashboard", "n_clicks"),
        Input("save-button-dashboard", "n_clicks"),
        State("stored-layout", "data"),
        State("stored-children", "data"),
        State("stored-edit-dashboard-mode-button", "data"),
        State("stored-add-button", "data"),
        prevent_initial_call=True,
    )
    def save_data_dashboard(
        n_clicks,
        stored_layout_data,
        stored_children_data,
        edit_dashboard_mode_button,
        add_button,
    ):
        if n_clicks > 0:
            data = {
                "stored_layout_data": stored_layout_data,
                "stored_children_data": stored_children_data,
                "stored_edit_dashboard_mode_button": edit_dashboard_mode_button,
                "stored_add_button": add_button,
            }
            with open("depictio_data.json", "w") as file:
                json.dump(data, file)
            return n_clicks
        return n_clicks

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

    # @app.callback(
    #     Output({"type": "add-button", "index": MATCH}, "disabled"),
    #     Output({"type": "save-button", "index": MATCH}, "disabled"),
    #     Input()


def design_header(data):
    """
    Design the header of the dashboard
    """
    init_nclicks_add_button = data["stored_add_button"] if data else {"count": 0}
    init_nclicks_edit_dashboard_mode_button = (
        data["stored_edit_dashboard_mode_button"] if data else [int(0)]
    )

    # Check if data is available, if not set the buttons to disabled
    disabled = False
    if not data:
        disabled = True

    # Backend components - dcc.Store for storing children and layout - memory storage
    # https://dash.plotly.com/dash-core-components/store
    backend_components = html.Div(
        [
            dcc.Store(id="stored-children", storage_type="memory"),
            dcc.Store(id="stored-layout", storage_type="memory"),
        ]
    )

    # Modal for success message when clicking the save button
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

    # APP Header

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
    
    # Right side of the header - Edit dashboard mode button
    if data:
        edit_switch = dbc.Checklist(
                    id="edit-dashboard-mode-button",
                    style={"fontSize": "22px"},
                    options=[{"label": "Edit dashboard", "value": 0}],
                    value=init_nclicks_edit_dashboard_mode_button,
                    switch=True,
        )
    else:       
        edit_switch = html.Div()


    header = html.Div(
        [
            # html.H1("Depictio", style=title_style),
            html.Img(src=dash.get_asset_url('logo.png')), 
            html.Div(
                [
                    # Left side of the header - Add new component button
                    dmc.Button(
                        "Add new component",
                        id="add-button",
                        size="lg",
                        radius="xl",
                        variant="gradient",
                        n_clicks=init_nclicks_add_button["count"],
                        style=button_style,
                        disabled=disabled,
                    ),
                    # Center part of the header - Save button + related modal
                    modal_save_button,
                    dmc.Button(
                        "Save",
                        id="save-button-dashboard",
                        size="lg",
                        radius="xl",
                        variant="gradient",
                        gradient={"from": "teal", "to": "lime", "deg": 105},
                        n_clicks=0,
                        disabled=disabled,
                    ),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            edit_switch,
            # Store the number of clicks for the add button and edit dashboard mode button
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

    return header, backend_components


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
