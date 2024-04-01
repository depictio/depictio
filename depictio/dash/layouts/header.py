import datetime
import json
import sys
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, ALL, MATCH
import dash
import httpx

from depictio.dash.utils import analyze_structure_and_get_deepest_type, get_size
from depictio.api.v1.configs.config import API_BASE_URL, logger


def register_callbacks_header(app):
    @app.callback(
        Output("dummy-output", "children"),
        Input("save-button-dashboard", "n_clicks"),
        State("stored-layout", "data"),
        State(
            {
                "type": "stored-metadata-component",
                "index": dash.dependencies.ALL,
            },
            "data",
        ),
        State("stored-children", "data"),
        State("stored-edit-dashboard-mode-button", "data"),
        State("stored-add-button", "data"),
        prevent_initial_call=True,
    )
    def save_data_dashboard(
        n_clicks,
        stored_layout_data,
        stored_metadata,
        children,
        edit_dashboard_mode_button,
        add_button,
    ):
        if n_clicks > 0:
            logger.info("\n\n\n")
            logger.info(f"save_data_dashboard INSIDE")

            logger.info(f"stored_layout_data: {type(stored_layout_data)} {get_size(stored_layout_data)}")
            logger.info(f"stored_metadata: {type(stored_metadata)} {get_size(stored_metadata)}")
            logger.info(f"edit_dashboard_mode_button: {type(edit_dashboard_mode_button)} {get_size(edit_dashboard_mode_button)}")
            logger.info(f"add_button: {type(add_button)} {get_size(add_button)}")
            logger.info(f"n_clicks: {n_clicks}")

            dashboard_data = {
                "stored_layout_data": stored_layout_data,
                "stored_metadata": stored_metadata,
                "stored_edit_dashboard_mode_button": edit_dashboard_mode_button,
                "stored_add_button": add_button,
                "version": "1",
            }
            dashboard_id = "1"
            dashboard_data["dashboard_id"] = dashboard_id
            logger.info("Dashboard data:")
            logger.info(dashboard_data)

            response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}", json=dashboard_data)
            if response.status_code == 200:
                logger.warn("Dashboard data saved successfully.")
            else:
                logger.warn(f"Failed to save dashboard data: {response.json()}")

            dashboard_data["stored_children_data"] = children

            with open("/app/data/depictio_data.json", "w") as file:
                json.dump(dashboard_data, file)
            return []
        return dash.no_update

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
        # logger.info(trigger_id, n_save, n_close)

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
        Output({"type": "test-container", "index": MATCH}, "children", allow_duplicate=True),
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
        # logger.info("\n\n\n")
        # logger.info("update_button")
        # logger.info(children)
        # logger.info(analyze_structure(children))
        # logger.info(len(children))

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

        # logger.info(children["props"]["id"])
        # children = [children[4]]
        # logger.info(len(children))
        # logger.info(children)

        children["props"]["id"]["type"] = "updated-" + children["props"]["id"]["type"]
        # logger.info(children)

        btn_index = btn_id["index"]  # Extracting index from btn_id dict

        # switch_state_bool = True if len(switch_state) > 0 else False

        # new_draggable_child = children
        new_draggable_child = enable_box_edit_mode(children, switch_state)
        # new_draggable_child = enable_box_edit_mode(children, btn_index, switch_state_bool)

        return new_draggable_child, []

    @app.callback(
        Output("add-button", "disabled"),
        Output("save-button-dashboard", "disabled"),
        Output("remove-all-components-button", "disabled"),
        Output("toggle-interactivity-button", "disabled"),
        Output("dashboard-version", "disabled"),
        Output("draggable", "isDraggable"),
        Output("draggable", "isResizable"),
        Input("edit-dashboard-mode-button", "checked"),
        prevent_initial_call=True,
    )
    def toggle_buttons(switch_state):
        logger.info("\n\n\n")
        logger.info("toggle_buttons")
        logger.info(switch_state)

        return [not switch_state] * 5 + [switch_state] * 2


