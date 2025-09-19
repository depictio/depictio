import dash
import dash_mantine_components as dmc
from dash import Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.simple_theme import create_theme_controls


def register_sidebar_callbacks(app):
    # Callback to dynamically update sidebar content based on route
    @app.callback(
        Output("sidebar-content", "children"),
        Input("url", "pathname"),
        State("user-cache-store", "data"),
        prevent_initial_call=True,
    )
    def update_sidebar_for_route(pathname, user_cache):
        import re

        logger.info(f"🔄 Updating sidebar for pathname: {pathname}")

        # Check if we're on a dashboard page
        dashboard_match = re.match(r"/dashboard/([a-f0-9]{24})", pathname)

        if dashboard_match:
            dashboard_id = dashboard_match.group(1)
            logger.info(f"📊 Dashboard route detected, ID: {dashboard_id}")

            # Return basic dashboard navigation with limited navlinks
            return [
                # Section-based navigation (default to overview tab) - using simple HTML links
                html.A(
                    dmc.Group(
                        [
                            DashIconify(icon="material-symbols:analytics", height=20),
                            html.Span(
                                "Metrics Overview",
                                style={
                                    "whiteSpace": "nowrap",
                                    "overflow": "hidden",
                                    "textOverflow": "ellipsis",
                                },
                            ),
                        ],
                        gap="sm",
                        wrap="nowrap",
                        style={"width": "100%"},
                    ),
                    href="#metrics-section",
                    style={
                        "textDecoration": "none",
                        "color": "var(--app-text-color, #000)",
                        "display": "block",
                        "padding": "8px 12px",
                        "borderRadius": "4px",
                        "transition": "background-color 0.2s",
                        "width": "100%",
                        "overflowX": "hidden",
                        "boxSizing": "border-box",
                    },
                ),
                html.A(
                    dmc.Group(
                        [
                            DashIconify(icon="material-symbols:bar-chart", height=20),
                            html.Span(
                                "Visualizations",
                                style={
                                    "whiteSpace": "nowrap",
                                    "overflow": "hidden",
                                    "textOverflow": "ellipsis",
                                },
                            ),
                        ],
                        gap="sm",
                        wrap="nowrap",
                        style={"width": "100%"},
                    ),
                    href="#charts-section",
                    style={
                        "textDecoration": "none",
                        "color": "var(--app-text-color, #000)",
                        "display": "block",
                        "padding": "8px 12px",
                        "borderRadius": "4px",
                        "transition": "background-color 0.2s",
                        "width": "100%",
                        "overflowX": "hidden",
                        "boxSizing": "border-box",
                    },
                ),
                dmc.Divider(style={"margin": "20px 10px"}),
                # Add NavLink button for edit mode - DISABLED
                # html.Div(
                #     dmc.Button(
                #         "➕ Add NavLink",
                #         id="add-navlink-btn-dashboard",
                #         variant="light",
                #         size="sm",
                #         color="green",
                #         fullWidth=True,
                #         leftSection=DashIconify(icon="material-symbols:add", height=16),
                #     ),
                #     id="add-navlink-container-dashboard",
                #     style={"display": "none", "margin": "10px 0"},  # Hidden by default
                # ),
                dmc.NavLink(
                    label="← All Projects",
                    leftSection=DashIconify(icon="material-symbols:arrow-back", height=20),
                    href="/projects",
                ),
            ]

        # Check if user is admin for admin link visibility
        is_admin = False
        if user_cache and isinstance(user_cache, dict) and "user" in user_cache:
            user_data = user_cache.get("user", {})
            is_admin = user_data.get("is_admin", False)

        # Return RNA-seq specific sidebar content for non-dashboard pages
        default_links = [
            dmc.NavLink(
                label="RNA-seq Projects",
                leftSection=DashIconify(icon="material-symbols:biotech", height=20),
                href="/projects",
                active=pathname == "/projects",
            ),
            dmc.NavLink(
                label="Data Management",
                leftSection=DashIconify(icon="material-symbols:storage", height=20),
                childrenOffset=28,
                children=[
                    dmc.NavLink(
                        label="Raw Data",
                        href="/data/raw",
                        active=pathname == "/data/raw",
                    ),
                    dmc.NavLink(
                        label="Processed Data",
                        href="/data/processed",
                        active=pathname == "/data/processed",
                    ),
                ],
            ),
            dmc.NavLink(
                label="Analysis Tools",
                leftSection=DashIconify(icon="material-symbols:science", height=20),
                childrenOffset=28,
                children=[
                    dmc.NavLink(
                        label="Gene Set Enrichment",
                        href="/tools/gsea",
                        active=pathname == "/tools/gsea",
                    ),
                    dmc.NavLink(
                        label="Pathway Analysis",
                        href="/tools/pathways",
                        active=pathname == "/tools/pathways",
                    ),
                ],
            ),
        ]

        # Add admin link if user is admin with nested options
        if is_admin:
            default_links.append(
                dmc.NavLink(
                    label="Administration",
                    leftSection=DashIconify(
                        icon="material-symbols:admin-panel-settings", height=20
                    ),
                    childrenOffset=28,
                    children=[
                        dmc.NavLink(
                            label="Users",
                            href="/admin/users",
                            active=pathname == "/admin/users",
                        ),
                        dmc.NavLink(
                            label="Settings",
                            href="/admin/settings",
                            active=pathname == "/admin/settings",
                        ),
                    ],
                )
            )

        # Add about link
        default_links.append(
            dmc.NavLink(
                label="About",
                leftSection=DashIconify(icon="mingcute:question-line", height=20),
                href="/about",
                active=pathname == "/about",
            )
        )

        return default_links

    # NEW: Tab-based sidebar content callback for dynamic navigation
    @app.callback(
        Output("sidebar-content", "children", allow_duplicate=True),
        [Input("rnaseq-tabs", "value"), Input("url", "pathname")],
        prevent_initial_call=True,
        suppress_callback_exceptions=True,  # Suppress exceptions for missing components
    )
    def update_sidebar_for_tab(tab_value, pathname):
        import re

        from dash import no_update

        # Handle None or missing values
        if not pathname:
            logger.warning("🔄 Tab sidebar update: No pathname provided")
            return no_update

        logger.info(f"🔄 Tab sidebar update: tab={tab_value}, pathname={pathname}")

        # Check if we're on a dashboard page
        dashboard_match = re.match(r"/dashboard/([a-f0-9]{24})", pathname)

        if not dashboard_match:
            logger.info("❌ Not a dashboard route, keeping existing sidebar")
            return no_update

        dashboard_id = dashboard_match.group(1)

        # Handle case where tabs component doesn't exist yet
        if tab_value is None:
            logger.info(
                f"📊 Dashboard route detected, ID: {dashboard_id}, Tab: None (component not ready)"
            )
            # Use default tab when tabs component isn't ready
            tab_value = "overview"
        else:
            logger.info(f"📊 Dashboard route detected, ID: {dashboard_id}, Tab: {tab_value}")

        # Return tab-specific navlinks
        tab_navlinks = get_tab_specific_navlinks(tab_value, dashboard_id)
        logger.info(f"✅ Generated {len(tab_navlinks)} tab-specific navlinks for {tab_value}")

        return tab_navlinks

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

    # DMC navbar toggle callback (left sidebar - main navigation)
    @app.callback(
        Output("app-shell", "navbar"),
        Input("burger-menu", "opened"),
        State("app-shell", "navbar"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def toggle_navbar(opened, navbar, pathname):
        logger.info(f"🍔 Burger menu toggled: opened={opened}, pathname={pathname}")

        # Don't update on auth page
        if pathname == "/auth":
            return None

        if navbar is None:
            navbar = {
                "width": 250,  # Standard width for main navigation
                "breakpoint": "sm",
                "collapsed": {"mobile": True, "desktop": False},
            }

        # Toggle collapsed state
        navbar["collapsed"] = {"mobile": not opened, "desktop": not opened}
        return navbar

    # Initial navbar setup based on URL
    @app.callback(
        Output("app-shell", "navbar", allow_duplicate=True),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )
    def setup_navbar_on_route_change(pathname):
        logger.info(f"🔧 Setting up navbar for pathname: {pathname}")

        # Hide navbar on auth page
        if pathname == "/auth":
            return None

        # Default navbar configuration
        return {
            "width": 250,  # Standard width for main navigation
            "breakpoint": "sm",
            "collapsed": {"mobile": True, "desktop": False},
        }

    # Dashboard aside setup and toggle (right side - dashboard features)
    @app.callback(
        Output("app-shell", "aside"),
        Input("aside-toggle-btn", "n_clicks"),
        Input("url", "pathname"),
        State("app-shell", "aside"),
        prevent_initial_call=True,
        suppress_callback_exceptions=True,  # Suppress exceptions for missing components
    )
    def setup_and_toggle_aside(n_clicks, pathname, aside):
        import re

        from dash import ctx

        logger.info(f"📄 Setting up aside for pathname: {pathname}, clicks: {n_clicks}")

        # Hide aside on auth page or non-dashboard pages
        if pathname == "/auth":
            return None

        # Check if we're on a dashboard page
        dashboard_match = re.match(r"/dashboard/([a-f0-9]{24})", pathname)
        if not dashboard_match:
            return None  # No aside for non-dashboard pages

        # Default aside configuration for dashboard pages
        if aside is None:
            aside = {
                "width": 300,
                "breakpoint": "sm",
                "collapsed": {"mobile": True, "desktop": True},  # Start collapsed
            }

        # If toggle button was clicked, toggle the aside
        if ctx.triggered_id == "aside-toggle-btn" and n_clicks:
            current_collapsed = aside.get("collapsed", {}).get("desktop", True)
            aside["collapsed"] = {"mobile": True, "desktop": not current_collapsed}

        return aside

    # Dashboard aside content callback
    @app.callback(
        Output("dashboard-aside", "children"),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )
    def update_aside_content(pathname):
        import re

        # Check if we're on a dashboard page
        dashboard_match = re.match(r"/dashboard/([a-f0-9]{24})", pathname)
        if not dashboard_match:
            return []  # No content for non-dashboard pages

        dashboard_id = dashboard_match.group(1)
        logger.info(f"📄 Updating aside content for dashboard: {dashboard_id}")

        # Dashboard features content for the aside (right panel)
        return [
            dmc.Stack(
                [
                    # Header
                    dmc.Group(
                        [
                            dmc.Text(
                                "Dashboard Tools",
                                size="lg",
                                fw="bold",
                                style={"fontSize": "16px"},
                            ),
                        ],
                        justify="center",
                        style={"padding": "16px 16px 8px 16px"},
                    ),
                    dmc.Divider(),
                    # Dashboard features
                    dmc.Stack(
                        [
                            dmc.NavLink(
                                label="Add Component",
                                leftSection=DashIconify(icon="material-symbols:add-box", height=18),
                                id="add-component-sidebar-btn",
                                style={"padding": "12px"},
                            ),
                            dmc.NavLink(
                                label="Dashboard Settings",
                                leftSection=DashIconify(
                                    icon="material-symbols:settings", height=18
                                ),
                                href=f"/dashboard/{dashboard_id}/settings",
                                style={"padding": "12px"},
                            ),
                        ],
                        gap="xs",
                        style={"padding": "0 8px"},
                    ),
                ],
                gap="sm",
                style={"height": "100%"},
            )
        ]

    # NOTE: Sidebar active state is now handled in update_sidebar_for_route callback
    # which dynamically updates the entire sidebar content based on the route
    # app.clientside_callback(
    #     """
    #     function(pathname) {
    #         console.log('🔧 CLIENTSIDE SIDEBAR ACTIVE: pathname=' + pathname);
    #
    #         if (pathname === '/dashboards') {
    #             return [true, false, false, false];
    #         } else if (pathname === '/projects') {
    #             return [false, true, false, false];
    #         } else if (pathname === '/admin') {
    #             return [false, false, true, false];
    #         } else if (pathname === '/about') {
    #             return [false, false, false, true];
    #         } else {
    #             return [false, false, false, false];
    #         }
    #     }
    #     """,
    #     Output({"type": "sidebar-link", "index": ALL}, "active"),
    #     Input("url", "pathname"),
    #     prevent_initial_call=True,
    # )

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
    # Custom app branding section at the top
    app_branding_section = html.Div(
        [
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon="material-symbols:analytics", height=24),
                        size="lg",
                        radius="md",
                        variant="gradient",
                        gradient={"from": "blue", "to": "cyan"},
                    ),
                    dmc.Stack(
                        [
                            dmc.Text(
                                "DataViz Pro",
                                size="lg",
                                fw="bold",
                                style={"fontSize": "18px", "lineHeight": "1.2"},
                            ),
                            dmc.Text(
                                "Analytics Dashboard",
                                size="xs",
                                c="gray",
                                style={
                                    "fontSize": "12px",
                                    "lineHeight": "1.0",
                                    "marginTop": "-2px",
                                },
                            ),
                        ],
                        gap="xs",
                    ),
                ],
                align="center",
                gap="sm",
            ),
        ],
        style={
            "padding": "16px",
            "borderBottom": "1px solid var(--app-border-color, #dee2e6)",
        },
    )

    # Main navigation links - will be dynamically populated with ScrollArea
    sidebar_links = dmc.ScrollArea(
        html.Div(
            id="sidebar-content",
            children=[],  # Will be populated by callback
            style={
                "padding": "8px",
            },
        ),
        style={
            "flex": "1",
            "height": "100%",
        },
        type="scroll",
    )

    # Footer with theme controls, server status, and Depictio attribution
    sidebar_footer = html.Div(
        id="sidebar-footer",
        children=[
            dmc.Divider(style={"margin": "10px 0"}),
            dmc.Center(create_theme_controls()),
            dmc.Grid(
                id="sidebar-footer-server-status",
                align="center",
                justify="center",
                style={"marginTop": "10px"},
            ),
            # Depictio attribution at the bottom
            dmc.Group(
                [
                    dmc.Text(
                        "Powered by",
                        size="xs",
                        c="gray",
                        style={"fontSize": "10px"},
                    ),
                    dcc.Link(
                        html.Img(
                            src=dash.get_asset_url("images/logos/logo_black.svg"),
                            height=16,
                            style={"opacity": "0.7"},
                        ),
                        href="https://depictio.com",
                        target="_blank",
                    ),
                ],
                align="center",
                justify="center",
                gap="xs",
                style={"padding": "16px 8px 8px 8px"},
            ),
        ],
        style={
            "flexShrink": 0,
            "borderTop": "1px solid var(--app-border-color, #dee2e6)",
        },
    )

    # Main navbar container
    navbar = dmc.Container(
        p=0,  # Remove padding to use full width
        id="sidebar",
        style={
            "width": "250px",
            "height": "100vh",
            "display": "flex",
            "flexDirection": "column",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "borderRight": "1px solid var(--app-border-color, #dee2e6)",
            "transition": "all 0.3s ease",
        },
        children=[app_branding_section, sidebar_links, sidebar_footer],
    )

    return navbar


