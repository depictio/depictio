import datetime
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, ALL
import dash
import httpx

from depictio.api.v1.configs.config import API_BASE_URL, logger

current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def register_callbacks_header(app):
    @app.callback(
        Output("dummy-output", "children"),
        Input("save-button-dashboard", "n_clicks"),
        State("draggable", "layouts"),
        State(
            {
                "type": "stored-metadata-component",
                "index": dash.dependencies.ALL,
            },
            "data",
        ),
        # State("draggable", "children"),
        State("stored-edit-dashboard-mode-button", "data"),
        State("stored-add-button", "data"),
        State({"type": "interactive-component-value", "index": ALL}, "value"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def save_data_dashboard(
        n_clicks,
        stored_layout_data,
        stored_metadata,
        # children,
        edit_dashboard_mode_button,
        add_button,
        interactive_component_values,
        pathname,
    ):
        if n_clicks:
            dashboard_id = pathname.split("/")[-1]

            logger.info(f"save_data_dashboard INSIDE")
            logger.info(f"stored-metadata-component: {stored_metadata}")

            # FIXME: check if some component are duplicated based on index value, if yes, remove them
            stored_metadata_indexes = list()
            for elem in stored_metadata:
                if elem["index"] in stored_metadata_indexes:
                    stored_metadata.remove(elem)
                else:
                    stored_metadata_indexes.append(elem["index"])

            # Get existing metadata for the dashboard
            dashboard_data = httpx.get(f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}").json()

            # Replace the existing metadata with the new metadata
            dashboard_data["stored_metadata"] = stored_metadata
            dashboard_data["stored_layout_data"] = stored_layout_data
            dashboard_data["stored_edit_dashboard_mode_button"] = edit_dashboard_mode_button
            dashboard_data["stored_add_button"] = add_button
            dashboard_data["version"] = "1"
            dashboard_data["last_saved_ts"] = str(current_time)

            logger.info(f"Dashboard data: {dashboard_data}")

            response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}", json=dashboard_data)
            if response.status_code == 200:
                logger.warn("Dashboard data saved successfully.")
            else:
                logger.warn(f"Failed to save dashboard data: {response.json()}")

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
        Output("add-button", "disabled"),
        Output("save-button-dashboard", "disabled"),
        Output("remove-all-components-button", "disabled"),
        Output("toggle-interactivity-button", "disabled"),
        Output("dashboard-version", "disabled"),
        Output("share-button", "disabled"),
        Output("draggable", "isDraggable"),
        Output("draggable", "isResizable"),
        Input("edit-dashboard-mode-button", "checked"),
        State("local-store", "data"),
        # prevent_initial_call=True,
    )
    def toggle_buttons(switch_state, local_store):
        logger.info("\n\n\n")
        logger.info("toggle_buttons")
        logger.info(switch_state)
        logger.info("API_BASE_URL: " + str(API_BASE_URL))

        if not local_store["access_token"]:
            switch_state = False
            return [True] * 8
        
        TOKEN = local_store["access_token"]


        workflows = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json()
        if not workflows:
            switch_state = False
            return [True] * 8

        return [not switch_state] * 6 + [switch_state] * 2

    @app.callback(
        Output("share-modal-dashboard", "is_open"),
        [
            Input("share-button", "n_clicks"),
            Input("share-modal-close", "n_clicks"),
        ],
        [State("share-modal-dashboard", "is_open")],
        prevent_initial_call=True,
    )
    def toggle_share_modal_dashboard(n_share, n_close, is_open):
        ctx = dash.callback_context

        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        # logger.info(trigger_id, n_save, n_close)

        if trigger_id == "share-button":
            if n_share is None or n_share == 0:
                raise dash.exceptions.PreventUpdate
            else:
                return True

        elif trigger_id == "share-modal-close":
            if n_close is None or n_close == 0:
                raise dash.exceptions.PreventUpdate
            else:
                return False

        return is_open

    @app.callback(
        Output("offcanvas-parameters", "is_open"),
        Input("open-offcanvas-parameters-button", "n_clicks"),
        State("offcanvas-parameters", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_offcanvas_parameters(n_clicks, is_open):
        logger.info(f"toggle_offcanvas_parameters: {n_clicks}, {is_open}")
        if n_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("offcanvas-menu", "is_open"),
        Input("open-offcanvas-menu-button", "n_clicks"),
        State("offcanvas-menu", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_offcanvas_menu(n_clicks, is_open):
        logger.info(f"toggle_offcanvas_menu: {n_clicks}, {is_open}")
        if n_clicks:
            return not is_open
        return is_open


def design_header(data):
    """
    Design the header of the dashboard
    """
    logger.info(f"depictio dashboard data: {data}")

    if data:
        if "stored_add_button" not in data:
            data["stored_add_button"] = {"count": 0}
        if "stored_edit_dashboard_mode_button" not in data:
            data["stored_edit_dashboard_mode_button"] = [int(0)]

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
            dcc.Store(
                id="stored-draggable-children",
                storage_type="session",
                data={},
            ),
            dcc.Store(id="stored-draggable-layouts", storage_type="session", data={}),
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

    modal_share_dashboard = dbc.Modal(
        [
            dbc.ModalHeader(
                html.H1(
                    "Share dashboard",
                    className="text-primary",
                )
            ),
            dbc.ModalBody(
                [
                    html.H5(
                        "Share this dashboard by copying the link below:",
                        className="text-primary",
                    ),
                    dmc.TextInput(type="text", value="https://depict.io/dashboard/1", style={"width": "100%"}, icon=DashIconify(icon="mdi:link", width=16, color="grey")),
                ],
                style={"background-color": "#F0F8FF"},
            ),
            dbc.ModalFooter(
                dbc.Button(
                    "Close",
                    id="share-modal-close",
                    className="ml-auto",
                    color="primary",
                )
            ),
        ],
        id="share-modal-dashboard",
        centered=True,
    )

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
    button_style = {"margin": "0 10px", "fontFamily": "Virgil"}

    # Right side of the header - Edit dashboard mode button
    # if data:

    add_new_component_button = dmc.Button(
        "Add component",
        id="add-button",
        size="lg",
        radius="xl",
        variant="gradient",
        n_clicks=init_nclicks_add_button["count"],
        style=button_style,
        disabled=disabled,
        leftIcon=DashIconify(icon="mdi:plus", width=16, color="white"),
    )

    save_button = dmc.Button(
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
        style={"width": "200px", "fontFamily": "Virgil"},
    )

    remove_all_components_button = dmc.Button(
        "Remove all components",
        id="remove-all-components-button",
        leftIcon=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        size="lg",
        radius="xl",
        variant="gradient",
        gradient={"from": "red", "to": "pink", "deg": 105},
        # style=button_style,
        # Hide
        style={"display": "none"},
        disabled=disabled,
    )

    card_section = dbc.Row(
        [
            dmc.Card(
                [
                    dmc.CardSection(
                        [
                            dmc.Badge(f"Owner: {data['owner']}", color="blue", leftSection=DashIconify(icon="mdi:account", width=16, color="grey")),
                            dmc.Badge(f"Last saved: {data['last_saved_ts']}", color="green", leftSection=DashIconify(icon="mdi:clock-time-four-outline", width=16, color="grey")),
                        ]
                    ),
                ],
            ),
        ],
    )

    offcanvas_menu = dbc.Offcanvas(
        id="offcanvas-menu",
        title="Menu",
        placement="start",
        backdrop=False,
        children=[
            dmc.Group(
                [
                    dmc.Button(
                        leftIcon=DashIconify(icon="mdi:home", width=20, color="white"),
                        id="home-button",
                        color="grey",
                        variant="filled",
                        style={"fontFamily": "default"},
                        disabled=disabled,
                        n_clicks=0,
                    ),
                    dmc.Text("Home", style={"fontFamily": "default"}),
                ],
                align="center",
                spacing="sm",
                style={"border": "1px solid lightgrey", "padding": "10px", "margin": "10px 0"},
            ),
            dmc.Group(
                [
                    dmc.Button(
                        leftIcon=DashIconify(icon="mdi:account", width=20, color="white"),
                        id="profile-button",
                        color="grey",
                        variant="filled",
                        style={"fontFamily": "default"},
                        disabled=disabled,
                        n_clicks=0,
                    ),
                    dmc.Text("Profile", style={"fontFamily": "default"}),
                ],
                align="center",
                spacing="sm",
                style={"border": "1px solid lightgrey", "padding": "10px", "margin": "10px 0"},
            ),
        ],
    )

    open_offcanvas_menu_button = dmc.ActionIcon(
        DashIconify(icon="mdi:menu", width=32, color="grey "),
        id="open-offcanvas-menu-button",
        size="xl",
        radius="xl",
        # color="grey",
        variant="transparent",
        style={"marginRight": "10px"},
    )

    offcanvas_parameters = dbc.Offcanvas(
        id="offcanvas-parameters",
        title="Parameters",
        placement="end",
        backdrop=False,
        children=[
            dmc.Group(
                dmc.Select(
                    id="dashboard-version",
                    data=[f"{data['version']}"],
                    value=f"{data['version']}",
                    label="Dashboard version",
                    style={"width": 150, "padding": "0 10px"},
                    icon=DashIconify(icon="mdi:format-list-bulleted-square", width=16, color=dmc.theme.DEFAULT_COLORS["blue"][5]),
                    # rightSection=DashIconify(icon="radix-icons:chevron-down"),
                )
            ),
            dmc.Group(
                [
                    dmc.Switch(
                        id="edit-dashboard-mode-button",
                        checked=True,
                        color="teal",
                    ),
                    dmc.Text("Edit dashboard", style={"fontFamily": "default"}),
                ],
                align="center",
                spacing="sm",
                style={"border": "1px solid lightgrey", "padding": "10px", "margin": "10px 0"},
            ),
            dmc.Group(
                [
                    dmc.Switch(
                        id="toggle-interactivity-button",
                        checked=True,
                        color="orange",
                    ),
                    dmc.Text("Toggle interactivity", style={"fontFamily": "default"}),
                ],
                align="center",
                spacing="sm",
                style={"border": "1px solid lightgrey", "padding": "10px", "margin": "10px 0"},
            ),
            dmc.Group(
                [
                    dmc.Button(
                        leftIcon=DashIconify(icon="mdi:share-variant", width=20, color="white"),
                        id="share-button",
                        color="grey",
                        variant="filled",
                        style={"fontFamily": "default"},
                        disabled=disabled,
                        n_clicks=0,
                    ),
                    dmc.Text("Share", style={"fontFamily": "default"}),
                ],
                align="center",
                spacing="sm",
                style={"border": "1px solid lightgrey", "padding": "10px", "margin": "10px 0"},
            ),
        ],
    )

    open_offcanvas_parameters_button = dmc.ActionIcon(
        DashIconify(icon="mdi:cog", width=32, color="white"),
        id="open-offcanvas-parameters-button",
        size="xl",
        radius="xl",
        color="grey",
        variant="filled",
        style=button_style,
    )

    dummy_output = html.Div(id="dummy-output", style={"display": "none"})
    stepper_output = html.Div(id="stepper-output", style={"display": "none"})

    # Add link to depictio logo to redirect to / page
    depictio_logo = html.A(
        html.Img(src=dash.get_asset_url("logo_icon.png"), height=40, style={"margin-left": "0px"}),
        href="/",
    )
    # depictio_logo = html.Img(src=dash.get_asset_url("logo.png"), height=40, style={"margin-left": "0px"})

    # Store the number of clicks for the add button and edit dashboard mode button
    stores_add_edit = [
        dcc.Store(
            id="stored-add-button",
            # storage_type="memory",
            storage_type="session",
            data=init_nclicks_add_button,
        ),
        dcc.Store(
            id="stored-edit-dashboard-mode-button",
            # storage_type="memory",
            storage_type="session",
            data=init_nclicks_edit_dashboard_mode_button,
        ),
    ]

    title_style = {"fontWeight": "bold", "fontSize": "24px", "color": "#333"}
    header = html.Div(
        [
            dummy_output,
            stepper_output,
            html.Div(children=stores_add_edit),
            open_offcanvas_menu_button,
            offcanvas_menu,
            dbc.Col(
                [depictio_logo],
                width=1,
            ),
            dbc.Col(
                [
                    card_section,
                ],
                width=2,
                align="end",
                style={"paddingLeft": "10px"},
            ),
            dbc.Col(
                [
                    dmc.Text(f'{data["title"]}', style=title_style),
                ],
                width=2,
                align="end",
                style={"paddingLeft": "10px"},
            ),
            # dbc.Col(width=1),
            dbc.Col(
                [
                    html.Div(
                        [
                            add_new_component_button,
                            modal_save_button,
                            save_button,
                            remove_all_components_button,
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    )
                ],
                width=6,
            ),
            open_offcanvas_parameters_button,
            offcanvas_parameters,
        ],
        style=header_style,
    )

    return header, backend_components


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
            # Assuming the last element is the main content box
            content_box = box["props"]["children"][-1]
            box["props"]["children"] = [content_box]

    sub_child["props"]["children"] = box
    return sub_child
