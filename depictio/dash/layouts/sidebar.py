import dash
import dash_mantine_components as dmc
from dash import ALL, Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.simple_theme import create_theme_controls


def register_sidebar_callbacks(app):
    # Inject JavaScript to handle the resize when sidebar state changes
    # app.clientside_callback(
    #     """
    #     function(navbar_config) {
    #         // Wait for DOM update then trigger resize
    #         setTimeout(function() {
    #             // Trigger window resize event
    #             window.dispatchEvent(new Event('resize'));

    #             // Also trigger resize for Plotly plots
    #             if (window.Plotly) {
    #                 var plots = document.querySelectorAll('.js-plotly-plot');
    #                 plots.forEach(function(plot) {
    #                     window.Plotly.Plots.resize(plot);
    #                 });
    #             }

    #             // Trigger resize for AG Grids
    #             if (window.agGrid) {
    #                 var grids = document.querySelectorAll('.ag-root-wrapper');
    #                 grids.forEach(function(grid) {
    #                     if (grid && grid.__agComponent && grid.__agComponent.gridOptions && grid.__agComponent.gridOptions.api) {
    #                         try {
    #                             grid.__agComponent.gridOptions.api.sizeColumnsToFit();
    #                         } catch (e) {
    #                             console.log('AG Grid resize error:', e);
    #                         }
    #                     }
    #                 });
    #             }

    #             // Dispatch custom event for draggable grids
    #             window.dispatchEvent(new CustomEvent('sidebar-toggled'));
    #         }, 350);  // Increased delay to match navbar animation (transition is 200ms)

    #         return window.dash_clientside.no_update;
    #     }
    #     """,
    #     dd.Output("dummy-resize-output", "children"),
    #     [dd.Input("app-shell", "navbar")],
    #     prevent_initial_call=True,
    # )

    # Combined callback to handle sidebar icon based on both initialization and clicks
    @app.callback(
        Output("sidebar-icon", "icon"),
        [Input("sidebar-collapsed", "data"), Input("url", "pathname")],
        prevent_initial_call=False,  # Allow initial call to set correct icon
    )
    def update_sidebar_icon(is_collapsed, pathname):
        # Don't update if on auth page (sidebar doesn't exist)
        if pathname == "/auth":
            return dash.no_update

        # Set icon based on current collapsed state
        # When collapsed -> show right arrow (points to expand)
        # When expanded -> show left arrow (points to collapse)
        return "ep:d-arrow-right" if is_collapsed else "ep:d-arrow-left"

    # Callback to show/hide the header favicon based on sidebar collapsed state
    @app.callback(
        Output("header-favicon", "style"),
        [Input("sidebar-collapsed", "data")],
        prevent_initial_call=False,
    )
    def update_header_favicon_visibility(is_collapsed):
        # Show favicon when sidebar is collapsed, hide when expanded
        base_style = {
            "height": "44px",
            "width": "44px",
            "marginLeft": "-5px",
            "marginRight": "0px",
        }

        if is_collapsed:
            base_style["display"] = "block"
        else:
            base_style["display"] = "none"

        return base_style

    # Callback to handle URL changes and navbar visibility
    @app.callback(
        Output("app-shell", "navbar"),
        Input("url", "pathname"),
        State("sidebar-collapsed", "data"),
        prevent_initial_call=True,
    )
    def handle_navbar_url_changes(pathname, is_collapsed):
        # Check if we're on the auth page - if so, hide the navbar completely
        if pathname == "/auth":
            return None

        # For other pages, show the navbar with current collapsed state
        navbar_config = {
            "width": 220,
            "breakpoint": "sm",
            "collapsed": {
                "mobile": True,
                "desktop": is_collapsed if is_collapsed is not None else False,
            },
        }

        return navbar_config

    # Callback to handle sidebar button clicks (conditional to avoid auth page error)
    @app.callback(
        Output("sidebar-collapsed", "data", allow_duplicate=True),
        Input("sidebar-button", "n_clicks"),
        State("sidebar-collapsed", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def handle_sidebar_button_click(n_clicks, is_collapsed, pathname):
        logger.info(
            f"Button clicked: {n_clicks}, Current state: {is_collapsed}, Pathname: {pathname}"
        )
        if n_clicks is None:
            raise PreventUpdate

        # Don't handle clicks on auth page (button doesn't exist there)
        if pathname == "/auth":
            raise PreventUpdate

        # Toggle the collapsed state
        logger.info(f"Toggling sidebar state from {is_collapsed} to {not is_collapsed}")
        return not is_collapsed

    # Update navbar when sidebar collapsed state changes
    @app.callback(
        Output("app-shell", "navbar", allow_duplicate=True),
        Input("sidebar-collapsed", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def update_navbar_from_collapsed_state(is_collapsed, pathname):
        # Don't update on auth page
        if pathname == "/auth":
            return dash.no_update

        # Return new navbar configuration
        navbar_config = {
            "width": 220,
            "breakpoint": "sm",
            "collapsed": {
                "mobile": True,
                "desktop": is_collapsed if is_collapsed is not None else False,
            },
        }

        return navbar_config

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
        Input("user-cache-store", "data"),
        prevent_initial_call=True,
    )
    def update_avatar(user_cache):
        from depictio.models.models.users import UserContext

        logger.info(f"🔧 AVATAR CALLBACK: user_cache received: {bool(user_cache)}")
        if user_cache:
            logger.info(
                f"🔧 AVATAR CALLBACK: user_cache keys: {list(user_cache.keys()) if isinstance(user_cache, dict) else 'not dict'}"
            )

        # Get user from consolidated cache
        current_user = UserContext.from_cache(user_cache)
        logger.info(f"🔧 AVATAR CALLBACK: current_user: {bool(current_user)}")

        if not current_user or not current_user.email:
            logger.info("🔧 AVATAR CALLBACK: No user or email, returning empty")
            return []

        email = current_user.email
        name = current_user.name
        avatar = dcc.Link(
            dmc.Avatar(
                id="avatar",
                src=f"https://ui-avatars.com/api/?format=svg&name={email}&background=AEC8FF&color=white&rounded=true&bold=true&format=svg&size=16",
                size="md",
                radius="xl",
            ),
            href="/profile",
        )
        name_text = dmc.Text(name, size="lg", style={"fontSize": "16px", "marginLeft": "10px"})
        logger.info(f"✅ AVATAR CALLBACK: Created avatar for {email}")
        return [avatar, name_text]

    @app.callback(
        Output("sidebar-footer-server-status", "children"),
        Input("server-status-cache", "data"),
        prevent_initial_call=True,
    )
    def update_server_status(server_cache):
        from depictio.dash.layouts.consolidated_api import get_cached_server_status

        # Get server status from consolidated cache
        server_status = get_cached_server_status(server_cache)
        if not server_status:
            return []

        if server_status["status"] == "online":
            server_status_badge = dmc.GridCol(
                dmc.Badge(
                    f"Server online - {server_status['version']}",
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

    @app.callback(
        Output({"type": "sidebar-link", "index": "administration"}, "style"),
        Input("user-cache-store", "data"),
        prevent_initial_call=True,
    )
    def show_admin_link(user_cache):
        from depictio.models.models.users import UserContext

        logger.info(f"🔧 ADMIN LINK CALLBACK: user_cache received: {bool(user_cache)}")

        # Get user from consolidated cache
        current_user = UserContext.from_cache(user_cache)
        if not current_user:
            logger.info("🔧 ADMIN LINK CALLBACK: No user, hiding admin link")
            return {"padding": "20px", "display": "none"}

        if current_user.is_admin:
            logger.info(f"✅ ADMIN LINK CALLBACK: Showing admin link for {current_user.email}")
            return {"padding": "20px"}
        else:
            logger.info(
                f"🔧 ADMIN LINK CALLBACK: Hiding admin link for non-admin {current_user.email}"
            )
            return {"padding": "20px", "display": "none"}

    # {"padding": "20px", "display": "none"}


def render_sidebar(email):
    # name = email.split("@")[0]

    depictio_logo = dcc.Link(
        html.Img(
            id="navbar-logo", src=dash.get_asset_url("images/logos/logo_black.svg"), height=45
        ),
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
        html.Img(
            id="navbar-logo-content",
            src=dash.get_asset_url("images/logos/logo_black.svg"),
            height=45,
        ),
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