def get_tab_specific_navlinks(tab_value, dashboard_id):
    """Get navlinks specific to the current tab"""

    if tab_value == "overview":
        return [
            html.A(
                dmc.Group(
                    [
                        DashIconify(icon="material-symbols:analytics", height=16),
                        html.Span(
                            "Metrics Overview",
                            style={
                                "whiteSpace": "nowrap",
                                "overflow": "hidden",
                                "textOverflow": "ellipsis",
                            },
                        ),
                    ],
                    gap="xs",
                    wrap="nowrap",
                    style={"width": "100%"},
                ),
                href="#metrics-section",
                style={
                    "textDecoration": "none",
                    "color": "var(--app-text-color)",
                    "display": "block",
                    "padding": "8px 0",
                    "borderRadius": "4px",
                    "width": "100%",
                    "overflowX": "hidden",
                    "boxSizing": "border-box",
                },
            ),
            html.Div(
                [
                    html.A(
                        dmc.Group(
                            [
                                DashIconify(icon="material-symbols:bar-chart", height=16),
                                html.Span(
                                    "Visualizations",
                                    style={
                                        "whiteSpace": "nowrap",
                                        "overflow": "hidden",
                                        "textOverflow": "ellipsis",
                                    },
                                ),
                            ],
                            gap="xs",
                            wrap="nowrap",
                            style={"width": "100%"},
                        ),
                        href="#charts-section",
                        style={
                            "textDecoration": "none",
                            "color": "var(--app-text-color)",
                            "display": "block",
                            "padding": "8px 0",
                            "borderRadius": "4px",
                            "width": "100%",
                            "overflowX": "hidden",
                            "boxSizing": "border-box",
                        },
                    ),
                    html.Div(
                        [
                            html.A(
                                dmc.Group(
                                    [
                                        DashIconify(
                                            icon="material-symbols:scatter-plot", height=14
                                        ),
                                        html.Span(
                                            "Gene Expression Scatter",
                                            style={
                                                "whiteSpace": "nowrap",
                                                "overflow": "hidden",
                                                "textOverflow": "ellipsis",
                                            },
                                        ),
                                    ],
                                    gap="xs",
                                    wrap="nowrap",
                                    style={"width": "100%"},
                                ),
                                href="#chart-0",
                                style={
                                    "textDecoration": "none",
                                    "color": "var(--app-text-color)",
                                    "display": "block",
                                    "padding": "4px 0 4px 16px",
                                    "fontSize": "0.9em",
                                    "width": "100%",
                                    "overflowX": "hidden",
                                    "boxSizing": "border-box",
                                },
                            ),
                            html.A(
                                dmc.Group(
                                    [
                                        DashIconify(icon="material-symbols:bar-chart", height=14),
                                        html.Span(
                                            "DEG Count by Sample Type",
                                            style={
                                                "whiteSpace": "nowrap",
                                                "overflow": "hidden",
                                                "textOverflow": "ellipsis",
                                            },
                                        ),
                                    ],
                                    gap="xs",
                                    wrap="nowrap",
                                    style={"width": "100%"},
                                ),
                                href="#chart-1",
                                style={
                                    "textDecoration": "none",
                                    "color": "var(--app-text-color)",
                                    "display": "block",
                                    "padding": "4px 0 4px 16px",
                                    "fontSize": "0.9em",
                                    "width": "100%",
                                    "overflowX": "hidden",
                                    "boxSizing": "border-box",
                                },
                            ),
                            html.A(
                                dmc.Group(
                                    [
                                        DashIconify(
                                            icon="material-symbols:candlestick-chart", height=14
                                        ),
                                        html.Span(
                                            "P-Value Distribution",
                                            style={
                                                "whiteSpace": "nowrap",
                                                "overflow": "hidden",
                                                "textOverflow": "ellipsis",
                                            },
                                        ),
                                    ],
                                    gap="xs",
                                    wrap="nowrap",
                                    style={"width": "100%"},
                                ),
                                href="#chart-2",
                                style={
                                    "textDecoration": "none",
                                    "color": "var(--app-text-color)",
                                    "display": "block",
                                    "padding": "4px 0 4px 16px",
                                    "fontSize": "0.9em",
                                    "width": "100%",
                                    "overflowX": "hidden",
                                    "boxSizing": "border-box",
                                },
                            ),
                            html.A(
                                dmc.Group(
                                    [
                                        DashIconify(icon="material-symbols:show-chart", height=14),
                                        html.Span(
                                            "Fold Change Timeline",
                                            style={
                                                "whiteSpace": "nowrap",
                                                "overflow": "hidden",
                                                "textOverflow": "ellipsis",
                                            },
                                        ),
                                    ],
                                    gap="xs",
                                    wrap="nowrap",
                                    style={"width": "100%"},
                                ),
                                href="#chart-3",
                                style={
                                    "textDecoration": "none",
                                    "color": "var(--app-text-color)",
                                    "display": "block",
                                    "padding": "4px 0 4px 16px",
                                    "fontSize": "0.9em",
                                    "width": "100%",
                                    "overflowX": "hidden",
                                    "boxSizing": "border-box",
                                },
                            ),
                        ],
                        style={
                            "marginLeft": "4px",
                            "borderLeft": "2px solid var(--app-border-color, #ddd)",
                            "paddingLeft": "4px",
                            "overflowX": "hidden",
                        },
                    ),
                ]
            ),
        ]
    elif tab_value == "analysis":
        return [
            html.A(
                dmc.Group(
                    [
                        DashIconify(icon="material-symbols:analytics", height=16),
                        html.Span(
                            "Metrics Overview",
                            style={
                                "whiteSpace": "nowrap",
                                "overflow": "hidden",
                                "textOverflow": "ellipsis",
                            },
                        ),
                    ],
                    gap="xs",
                    wrap="nowrap",
                    style={"width": "100%"},
                ),
                href="#metrics-section",
                style={
                    "width": "100%",
                    "overflowX": "hidden",
                    "boxSizing": "border-box",
                    "display": "block",
                    "textDecoration": "none",
                    "padding": "8px 0",
                    "borderRadius": "4px",
                },
            ),
            html.A(
                dmc.Group(
                    [
                        DashIconify(icon="material-symbols:bar-chart", height=16),
                        html.Span(
                            "Visualizations",
                            style={
                                "whiteSpace": "nowrap",
                                "overflow": "hidden",
                                "textOverflow": "ellipsis",
                            },
                        ),
                    ],
                    gap="xs",
                    wrap="nowrap",
                    style={"width": "100%"},
                ),
                href="#charts-section",
                style={
                    "width": "100%",
                    "overflowX": "hidden",
                    "boxSizing": "border-box",
                    "display": "block",
                    "textDecoration": "none",
                    "padding": "8px 0",
                    "borderRadius": "4px",
                },
            ),
        ]
    else:
        # Default overview navlinks
        return get_tab_specific_navlinks("overview", dashboard_id)


