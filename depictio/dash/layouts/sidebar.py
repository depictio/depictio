import dash
import dash.dependencies as dd
import dash_mantine_components as dmc
import httpx
from dash import ALL, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token


def register_sidebar_callbacks(app):
    # Inject JavaScript to handle the resize
    app.clientside_callback(
        """
        function(n_clicks) {
            setTimeout(function() {
                window.dispatchEvent(new Event('resize'));
            }, 50);
            return null;
        }
        """,
        dd.Output("sidebar", "style", allow_duplicate=True),
        [dd.Input("sidebar-button", "n_clicks")],
        prevent_initial_call=True,
    )

    # Callback to toggle sidebar
    @app.callback(
        Output("sidebar", "style"),
        Output("header", "height"),
        Output("sidebar-icon", "icon"),
        Output("initialized-navbar-button", "data"),
        Input("sidebar-button", "n_clicks"),
        State("sidebar", "style"),
        State("header", "height"),
        State("sidebar-icon", "icon"),
        State("initialized-navbar-button", "data"),
        prevent_initial_call=True,
    )
    def toggle_sidebar(n_clicks, sidebar_style, header_height, icon, initialized):
        if not initialized:
            return sidebar_style, header_height, icon, True

        if sidebar_style.get("display") == "none":
            sidebar_style["display"] = "flex"
            icon = "ep:d-arrow-left"
            return sidebar_style, header_height, icon, initialized
        else:
            icon = "ep:d-arrow-right"
            sidebar_style["display"] = "none"
            return sidebar_style, header_height, icon, initialized

    # Callback to update sidebar-link active state
    @app.callback(
        Output({"type": "sidebar-link", "index": ALL}, "active"),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )
    def update_active_state(pathname):
        if pathname == "/dashboards":
            return [True, False, False, False]
        elif pathname == "/projects":
            return [False, True, False, False]
        elif pathname == "/admin":
            return [False, False, True, False]
        elif pathname == "/about":
            return [False, False, False, True]
        else:
            return [False, False, False, False]

    @app.callback(
        Output("avatar-container", "children"),
        Input("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def update_avatar(pathname, local_store):
        if pathname == "/auth":
            return []

        current_user = api_call_fetch_user_from_token(local_store["access_token"])
        if not current_user or not current_user.email:
            return []
        email = current_user.email
        name = email.split("@")[0]
        avatar = dcc.Link(
            dmc.Avatar(
                id="avatar",
                src=f"https://ui-avatars.com/api/?format=svg&name={email}&background=AEC8FF&color=white&rounded=true&bold=true&format=svg&size=16",
                size="md",
                radius="xl",
            ),
            href="/profile",
        )
        name = dmc.Text(name, size="lg", style={"fontSize": "16px", "marginLeft": "10px"})
        return [avatar, name]

    @app.callback(
        Output("sidebar-footer-server-status", "children"),
        Input("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def update_server_status(pathname, local_store):
        if pathname == "/auth":
            return []

        try:
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/utils/status",
                headers={"Authorization": f"Bearer {local_store['access_token']}"},
                timeout=settings.performance.api_request_timeout,
            )
            if response.status_code != 200:
                server_status_badge = dmc.Col(
                    dmc.Badge(
                        "Server offline",
                        variant="dot",
                        color="red",
                        size=14,
                        style={"padding": "5px 5px"},
                    ),
                    span="content",
                )
                return [server_status_badge]
            else:
                logger.info(f"Server status: {response.json()}")
                server_status = response.json()["status"]
                if server_status == "online":
                    server_status_badge = dmc.Col(
                        dmc.Badge(
                            f"Server online - {response.json()['version']}",
                            variant="dot",
                            color="green",
                            size=14,
                        ),
                        span="content",
                    )

                    return [dmc.Group([server_status_badge], position="apart")]
                else:
                    server_status_badge = dmc.Col(
                        dmc.Badge(
                            "Server offline",
                            variant="outline",
                            color="red",
                            size=14,
                            style={"padding": "5px 5px"},
                        ),
                        span="content",
                    )
                    return [server_status_badge]

        except Exception as e:
            logger.error(f"Error fetching server status: {e}")
            server_status_badge = dmc.Col(
                dmc.Badge(
                    "Server offline",
                    variant="outline",
                    color="red",
                    size=14,
                    style={"padding": "5px 5px"},
                ),
                span="content",
            )
            return [server_status_badge]

    @app.callback(
        Output({"type": "sidebar-link", "index": "administration"}, "style"),
        Input("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def show_admin_link(pathname, local_store):
        if pathname == "/auth":
            return dash.no_update
        if not local_store or "access_token" not in local_store:
            return {"padding": "20px", "display": "none"}
        current_user = api_call_fetch_user_from_token(local_store["access_token"])
        if current_user.is_admin:
            return {"padding": "20px"}
        else:
            return {"padding": "20px", "display": "none"}

    # {"padding": "20px", "display": "none"}


def render_sidebar(email):
    # name = email.split("@")[0]

    depictio_logo = dcc.Link(
        html.Img(src=dash.get_asset_url("logo.png"), height=45),
        # html.Img(src=dash.get_asset_url("logo_icon.png"), height=40, style={"margin-left": "0px"}),
        href="/",
        style={"alignItems": "center", "justifyContent": "center", "display": "flex"},
    )

    sidebar_links = html.Div(
        id="sidebar-content",
        children=[
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "dashboards"},
                label=dmc.Text(
                    "Dashboards", size="lg", style={"fontSize": "16px"}
                ),  # Using dmc.Text to set the font size
                icon=DashIconify(icon="material-symbols:dashboard", height=25),
                href="/dashboards",
                style={"padding": "20px"},
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "projects"},
                label=dmc.Text(
                    "Projects", size="lg", style={"fontSize": "16px"}
                ),  # Using dmc.Text to set the font size
                icon=DashIconify(icon="mdi:jira", height=25),
                href="/projects",
                style={"padding": "20px"},
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "administration"},
                label=dmc.Text(
                    "Administration", size="lg", style={"fontSize": "16px"}
                ),  # Using dmc.Text to set the font size
                icon=DashIconify(icon="material-symbols:settings", height=25),
                href="/admin",
                style={"padding": "20px", "display": "none"},
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "about"},
                label=dmc.Text(
                    "About", size="lg", style={"fontSize": "16px"}
                ),  # Using dmc.Text to set the font size
                icon=DashIconify(icon="mingcute:question-line", height=25),
                href="/about",
                style={"padding": "20px"},
            ),
        ],
        style={
            "white-space": "nowrap",
            "margin-top": "20px",
            "flexGrow": "1",
            "overflowY": "auto",
        },
    )

    sidebar_footer = html.Div(
        id="sidebar-footer",
        # className="mt-auto",
        children=[
            dmc.Grid(
                id="sidebar-footer-server-status",
                align="center",
                justify="center",
            ),
            html.Hr(),
            html.Div(
                id="avatar-container",
                style={
                    "textAlign": "center",
                    "justifyContent": "center",
                    "display": "flex",
                    "alignItems": "center",  # Aligns Avatar and Text on the same line
                    "flexDirection": "row",  # Flex direction set to row (default)
                },
            ),
        ],
        style={
            "flexShrink": 0,  # Prevent footer from shrinking
        },
    )

    navbar = dmc.Navbar(
        p="md",
        fixed=False,
        width={"base": 220},
        hidden=True,
        hiddenBreakpoint="md",
        position="right",
        height="100vh",
        id="sidebar",
        style={
            "overflow": "hidden",
            "transition": "width 0.3s ease-in-out",
            "display": "flex",
            "flexDirection": "column",
        },
        children=[dmc.Center([depictio_logo]), sidebar_links, sidebar_footer],
    )

    return navbar