def design_header(data):
    """
    Design the header of the dashboard
    """
    init_nclicks_add_button = data["stored_add_button"] if data else {"count": 0}
    init_nclicks_edit_dashboard_mode_button = data["stored_edit_dashboard_mode_button"] if data else [int(0)]

    # Check if data is available, if not set the buttons to disabled
    disabled = False
    # if not data:
    #     disabled = True

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
    from dash_iconify import DashIconify

    # APP Header

    header_style = {
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
        "padding": "10px 20px",
        "backgroundColor": "#FCFCFC",
        "borderBottom": "1px solid #eaeaea",
        "fontFamily": "'Open Sans', sans-serif",
    }

    title_style = {"fontWeight": "bold", "fontSize": "24px", "color": "#333"}
    button_style = {"margin": "0 10px", "fontWeight": "500"}

    # Right side of the header - Edit dashboard mode button
    # if data:
    edit_switch = dmc.Switch(
        # edit_switch = dbc.Checklist(
        id="edit-dashboard-mode-button",
        label="Edit dashboard",
        thumbIcon=DashIconify(icon="mdi:lead-pencil", width=16, color=dmc.theme.DEFAULT_COLORS["teal"][5]),
        style={"fontSize": "28x"},
        # options=[{"label": "Edit dashboard", "value": 0}],
        # value=init_nclicks_edit_dashboard_mode_button,
        # switch=True,
        checked=True,
        color="teal",
    )
    toggle_interactivity = dmc.Switch(
        label="Toggle interactivity",
        id="toggle-interactivity-button",
        thumbIcon=DashIconify(icon="mdi:gesture-tap", width=16, color=dmc.theme.DEFAULT_COLORS["orange"][5]),
        style={"fontSize": "28px"},
        # options=[{"label": "Toggle interactivity", "value": 0}],
        # value=0,
        checked=True,
        # switch=True,
        color="orange",
    )
    # else:
    #     edit_switch = html.Div()

    # TODO: toggle interactivity button

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = html.Div(
        [
            # html.H1("Depictio", style=title_style),
            # Invisible div to store the test data
            dbc.Col(
                [html.Div(id="dummy-output", style={"display": "none"}), html.Img(src=dash.get_asset_url("logo.png"), height=40, style={"margin-left": "0px"})],
                width=2,
            ),
            dbc.Col(
                [
                    dmc.Select(
                        id="dashboard-version",
                        data=["v1", "v2"],
                        value="v2",
                        label="Dashboard version",
                        style={"width": 150, "padding": "0 10px"},
                        icon=DashIconify(icon="mdi:format-list-bulleted-square", width=16, color=dmc.theme.DEFAULT_COLORS["blue"][5]),
                        rightSection=DashIconify(icon="radix-icons:chevron-down"),
                    ),
                ],
                width=1,
            ),
            # dbc.Col(width=1),
            dbc.Col(
                [
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
                                leftIcon=DashIconify(icon="mdi:plus", width=16, color="white"),
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
                                leftIcon=DashIconify(icon="mdi:content-save", width=16, color="white"),
                                # width of the button
                                style={"width": "200px"},
                            ),
                            dmc.Button(
                                "Remove all components",
                                id="remove-all-components-button",
                                leftIcon=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
                                size="lg",
                                radius="xl",
                                variant="gradient",
                                gradient={"from": "red", "to": "pink", "deg": 105},
                                style=button_style,
                                disabled=disabled,
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    )
                ],
                width=6,
            ),
            html.Div(
                [
                    dbc.Col([dbc.Row(edit_switch), dbc.Row(toggle_interactivity, style={"paddingTop": "5px"})], width=3, style={"justifyContent": "flex-end"}),
                    dbc.Col(
                        [
                            dmc.ActionIcon(
                                DashIconify(icon="mdi:share-variant", width=32, color="white"),
                                id="share-button",
                                size="xl",
                                radius="xl",
                                color="grey",
                                variant="filled",
                                style=button_style,
                            ),
                        ],
                        width=1,
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "padding": "0 50px 0 0"},
            ),
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
    from dash_iconify import DashIconify

    remove_button = dmc.Button(
        "Remove",
        id={"type": "remove-box-button", "index": f"{btn_index}"},
        color="red",
        leftIcon=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    )
    # remove_button = dbc.Button(
    #     "Remove",
    #     id={"type": "remove-box-button", "index": f"{btn_index}"},
    #     color="danger",
    # )

    # reset_button = dbc.Button(
    #     "Reset",
    #     id={"type": "reset-box-button", "index": f"{btn_index}"},
    #     color="info",
    #     style={"margin-left": "24px"},
    # )

    if switch_state:
        box_components_list = [remove_button, box]
        # box_components_list = [remove_button, edit_button, box]
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
    logger.info("enable_box_edit_mode_dev")
    logger.info(switch_state)

    # Extract the required substructure based on the depth analysis
    box = sub_child["props"]["children"]
    logger.info(box)

    # Check if the children attribute is a list
    if isinstance(box["props"]["children"], list):
        logger.info("List")

        # Identify if edit and remove buttons are present
        edit_button_exists = any(child.get("props", {}).get("id", {}).get("type") == "edit-box-button" for child in box["props"]["children"])
        remove_button_exists = any(child.get("props", {}).get("id", {}).get("type") == "remove-box-button" for child in box["props"]["children"])

        logger.info(switch_state, edit_button_exists, remove_button_exists)

        # If switch_state is true and buttons are not yet added, add them
        if switch_state and not (edit_button_exists and remove_button_exists):
            # Assuming that the ID for box is structured like: {'type': '...', 'index': 1}
            logger.info("\n\n\n")
            logger.info("Adding buttons")
            logger.info(box["props"]["id"])
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
            box["props"]["children"] = [remove_button, edit_button] + box["props"]["children"]

        # If switch_state is false and buttons are present, remove them
        elif not switch_state and edit_button_exists and remove_button_exists:
            # logger.info("Removing buttons")
            # Assuming the last element is the main content box
            # logger.info(analyze_structure(box))
            # logger.info(box)
            content_box = box["props"]["children"][-1]
            # logger.info(content_box)
            box["props"]["children"] = [content_box]
            # logger.info(box)

    sub_child["props"]["children"] = box
    # logger.info(sub_child)
    # Return the modified sub_child structure
    return sub_child
