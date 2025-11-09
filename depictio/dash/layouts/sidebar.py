import dash
import dash_mantine_components as dmc
from dash import ALL, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
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
    # Import and register tab callbacks
    from depictio.dash.layouts import tab_callbacks  # noqa: F401 - Import for callback registration

    logger.info("✅ SIDEBAR: Tab callbacks registered")

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

    # PHASE 2A OPTIMIZATION: Track last rendered server status to prevent duplicate renders
    _last_server_status_state = {"status": None, "version": None}

    @app.callback(
        Output("sidebar-footer-server-status", "children"),
        Input("server-status-cache", "data"),
        State("sidebar-footer-server-status", "children"),
        prevent_initial_call=False,  # Must be False to check ctx.triggered
    )
    def update_server_status(server_cache, current_children):
        """
        PERFORMANCE OPTIMIZATION (Phase 2A): Enhanced guards to prevent redundant updates.

        Guards:
        1. Skip if no trigger or empty value (initial load)
        2. Skip if server status hasn't actually changed (content comparison)

        This reduces callback fires from 4 → 1 during dashboard load.
        """
        from dash import ctx

        # DEBUG LOGGING: Log all inputs for troubleshooting
        logger.info("🔍 SERVER STATUS CALLBACK TRIGGERED")
        logger.info(f"  - Trigger: {ctx.triggered}")
        logger.info(f"  - server_cache: {server_cache}")
        logger.info(f"  - current_children type: {type(current_children)}")
        logger.info(f"  - _last_server_status_state: {_last_server_status_state}")

        # Get server status from server-status-cache store
        # server_cache contains data like: {"status": "online", "version": "0.5.2"}
        server_status = server_cache

        # GUARD 1: Skip if no valid cache data exists
        if not server_status or "status" not in server_status:
            logger.debug("🔴 GUARD 1: No valid cache data - preventing update")
            raise dash.exceptions.PreventUpdate

        # GUARD 2: Skip if server status hasn't changed AND element already has content
        # Compare relevant fields only (status + version)
        # IMPORTANT: Always render if current_children is None (element is empty in DOM)
        current_status = server_status.get("status")
        current_version = server_status.get("version")

        if (
            current_children is not None  # Element already has content
            and _last_server_status_state["status"] is not None
            and _last_server_status_state["status"] == current_status
            and _last_server_status_state["version"] == current_version
        ):
            logger.info(
                f"🔴 GUARD 2: Status unchanged ({current_status}, {current_version}) and element has content - preventing update"
            )
            raise dash.exceptions.PreventUpdate

        # Update tracking state
        _last_server_status_state["status"] = current_status
        _last_server_status_state["version"] = current_version

        logger.info(
            f"✅ update_server_status: Rendering new status ({current_status}, {current_version})"
        )

        # Render server status badge
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

    # Admin link visibility - server-side callback using local-store
    @app.callback(
        Output({"type": "sidebar-link", "index": "administration"}, "style"),
        Input("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_admin_link_visibility(local_data):
        """
        Show/hide admin link based on user's admin status.
        """
        if not local_data or not local_data.get("logged_in"):
            return {"padding": "20px", "display": "none"}

        try:
            # Fetch user details using cached API call
            from depictio.dash.api_calls import api_call_fetch_user_from_token

            user = api_call_fetch_user_from_token(local_data.get("access_token"))
            if user and user.is_admin:
                logger.debug(f"✅ Showing admin link for admin user: {user.email}")
                return {"padding": "20px"}
            else:
                logger.debug(
                    f"🔧 Hiding admin link for non-admin user: {user.email if user else 'unknown'}"
                )
                return {"padding": "20px", "display": "none"}
        except Exception as e:
            logger.error(f"❌ Error checking admin status: {e}")
            return {"padding": "20px", "display": "none"}

    app.clientside_callback(
        """
        function(local_data) {
            console.log('🔧 CLIENTSIDE AVATAR: local_data received:', !!local_data);

            // Check if user is logged in
            if (!local_data || !local_data.logged_in) {
                console.log('❌ No local_data or not logged in - returning empty');
                return [];
            }

            // Read token name which contains email with timestamp suffix
            // Example: "admin@example.com_20251107090126"
            var tokenName = local_data.name;
            if (!tokenName) {
                console.log('❌ No token name in local_data - returning empty');
                return [];
            }

            // Extract email by removing timestamp suffix (everything after first underscore)
            var email = tokenName.split('_')[0];

            // Extract name from email (before @)
            var name = email.split('@')[0];

            console.log('✅ CLIENTSIDE AVATAR: Creating avatar for', email, 'from token name', tokenName);

            // Create avatar link with image using clean email
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
        Input("local-store", "data"),
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

    # Minimal callback to reference sidebar tabs (dashboard viewer only)
    # NOTE: Only register this if sidebar-tabs component exists (viewer app)
    try:

        @app.callback(
            Input("sidebar-tabs", "value"),
            prevent_initial_call=True,
        )
        def sidebar_tabs_callback(tab_value):
            """
            Minimal callback to reference sidebar tabs component (dashboard viewer).
            No output - Dash supports callbacks without return statements.
            This prevents component ID errors while allowing for future expansion.
            """
            logger.debug(f"Sidebar tab changed to: {tab_value}")
            # No return statement - Dash allows this for callbacks without outputs
    except Exception as e:
        # Sidebar tabs may not exist in management app, skip callback
        logger.debug(f"Sidebar tabs callback not registered: {e}")


def create_dashboard_viewer_sidebar():
    """
    Create sidebar for dashboard viewer with tabs and footer.

    Tabs are populated dynamically via callback based on current dashboard and user permissions.

    Returns:
        list: Sidebar children with empty tabs container and footer
    """
    logger.info("🏗️ Creating dashboard viewer sidebar with tab container")

    # Create empty tabs component - will be populated by callback
    sidebar_tabs = dmc.Tabs(
        id="sidebar-tabs",
        orientation="vertical",
        placement="left",
        value=None,
        children=[dmc.TabsList([], id="sidebar-tabs-list")],
    )
    logger.info("✅ Created sidebar-tabs with sidebar-tabs-list")

    # Footer with server status and profile (same as management app)
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

    # Return tabs with footer at bottom
    return [
        dmc.Stack(
            [
                sidebar_tabs,
                sidebar_footer,
            ],
            justify="space-between",
            h="100%",
            style={
                "height": "100%",
                "width": "100%",  # Full width stack
            },
        )
    ]


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
