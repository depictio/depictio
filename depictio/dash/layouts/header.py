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
        # Output("reset-all-filters-button", "disabled"),
        Output("dashboard-version", "disabled"),
        Output("share-button", "disabled"),
        Output("draggable", "isDraggable"),
        Output("draggable", "isResizable"),
        Input("edit-dashboard-mode-button", "checked"),
        State("local-store", "data"),
        State("url", "pathname"),
        # prevent_initial_call=True,
    )
    def toggle_buttons(switch_state, local_store, pathname):
        logger.info("\n\n\n")
        logger.info("toggle_buttons")
        logger.info(switch_state)
        logger.info("API_BASE_URL: " + str(API_BASE_URL))

        len_output = 8

        current_user = fetch_user_from_token(local_store["access_token"])

        if not local_store["access_token"]:
            switch_state = False
            return [True] * len_output

        TOKEN = local_store["access_token"]

        dashboard_id = pathname.split("/")[-1]

        dashboard_data_response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}", headers={"Authorization": f"Bearer {TOKEN}"})
        if dashboard_data_response.status_code != 200:
            return [True] * len_output

        data = dashboard_data_response.json()

        # Check if data is available, if not set the buttons to disabled
        owner = True if str(current_user.id) in [str(e["_id"]) for e in data["permissions"]["owners"]] else False

        logger.info(f'{data["permissions"]["viewers"]}')

        viewer_ids = [str(e["_id"]) for e in data["permissions"]["viewers"] if e != "*"]
        is_viewer = str(current_user.id) in viewer_ids
        has_wildcard = "*" in data["permissions"]["viewers"]
        viewer = is_viewer or has_wildcard

        if not owner and viewer:
            return [dash.no_update] * (len_output - 2) + [False] * 2

        workflows = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json()
        if not workflows:
            switch_state = False
            return [True] * len_output

        return [not switch_state] * (len_output - 2) + [switch_state] * 2

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

    # @app.callback(
    #     Output("stored_metadata", "data"),
    #     Input("url", "pathname"),  # Assuming you have a URL component triggering on page load
    #     prevent_initial_call=True
    # )
    # def load_stored_metadata(pathname):
    #     """
    #     Load stored_metadata from MongoDB and store it in the 'stored_metadata' dcc.Store.
    #     """
    #     try:
    #         dashboard_id = pathname.split("/")[-1]
    #         logger.info(f"Loading stored_metadata for dashboard_id: {dashboard_id}")

    #         from depictio.api.v1.db import dashboards_collection
    #         dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    #         if not dashboard:
    #             logger.error(f"Dashboard with ID {dashboard_id} not found.")
    #             return dash.no_update

    #         stored_metadata = dashboard.get("stored_metadata", [])
    #         if not stored_metadata:
    #             logger.warning(f"No stored_metadata found for dashboard_id: {dashboard_id}.")
    #             return []

    #         logger.info(f"Loaded stored_metadata: {stored_metadata}")
    #         return stored_metadata

    #     except Exception as e:
    #         logger.exception("Failed to load stored_metadata from MongoDB.")
    #         return dash.no_update


