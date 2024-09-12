import datetime
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, ALL
import dash
import httpx

from depictio.api.v1.configs.config import API_BASE_URL, logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token

current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def register_callbacks_header(app):
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


def design_header(data):
    """
    Design the header of the dashboard
    """
    # logger.info(f"depictio dashboard data: {data}")

    if data:
        if "stored_add_button" not in data:
            data["stored_add_button"] = {"count": 0}
        if "stored_edit_dashboard_mode_button" not in data:
            data["stored_edit_dashboard_mode_button"] = [int(0)]

    init_nclicks_add_button = data["stored_add_button"] if data else {"count": 0, "initialized": False}
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
    button_style = {"margin": "0 0px", "fontFamily": "Virgil", "marginTop": "5px"}

    # Right side of the header - Edit dashboard mode button
    # if data:

    add_new_component_button = dmc.ActionIcon(
        DashIconify(icon="ic:round-add-circle", width=35, color="#627bf2"),
        # dmc.Button(
        # "Add",
        id="add-button",
        size="xl",
        radius="xl",
        variant="subtle",
        n_clicks=init_nclicks_add_button["count"],
        # style={"width": "120px", "fontFamily": "Virgil", "marginRight": "10px"},
        style=button_style,
        disabled=disabled,
        # leftIcon=DashIconify(icon="mdi:plus", width=16, color="white"),
    )

    save_button = dmc.ActionIcon(
        DashIconify(icon="ic:baseline-save", width=35, color="#a2d64e"),
        # dmc.Button(
        # "Save",
        id="save-button-dashboard",
        size="xl",
        radius="xl",
        variant="subtle",
        gradient={"from": "teal", "to": "lime", "deg": 105},
        n_clicks=0,
        disabled=disabled,
        style=button_style,
        # leftIcon=DashIconify(icon="mdi:content-save", width=16, color="white"),
        # width of the button
        # style={"width": "120px", "fontFamily": "Virgil"},
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
            dmc.Stack(
                [
                    # dmc.CardSection(
                    # [
                    dmc.Badge(f"Owner: {data['permissions']['owners'][0]['email']}", color="blue", leftSection=DashIconify(icon="mdi:account", width=16, color="grey")),
                    dmc.Badge(f"Last saved: {data['last_saved_ts']}", color="green", leftSection=DashIconify(icon="mdi:clock-time-four-outline", width=16, color="grey")),
                    # ]
                    # ),
                ],
                justify="center",
                align="flex-start",
                spacing="xs",
            ),
        ],
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
                    # dmc.Button(
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:share-variant", width=20, color="white"),
                        id="share-button",
                        color="grey",
                        variant="filled",
                        # style={"fontFamily": "default"},
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
        DashIconify(icon="ic:baseline-settings", width=32, color="grey"),
        id="open-offcanvas-parameters-button",
        size="xl",
        radius="xl",
        color="grey",
        variant="subtle",
        style=button_style,
    )

    dummy_output = html.Div(id="dummy-output", style={"display": "none"})
    stepper_output = html.Div(id="stepper-output", style={"display": "none"})

    # Store the number of clicks for the add button and edit dashboard mode button
    stores_add_edit = [
        dcc.Store(
            id="stored-add-button",
            # storage_type="memory",
            storage_type="local",
            data=init_nclicks_add_button,
        ),
        dcc.Store(
            id="initialized-add-button",
            storage_type="memory",
            data=False,
        ),
        dcc.Store(
            id="stored-edit-dashboard-mode-button",
            # storage_type="memory",
            storage_type="session",
            data=init_nclicks_edit_dashboard_mode_button,
        ),
    ]

    button_menu = dmc.Group(
        [
            dcc.Store(
                id="initialized-navbar-button",
                storage_type="memory",
                data=False,
            ),
            dmc.MediaQuery(
                [
                    dmc.ActionIcon(
                        DashIconify(
                            id="sidebar-icon",
                            icon="ep:d-arrow-left",
                            width=34,
                            height=34,
                            color="#c2c7d0",
                        ),
                        variant="subtle",
                        p=1,
                        id="sidebar-button",
                    )
                ],
                smallerThan="md",
                styles={"display": "none"},
            ),
        ]
    )

    title_style = {"fontWeight": "bold", "fontSize": "24px", "color": "#333"}
    header = dmc.Header(
        [
            offcanvas_parameters,
            modal_save_button,
            remove_all_components_button,
            dummy_output,
            stepper_output,
            html.Div(children=stores_add_edit),
            dmc.Grid(
                [
                    # dmc.Col(
                    #     [button_menu],
                    #     # align="center",
                    #     style={"paddingLeft": "20px"},
                    #     span="content",
                    # ),
                    dmc.Col(
                        [
                            dmc.Group([button_menu, card_section]),
                        ],
                        style={"justify": "start"},
                        span=3,
                    ),
                    dmc.Col(
                        [
                            dmc.Center(
                                dmc.Title(
                                    f'{data["title"]}',
                                    order=1,  # Increase to order=1 for larger font size
                                    style={
                                        "color": "#333",  # Darker color for more emphasis
                                        "fontWeight": "bold",  # Make the text bold
                                        "fontSize": "24px",  # Increase font size
                                        # "fontFamily": "Open Sans",  # Change the font family
                                    },
                                )
                            ),
                        ],
                        span=7,
                    ),
                    dmc.Col(
                        [
                            html.Div(
                                children=[
                                    dmc.Group(
                                        [
                                            add_new_component_button,
                                            save_button,
                                            open_offcanvas_parameters_button,
                                        ],
                                        # justify="flex-end",
                                        # align="stretch",
                                        # style={"paddingTop": "5px"},
                                        spacing="xs",
                                        position="right",  # Aligns items to the right
                                        style={"paddingTop": "5px"},
                                    ),
                                ],
                            ),
                        ],
                        span=2,
                        # offset=1
                    ),
                ],
                # justify="between",
                # align="center",  # Ensure all elements are vertically centered
                align="center",
            ),
        ],
        height=80,
    style={"width": "100%"},
    )

    return header, backend_components
