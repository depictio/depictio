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

    # Move sidebar icon to clientside for instant response
    app.clientside_callback(
        """
        function(is_collapsed, pathname) {
            console.log('🔧 CLIENTSIDE SIDEBAR ICON: collapsed=' + is_collapsed + ', pathname=' + pathname);

            // Don't update if on auth page (sidebar doesn't exist)
            if (pathname === '/auth') {
                return window.dash_clientside.no_update;
            }

            // Set icon based on current collapsed state
            // When collapsed -> show right arrow (points to expand)
            // When expanded -> show left arrow (points to collapse)
            return is_collapsed ? 'ep:d-arrow-right' : 'ep:d-arrow-left';
        }
        """,
        Output("sidebar-icon", "icon"),
        [Input("sidebar-collapsed", "data"), Input("url", "pathname")],
        prevent_initial_call=False,
    )

    # Move header favicon to clientside for instant response
    app.clientside_callback(
        """
        function(is_collapsed) {
            console.log('🔧 CLIENTSIDE FAVICON: collapsed=' + is_collapsed);

            var base_style = {
                "height": "44px",
                "width": "44px",
                "marginLeft": "-5px",
                "marginRight": "0px",
                "display": is_collapsed ? "block" : "none"
            };

            return base_style;
        }
        """,
        Output("header-favicon", "style"),
        [Input("sidebar-collapsed", "data")],
        prevent_initial_call=False,
    )

    # Move navbar URL changes to clientside for instant response
    app.clientside_callback(
        """
        function(pathname, is_collapsed) {
            console.log('🔧 CLIENTSIDE NAVBAR URL: pathname=' + pathname + ', collapsed=' + is_collapsed);

            // Check if we're on the auth page - if so, hide the navbar completely
            if (pathname === '/auth') {
                return null;
            }

            // For other pages, show the navbar with current collapsed state
            var navbar_config = {
                "width": 220,
                "breakpoint": "sm",
                "collapsed": {
                    "mobile": true,
                    "desktop": is_collapsed !== null ? is_collapsed : false
                }
            };

            return navbar_config;
        }
        """,
        Output("app-shell", "navbar"),
        [Input("url", "pathname")],
        [State("sidebar-collapsed", "data")],
        prevent_initial_call=False,
    )

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

    # Move navbar collapsed state update to clientside for instant response
    app.clientside_callback(
        """
        function(is_collapsed, pathname) {
            console.log('🔧 CLIENTSIDE NAVBAR COLLAPSED: collapsed=' + is_collapsed + ', pathname=' + pathname);

            // Don't update on auth page
            if (pathname === '/auth') {
                return window.dash_clientside.no_update;
            }

            // Return new navbar configuration
            var navbar_config = {
                "width": 220,
                "breakpoint": "sm",
                "collapsed": {
                    "mobile": true,
                    "desktop": is_collapsed !== null ? is_collapsed : false
                }
            };

            return navbar_config;
        }
        """,
        Output("app-shell", "navbar", allow_duplicate=True),
        [Input("sidebar-collapsed", "data")],
        [State("url", "pathname")],
        prevent_initial_call=True,
    )

    # Move sidebar active state to clientside for instant response
    app.clientside_callback(
        """
        function(pathname) {
            console.log('🔧 CLIENTSIDE SIDEBAR ACTIVE: pathname=' + pathname);

            if (pathname === '/dashboards') {
                return [true, false, false, false];
            } else if (pathname === '/projects') {
                return [false, true, false, false];
            } else if (pathname === '/admin') {
                return [false, false, true, false];
            } else if (pathname === '/about') {
                return [false, false, false, true];
            } else {
                return [false, false, false, false];
            }
        }
        """,
        Output({"type": "sidebar-link", "index": ALL}, "active"),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("avatar-container", "children"),
        Input("user-cache-store", "data"),
        prevent_initial_call=True,
    )
    def update_avatar(user_cache):
        # Get user from consolidated cache
        if user_cache and isinstance(user_cache, dict) and "user" in user_cache:
            user_data = user_cache["user"]

            if user_data and user_data.get("email"):
                email = user_data["email"]
                name = user_data.get("name", email.split("@")[0])
            else:
                return []
        else:
            return []
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

    # Move admin link visibility to clientside for instant response
    app.clientside_callback(
        """
        function(user_cache) {
            console.log('🔧 CLIENTSIDE ADMIN LINK: user_cache received:', !!user_cache);

            if (!user_cache || !user_cache.user) {
                console.log('🔧 CLIENTSIDE ADMIN LINK: No user, hiding admin link');
                return {"padding": "20px", "display": "none"};
            }

            var user = user_cache.user;
            if (user.is_admin) {
                console.log('✅ CLIENTSIDE ADMIN LINK: Showing admin link for', user.email);
                return {"padding": "20px"};
            } else {
                console.log('🔧 CLIENTSIDE ADMIN LINK: Hiding admin link for non-admin', user.email);
                return {"padding": "20px", "display": "none"};
            }
        }
        """,
        Output({"type": "sidebar-link", "index": "administration"}, "style"),
        Input("user-cache-store", "data"),
        prevent_initial_call=True,
    )

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
