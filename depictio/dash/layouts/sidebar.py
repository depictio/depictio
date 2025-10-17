import dash
import dash_mantine_components as dmc
from dash import ALL, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.dash.layouts.consolidated_api import get_cached_server_status
from depictio.dash.simple_theme import create_theme_controls


def create_static_navbar_content():
    """
    PERFORMANCE OPTIMIZATION: Generate static navbar HTML once at app startup.

    This function generates the navbar content that was previously built dynamically
    via a callback on every page load, causing ~2419ms delay.

    Returns:
        list: Navbar children to be passed to AppShellNavbar
    """
    depictio_logo_container = html.Div(
        id="navbar-logo-container",
        children=[
            dcc.Link(
                dmc.Image(
                    id="navbar-logo-content",
                    src=dash.get_asset_url("images/logos/logo_black.svg"),
                    w=185,
                ),
                href="/",
                style={"alignItems": "center", "justifyContent": "center", "display": "flex"},
            )
        ],
    )

    sidebar_links = dmc.Stack(
        id="sidebar-content",
        children=[
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "dashboards"},
                label=dmc.Text(
                    "Dashboards",
                    size="lg",
                    style={"fontSize": "16px"},
                    className="section-accent",
                ),
                leftSection=DashIconify(icon="material-symbols:dashboard", height=25),
                href="/dashboards",
                style={"padding": "20px"},
                color="orange",
            ),
            dmc.NavLink(
                id={"type": "sidebar-link", "index": "projects"},
                label=dmc.Text(
                    "Projects",
                    size="lg",
                    style={"fontSize": "16px"},
                    className="section-accent",
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
                    "About",
                    size="lg",
                    style={"fontSize": "16px"},
                    className="section-accent",
                ),
                leftSection=DashIconify(icon="mingcute:question-line", height=25),
                href="/about",
                style={"padding": "20px"},
                color="gray",
            ),
        ],
        gap="xs",
        style={
            "whiteSpace": "nowrap",
            "flex": "1",
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
                    "paddingBottom": "16px",
                },
            ),
        ],
        style={
            "flexShrink": 0,
        },
    )

    # Return layout - same for all pages
    return [
        dmc.Stack(
            [
                dmc.Center(
                    [depictio_logo_container],
                    id="navbar-logo-center",
                    pt="md",
                ),
                sidebar_links,
                sidebar_footer,
            ],
            justify="space-between",
            h="100%",
            style={
                "height": "100%",
            },
        )
    ]


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

    # NOTE: sidebar-icon callback removed - now using DMC Burger which manages its own icon state

    # Move header favicon to clientside for instant response
    # Favicon only relevant on dashboard pages (where navbar exists)
    app.clientside_callback(
        """
        function(is_collapsed, pathname) {
            console.log('🔧 CLIENTSIDE FAVICON: collapsed=' + is_collapsed + ', pathname=' + pathname);

            // Only manage favicon on dashboard pages
            if (!pathname || !pathname.startsWith('/dashboard/')) {
                console.log('❌ Not a dashboard page - hiding favicon');
                return {"display": "none"};
            }

            // Show favicon when navbar is collapsed on dashboard pages
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
        [Input("sidebar-collapsed", "data"), Input("url", "pathname")],
        prevent_initial_call=False,
    )

    # NOTE: Navbar is now always visible via static config in app_layout.py
    # Only update collapse state for dashboard pages
    app.clientside_callback(
        """
        function(is_collapsed, pathname) {
            console.log('🔧 CLIENTSIDE NAVBAR COLLAPSED: collapsed=' + is_collapsed + ', pathname=' + pathname);

            // Only allow collapse on dashboard pages
            if (!pathname || !pathname.startsWith('/dashboard/')) {
                console.log('❌ Not a dashboard page - keeping navbar expanded');
                return window.dash_clientside.no_update;
            }

            // Update navbar collapse state for dashboard pages
            console.log('✅ Updating navbar collapse state for dashboard');
            var navbar_config = {
                "width": 220,
                "breakpoint": "sm",
                "collapsed": {
                    "mobile": true,
                    "desktop": is_collapsed ? true : false
                }
            };

            return navbar_config;
        }
        """,
        Output("app-shell", "navbar"),
        [Input("sidebar-collapsed", "data")],
        [State("url", "pathname")],
        prevent_initial_call=True,
    )

    # NOTE: sidebar-button callback removed - now using DMC Burger which handles clicks via
    # update_collapsed_from_burger() in header.py

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

    # Hide logo on dashboard pages for cleaner view
    app.clientside_callback(
        """
        function(pathname) {
            console.log('🔧 CLIENTSIDE NAVBAR LOGO: pathname=' + pathname);

            // Hide logo on individual dashboard pages (/dashboard/{dashboard_id})
            if (pathname && pathname.startsWith('/dashboard/')) {
                console.log('✅ Dashboard page - hiding logo');
                return {"display": "none"};
            } else {
                console.log('✅ Non-dashboard page - showing logo');
                return {"display": "block"};
            }
        }
        """,
        Output("navbar-logo-container", "style"),
        Input("url", "pathname"),
        prevent_initial_call=False,
    )

    # Reduce top padding when logo is hidden on dashboard pages
    app.clientside_callback(
        """
        function(pathname) {
            console.log('🔧 CLIENTSIDE NAVBAR LOGO CENTER: pathname=' + pathname);

            // Hide logo center completely on dashboard pages for maximum space efficiency
            if (pathname && pathname.startsWith('/dashboard/')) {
                console.log('✅ Dashboard page - hiding logo center entirely');
                return {"display": "none"};
            } else {
                console.log('✅ Non-dashboard page - showing logo center');
                return {"display": "block"};
            }
        }
        """,
        Output("navbar-logo-center", "style"),
        Input("url", "pathname"),
        prevent_initial_call=False,
    )

    # NOTE: Avatar callback removed - replaced with "Powered by Depictio" section
    # NOTE: Theme-aware logo callbacks removed - no logos to invert anymore

    @app.callback(
        Output("sidebar-footer-server-status", "children"),
        Input("server-status-cache", "data"),
        prevent_initial_call=False,
    )
    def update_server_status(server_cache):
        """
        PERFORMANCE OPTIMIZATION: Import moved to module level to avoid repeated import overhead.
        Update server status badge based on cached server status data.
        """
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
        prevent_initial_call=False,
    )

    # Avatar callback - CONVERTED TO CLIENT-SIDE for instant response (~0.8s savings)
    # This breaks CASCADE #1 (user-cache-store → avatar-container, 1.9s total)
    app.clientside_callback(
        """
        function(user_cache) {
            console.log('🔧 CLIENTSIDE AVATAR: user_cache received:', !!user_cache);

            // Check if we have valid user data
            if (!user_cache || !user_cache.user) {
                console.log('❌ No user cache - returning empty');
                return [];
            }

            var user = user_cache.user;
            if (!user.email) {
                console.log('❌ No email in user - returning empty');
                return [];
            }

            var email = user.email;
            var name = user.name || email.split('@')[0];

            console.log('✅ CLIENTSIDE AVATAR: Creating avatar for', email);

            // Create avatar link with image
            var avatarSrc = 'https://ui-avatars.com/api/?format=svg&name=' + encodeURIComponent(email) +
                           '&background=AEC8FF&color=white&rounded=true&bold=true&format=svg&size=16';

            return [
                {
                    namespace: 'dash_core_components',
                    type: 'Link',
                    props: {
                        href: '/profile',
                        children: {
                            namespace: 'dash_mantine_components',
                            type: 'Avatar',
                            props: {
                                id: 'avatar',
                                src: avatarSrc,
                                size: 'md',
                                radius: 'xl'
                            }
                        }
                    }
                },
                {
                    namespace: 'dash_mantine_components',
                    type: 'Text',
                    props: {
                        children: name,
                        size: 'sm',
                        style: {marginLeft: '5px'}
                    }
                }
            ];
        }
        """,
        Output("avatar-container", "children"),
        Input("user-cache-store", "data"),
        prevent_initial_call=False,
    )

    # PERFORMANCE OPTIMIZATION: Navbar callback disabled - replaced with static content at app startup
    # This callback was causing ~2419ms delay on every page load by rebuilding the same HTML structure
    # The navbar content is now generated once by create_static_navbar_content() in app_layout.py
    # Commenting out instead of removing to preserve the code structure for reference
    # @app.callback(
    #     Output("app-shell-navbar-content", "children"),
    #     Input("url", "pathname"),
    #     prevent_initial_call=False,
    # )
    # def render_dynamic_navbar_content(pathname):
    #     """Render navbar content with logo, navlinks, and footer with avatar."""
    #     depictio_logo_container = html.Div(
    #         id="navbar-logo-container",
    #         children=[
    #             dcc.Link(
    #                 dmc.Image(
    #                     id="navbar-logo-content",
    #                     src=dash.get_asset_url("images/logos/logo_black.svg"),
    #                     # h=38,
    #                     w=185,
    #                 ),
    #                 href="/",
    #                 style={"alignItems": "center", "justifyContent": "center", "display": "flex"},
    #             )
    #         ],
    #     )
    #
    #     sidebar_links = dmc.Stack(
    #         id="sidebar-content",
    #         children=[
    #             dmc.NavLink(
    #                 id={"type": "sidebar-link", "index": "dashboards"},
    #                 label=dmc.Text(
    #                     "Dashboards",
    #                     size="lg",
    #                     style={"fontSize": "16px"},
    #                     className="section-accent",
    #                 ),
    #                 leftSection=DashIconify(icon="material-symbols:dashboard", height=25),
    #                 href="/dashboards",
    #                 style={"padding": "20px"},
    #                 color="orange",
    #             ),
    #             dmc.NavLink(
    #                 id={"type": "sidebar-link", "index": "projects"},
    #                 label=dmc.Text(
    #                     "Projects",
    #                     size="lg",
    #                     style={"fontSize": "16px"},
    #                     className="section-accent",
    #                 ),
    #                 leftSection=DashIconify(icon="mdi:jira", height=25),
    #                 href="/projects",
    #                 style={"padding": "20px"},
    #                 color="teal",
    #             ),
    #             dmc.NavLink(
    #                 id={"type": "sidebar-link", "index": "administration"},
    #                 label=dmc.Text(
    #                     "Administration",
    #                     size="lg",
    #                     style={"fontSize": "16px"},
    #                     className="section-accent",
    #                 ),
    #                 leftSection=DashIconify(icon="material-symbols:settings", height=25),
    #                 href="/admin",
    #                 style={"padding": "20px", "display": "none"},
    #                 color="blue",
    #             ),
    #             dmc.NavLink(
    #                 id={"type": "sidebar-link", "index": "about"},
    #                 label=dmc.Text(
    #                     "About",
    #                     size="lg",
    #                     style={"fontSize": "16px"},
    #                     className="section-accent",
    #                 ),
    #                 leftSection=DashIconify(icon="mingcute:question-line", height=25),
    #                 href="/about",
    #                 style={"padding": "20px"},
    #                 color="gray",
    #             ),
    #         ],
    #         gap="xs",
    #         style={
    #             "whiteSpace": "nowrap",
    #             "flex": "1",
    #             "overflowY": "auto",
    #         },
    #     )
    #
    #     sidebar_footer = html.Div(
    #         id="sidebar-footer",
    #         children=[
    #             dmc.Center(create_theme_controls()),
    #             dmc.Grid(
    #                 id="sidebar-footer-server-status",
    #                 align="center",
    #                 justify="center",
    #             ),
    #             html.Hr(),
    #             html.Div(
    #                 id="avatar-container",
    #                 style={
    #                     "textAlign": "center",
    #                     "justifyContent": "center",
    #                     "display": "flex",
    #                     "alignItems": "center",
    #                     "flexDirection": "row",
    #                     "paddingBottom": "16px",  # Add padding to bottom of avatar
    #                 },
    #             ),
    #         ],
    #         style={
    #             "flexShrink": 0,
    #         },
    #     )
    #
    #     # Return layout - same for all pages
    #     return [
    #         dmc.Stack(
    #             [
    #                 dmc.Center(
    #                     [depictio_logo_container],
    #                     id="navbar-logo-center",
    #                     pt="md",  # Add padding to top of logo
    #                 ),
    #                 sidebar_links,
    #                 sidebar_footer,
    #             ],
    #             justify="space-between",
    #             h="100%",
    #             style={
    #                 "height": "100%",
    #             },
    #         )
    #     ]


def _create_powered_by_footer():
    """Create footer with theme controls and server status for dashboard pages."""
    return dmc.Stack(
        id="powered-by-footer",
        children=[
            dmc.Center(create_theme_controls()),
            dmc.Grid(
                id="sidebar-footer-server-status",
                align="center",
                justify="center",
            ),
        ],
        gap="sm",
        style={
            "flexShrink": 0,
        },
    )