def render_sidebar_content(email, current_tab="overview"):
    """Render just the navbar content for use in AppShellNavbar"""
    # Custom app branding for RNA-seq analysis
    app_branding = dmc.Group(
        [
            dmc.ThemeIcon(
                DashIconify(icon="material-symbols:biotech", height=24),
                size="lg",
                radius="md",
                variant="gradient",
                gradient={"from": "green", "to": "teal"},
            ),
            dmc.Stack(
                [
                    dmc.Text(
                        "RNAseq Studio app",  # RNA-seq app name
                        size="lg",
                        fw="bold",
                        style={"fontSize": "18px", "lineHeight": "1.2"},
                    ),
                    dmc.Text(
                        "Gene Expression Analysis",  # RNA-seq subtitle
                        size="xs",
                        c="gray",
                        style={"fontSize": "12px", "lineHeight": "1.0", "marginTop": "-2px"},
                    ),
                ],
                gap="xs",
            ),
        ],
        align="center",
        gap="sm",
        style={"padding": "12px 0"},
    )

    # Depictio attribution at the bottom
    depictio_attribution = dmc.Group(
        [
            dmc.Text(
                "Powered by",
                size="xs",
                c="gray",
                style={"fontSize": "10px"},
            ),
            dcc.Link(
                html.Img(
                    src=dash.get_asset_url("images/logos/logo_black.svg"),
                    height=16,
                    style={"opacity": "0.7"},
                ),
                href="https://depictio.com",
                target="_blank",
            ),
        ],
        align="center",
        justify="center",
        gap="xs",
        style={"padding": "8px"},
    )

    # Extract dashboard_id from current URL for tab-specific navigation
    # For now, use a placeholder - this will be updated by callback
    dashboard_id = "placeholder"

    # Get tab-specific navlinks (will be updated dynamically)
    tab_navlinks = get_tab_specific_navlinks(current_tab, dashboard_id)

    sidebar_links = html.Div(
        id="sidebar-content",
        children=tab_navlinks,
        style={
            "whiteSpace": "nowrap",
            "flex": "1",  # Take available space in Stack
            "overflowY": "auto",
            "padding": "4px 0",
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
            # Depictio attribution moved to bottom
            depictio_attribution,
        ],
        style={
            "flexShrink": 0,
        },
    )

    # Return content for AppShellNavbar - structured for full height
    return [
        dmc.Stack(
            [
                app_branding,  # Custom app branding at top
                sidebar_links,
                sidebar_footer,
            ],
            justify="space-between",
            h="100%",
            style={
                "padding": "16px",
                "height": "100%",
                "position": "relative",
            },
        ),
    ]
