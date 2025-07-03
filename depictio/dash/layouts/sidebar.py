import dash
import dash.dependencies as dd
import dash_mantine_components as dmc
import httpx
from dash import ALL, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token
from depictio.dash.theme_utils import create_theme_controls


def register_sidebar_callbacks(app):
    # Inject JavaScript to handle the resize when sidebar state changes
    app.clientside_callback(
        """
        function(navbar_config) {
            // Wait for DOM update then trigger resize
            setTimeout(function() {
                // Trigger window resize event
                window.dispatchEvent(new Event('resize'));

                // Also trigger resize for Plotly plots
                if (window.Plotly) {
                    var plots = document.querySelectorAll('.js-plotly-plot');
                    plots.forEach(function(plot) {
                        window.Plotly.Plots.resize(plot);
                    });
                }

                // Trigger resize for AG Grids
                if (window.agGrid) {
                    var grids = document.querySelectorAll('.ag-root-wrapper');
                    grids.forEach(function(grid) {
                        if (grid && grid.__agComponent && grid.__agComponent.gridOptions && grid.__agComponent.gridOptions.api) {
                            try {
                                grid.__agComponent.gridOptions.api.sizeColumnsToFit();
                            } catch (e) {
                                console.log('AG Grid resize error:', e);
                            }
                        }
                    });
                }

                // Dispatch custom event for draggable grids
                window.dispatchEvent(new CustomEvent('sidebar-toggled'));
            }, 350);  // Increased delay to match navbar animation (transition is 200ms)

            return window.dash_clientside.no_update;
        }
        """,
        dd.Output("dummy-resize-output", "children"),
        [dd.Input("app-shell", "navbar")],
        prevent_initial_call=True,
    )

    # Combined callback to handle sidebar icon based on both initialization and clicks
    @app.callback(
        Output("sidebar-icon", "icon"),
        [Input("sidebar-collapsed", "data"), Input("sidebar-button", "n_clicks")],
        prevent_initial_call=False,  # Allow initial call to set correct icon
    )
    def update_sidebar_icon(is_collapsed, n_clicks):
        # Set icon based on current collapsed state
        # When collapsed -> show right arrow (points to expand)
        # When expanded -> show left arrow (points to collapse)
        return "ep:d-arrow-right" if is_collapsed else "ep:d-arrow-left"

    # Callback to toggle AppShell navbar collapsed state using store
    @app.callback(
        Output("app-shell", "navbar"),
        Output("sidebar-collapsed", "data"),
        Input("sidebar-button", "n_clicks"),
        State("sidebar-collapsed", "data"),
        prevent_initial_call=True,
    )
    def toggle_appshell_navbar(n_clicks, is_collapsed):
        # Toggle the collapsed state
        new_collapsed_state = not is_collapsed

        # Return new navbar configuration
        navbar_config = {
            "width": 220,
            "breakpoint": "sm",
            "collapsed": {"mobile": True, "desktop": new_collapsed_state},
        }

        return navbar_config, new_collapsed_state

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
                server_status_badge = dmc.GridCol(
                    dmc.Badge(
                        "Server offline",
                        variant="dot",
                        color="red",
                        size="sm",
                        style={"padding": "5px 5px"},
                    ),
                    span="content",
                )
                return [server_status_badge]
            else:
                logger.info(f"Server status: {response.json()}")
                server_status = response.json()["status"]
                if server_status == "online":
                    server_status_badge = dmc.GridCol(
                        dmc.Badge(
                            f"Server online - {response.json()['version']}",
                            variant="dot",
                            color="green",
                            size="sm",
                        ),
                        span="content",
                    )

                    return [dmc.Group([server_status_badge], justify="space-between")]
                else:
                    server_status_badge = dmc.GridCol(
                        dmc.Badge(
                            "Server offline",
                            variant="outline",
                            color="red",
                            size="sm",
                            style={"padding": "5px 5px"},
                        ),
                        span="content",
                    )
                    return [server_status_badge]

        except Exception as e:
            logger.error(f"Error fetching server status: {e}")
            server_status_badge = dmc.GridCol(
                dmc.Badge(
                    "Server offline",
                    variant="outline",
                    color="red",
                    size="sm",
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
        html.Img(id="navbar-logo", src=dash.get_asset_url("logo_black.svg"), height=45),
        href="/",
        style={"alignItems": "center", "justifyContent": "center", "display": "flex"},
    )

    sidebar_links = html.Div(
        id="sidebar-content",
        children=[
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "dashboards"},
                label=dmc.Text(
                    "Dashboards", size="lg", style={"fontSize": "16px"}, className="section-accent"
                ),
                leftSection=DashIconify(icon="material-symbols:dashboard", height=25),
                href="/dashboards",
                style={"padding": "20px"},
                color="orange",
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "projects"},
                label=dmc.Text(
                    "Projects", size="lg", style={"fontSize": "16px"}, className="section-accent"
                ),
                leftSection=DashIconify(icon="mdi:jira", height=25),
                href="/projects",
                style={"padding": "20px"},
                color="teal",
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "administration"},
                label=dmc.Text(
                    "Administration",
                    size="lg",
                    style={"fontSize": "16px"},
                    className="section-accent",
                ),
                leftSection=DashIconify(icon="material-symbols:settings", height=25),
                href="/admin",
                style={"padding": "20px", "display": "none"},
                color="blue",
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "about"},
                label=dmc.Text(
                    "About", size="lg", style={"fontSize": "16px"}, className="section-accent"
                ),
                leftSection=DashIconify(icon="mingcute:question-line", height=25),
                href="/about",
                style={"padding": "20px"},
                color="gray",
            ),
        ],
        style={
            "whiteSpace": "nowrap",
            "marginTop": "20px",
            "flexGrow": "1",
            "overflowY": "auto",
        },
    )

    sidebar_footer = html.Div(
        id="sidebar-footer",
        # className="mt-auto",
        children=[
            dmc.Center(create_theme_controls()),
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

    # TODO: DMC 2.0+ - Navbar component no longer exists, replaced with Container
    navbar = dmc.Container(
        p="md",
        id="sidebar",
        style={
            "width": "220px",
            "height": "100vh",
            "overflow": "hidden",
            "transition": "width 0.3s ease-in-out",
            "display": "flex",
            "flexDirection": "column",
            "backgroundColor": "#ffffff",
            "borderRight": "1px solid #dee2e6",
        },
        children=[dmc.Center([depictio_logo]), sidebar_links, sidebar_footer],
    )

    return navbar


def render_sidebar_content(email):
    """Render just the navbar content for use in AppShellNavbar"""
    # name = email.split("@")[0]

    depictio_logo = dcc.Link(
        html.Img(id="navbar-logo-content", src=dash.get_asset_url("logo_black.svg"), height=45),
        href="/",
        style={"alignItems": "center", "justifyContent": "center", "display": "flex"},
    )

    sidebar_links = html.Div(
        id="sidebar-content",
        children=[
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "dashboards"},
                label=dmc.Text(
                    "Dashboards", size="lg", style={"fontSize": "16px"}, className="section-accent"
                ),
                leftSection=DashIconify(icon="material-symbols:dashboard", height=25),
                href="/dashboards",
                style={"padding": "20px"},
                color="orange",
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "projects"},
                label=dmc.Text(
                    "Projects", size="lg", style={"fontSize": "16px"}, className="section-accent"
                ),
                leftSection=DashIconify(icon="mdi:jira", height=25),
                href="/projects",
                style={"padding": "20px"},
                color="teal",
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "administration"},
                label=dmc.Text(
                    "Administration",
                    size="lg",
                    style={"fontSize": "16px"},
                    className="section-accent",
                ),
                leftSection=DashIconify(icon="material-symbols:settings", height=25),
                href="/admin",
                style={"padding": "20px", "display": "none"},
                color="blue",
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "about"},
                label=dmc.Text(
                    "About", size="lg", style={"fontSize": "16px"}, className="section-accent"
                ),
                leftSection=DashIconify(icon="mingcute:question-line", height=25),
                href="/about",
                style={"padding": "20px"},
                color="gray",
            ),
        ],
        style={
            "whiteSpace": "nowrap",
            "flex": "1",  # Take available space in Stack
            "overflowY": "auto",
        },
    )

    sidebar_footer = html.Div(
        id="sidebar-footer",
        children=[
            dmc.Center(create_theme_controls()),
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
                    "alignItems": "center",
                    "flexDirection": "row",
                },
            ),
        ],
        style={
            "flexShrink": 0,
        },
    )

    # Return content for AppShellNavbar - structured for full height
    return [
        dmc.Stack(
            [
                dmc.Center([depictio_logo]),
                sidebar_links,
                sidebar_footer,
            ],
            justify="space-between",
            h="100%",
            style={
                "padding": "16px",
                "height": "100%",
            },
        )
    ]