def design_header(data, local_store):
    """
    Design the header of the dashboard
    """
    logger.info(f"depictio dashboard data: {data}")

    if data:
        if "stored_add_button" not in data:
            data["stored_add_button"] = {"count": 0}
        if "stored_edit_dashboard_mode_button" not in data:
            data["stored_edit_dashboard_mode_button"] = [int(0)]

    current_user = fetch_user_from_token(local_store["access_token"])
    logger.info(f"current_user: {current_user}")

    init_nclicks_add_button = data["stored_add_button"] if data else {"count": 0, "initialized": False, "id": ""}
    init_nclicks_edit_dashboard_mode_button = data["stored_edit_dashboard_mode_button"] if data else [int(0)]

    # Check if data is available, if not set the buttons to disabled
    owner = True if str(current_user.id) in [str(e["_id"]) for e in data["permissions"]["owners"]] else False

    logger.info(f'{data["permissions"]["viewers"]}')

    viewer_ids = [str(e["_id"]) for e in data["permissions"]["viewers"] if e != "*"]
    is_viewer = str(current_user.id) in viewer_ids
    has_wildcard = "*" in data["permissions"]["viewers"]
    viewer = is_viewer or has_wildcard

    if not owner and viewer:
        disabled = True
        edit_dashboard_mode_button_checked = False
        edit_components_button_checked = False
    else:
        disabled = False
        edit_dashboard_mode_button_checked = data["buttons_data"]["edit_dashboard_mode_button"]
        edit_components_button_checked = data["buttons_data"]["edit_components_button"]

    logger.info(f"owner: {owner}, viewer: {viewer}")
    logger.info(f"edit_dashboard_mode_button_checked: {edit_dashboard_mode_button_checked}")
    logger.info(f"edit_components_button_checked: {edit_components_button_checked}")
    logger.info(f"disabled: {disabled}")

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
            dcc.Store(id="stored-edit-component", data=None, storage_type="memory"),
            # dcc.Store(id="stored_metadata", data=None, storage_type="memory"),
            dcc.Store(id="stored-draggable-layouts", storage_type="session", data={}),
            dcc.Store(id="interactive-values-store", storage_type="session", data={}),
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


    sx={
        ":hover": {
            "backgroundColor": "#d0d0d0",  # Replace with your desired darker color
            "cursor": "pointer",  # Ensures the cursor changes to pointer on hover
        }
    }

    # Right side of the header - Edit dashboard mode button
    # if data:

    add_new_component_button = dmc.ActionIcon(
        DashIconify(icon="material-symbols:add", width=35, color="gray"),
        # DashIconify(icon="ic:round-add-circle", width=35, color="#627bf2"),
        # dmc.Button(
        # "Add",
        id="add-button",
        size="xl",
        radius="xl",
        variant="subtle",
        n_clicks=init_nclicks_add_button["count"],
        # color="blue",
        # style={"width": "120px", "fontFamily": "Virgil", "marginRight": "10px"},
        style=button_style,
        disabled=disabled,
        # leftIcon=DashIconify(icon="mdi:plus", width=16, color="white"),
        sx=sx
    )

    save_button = dmc.ActionIcon(
        DashIconify(icon="ic:baseline-save", width=35, color="gray"),
        # dmc.Button(
        # "Save",
        id="save-button-dashboard",
        size="xl",
        radius="xl",
        variant="subtle",
        # variant="filled",
        # color="teal",
        # gradient={"from": "teal", "to": "lime", "deg": 105},
        n_clicks=0,
        disabled=disabled,
        style=button_style,
        sx=sx
        # leftIcon=DashIconify(icon="mdi:content-save", width=16, color="white"),
        # width of the button
        # style={"width": "120px", "fontFamily": "Virgil"},
    )

    remove_all_components_button = dmc.Button(
        "Remove all components",
        id="remove-all-components-button",
        leftIcon=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        size="md",
        radius="xl",
        variant="gradient",
        gradient={"from": "red", "to": "pink", "deg": 105},
        # style=button_style,
        # Hide
        # style={"display": "none"},
        disabled=disabled,
        fullWidth=True,
    )

    if data["last_saved_ts"] == "":
        formated_ts = "Never"
    else:
        formated_ts = datetime.datetime.strptime(data["last_saved_ts"].split(".")[0], "%Y-%m-%d %H:%M:%S")

    card_section = dbc.Row(
        [
            dmc.Stack(
                [
                    # dmc.CardSection(
                    # [
                    dmc.Badge(f"Owner: {data['permissions']['owners'][0]['email']}", color="blue", leftSection=DashIconify(icon="mdi:account", width=16, color="grey")),
                    dmc.Badge(f"Last saved: {formated_ts}", color="green", leftSection=DashIconify(icon="mdi:clock-time-four-outline", width=16, color="grey")),
                    # ]
                    # ),
                ],
                justify="center",
                align="flex-start",
                spacing="xs",
            ),
        ],
    )

    toggle_switches_group = html.Div(
        [
            dmc.Title("Switches", order=4),
            dmc.Group(
                dmc.Select(
                    id="dashboard-version",
                    data=[f"{data['version']}"],
                    value=f"{data['version']}",
                    label="Dashboard version",
                    style={"width": 150, "padding": "0 10px", "display": "none"},
                    icon=DashIconify(icon="mdi:format-list-bulleted-square", width=16, color=dmc.theme.DEFAULT_COLORS["blue"][5]),
                    # rightSection=DashIconify(icon="radix-icons:chevron-down"),
                )
            ),
            dmc.Group(
                [
                    dmc.Switch(
                        id="edit-dashboard-mode-button",
                        checked=edit_dashboard_mode_button_checked,
                        disabled=disabled,
                        color="gray",
                    ),
                    dmc.Text("Edit dashboard layout", style={"fontFamily": "default"}),
                ],
                align="center",
                spacing="sm",
                style={"padding": "10px", "margin": "10px 0"},
            ),
            dmc.Group(
                [
                    dmc.Switch(
                        id="edit-components-mode-button",
                        checked=edit_components_button_checked,
                        disabled=disabled,
                        color="gray",
                    ),
                    dmc.Text("Display components options", style={"fontFamily": "default"}),
                ],
                align="center",
                spacing="sm",
                style={"padding": "10px", "margin": "10px 0"},
            ),
            dmc.Group(
                [
                    dmc.Switch(
                        id="toggle-interactivity-button",
                        checked=True,
                        color="gray",
                    ),
                    dmc.Text("Toggle interactivity", style={"fontFamily": "default"}),
                ],
                align="center",
                spacing="sm",
                style={"padding": "10px", "margin": "10px 0"},
            ),
        ]
    )

    buttons_group = html.Div(
        [
            dmc.Title("Buttons", order=4),
            dmc.Group([remove_all_components_button], align="center", spacing="sm", style={"padding": "10px", "margin": "10px 0"}),
            dmc.Group(
                [
                    dmc.Button(
                        "Reset all filters",
                        id="reset-all-filters-button",
                        leftIcon=DashIconify(icon="bx:reset", width=16, color="white"),
                        size="md",
                        radius="xl",
                        variant="gradient",
                        gradient={"from": "orange", "to": "yellow", "deg": 105},
                        # style=button_style,
                        # Hide
                        # style={"display": "none"},
                        disabled=False,
                        fullWidth=True,
                    )
                ]
            ),
            dmc.Group(
                [
                    # dmc.Button(
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:share-variant", width=20, color="white"),
                        id="share-button",
                        color="grey",
                        variant="filled",
                        disabled=disabled,
                        n_clicks=0,
                    ),
                    dmc.Text("Share", style={"fontFamily": "default"}),
                ],
                align="center",
                spacing="sm",
                style={"padding": "10px", "margin": "10px 0", "display": "none"},
            ),
        ]
    )

    offcanvas_parameters = dbc.Offcanvas(
        id="offcanvas-parameters",
        title="Parameters",
        placement="end",
        backdrop=True,
        children=[toggle_switches_group, buttons_group],
    )

    open_offcanvas_parameters_button = dmc.ActionIcon(
        DashIconify(icon="ic:baseline-settings", width=35, color="gray"),
        id="open-offcanvas-parameters-button",
        size="xl",
        radius="xl",
        # color="gray",
        # variant="filled",
        variant="subtle",
        style=button_style,
        sx=sx
    )

    dummy_output = html.Div(id="dummy-output", style={"display": "none"})
    dummy_output2 = html.Div(id="dummy-output2", style={"display": "none"})
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
        # dcc.Store(
        #     id="initialized-edit-button",
        #     storage_type="memory",
        #     data=False,
        # ),
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
            dummy_output,
            dummy_output2,
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
        withBorder=False,
    )

    return header, backend_components
