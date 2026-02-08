"""
Shared AppShell wrapper for multi-app Depictio architecture.

This module provides a reusable Mantine AppShell structure that can be
customized per-app with different header/sidebar content while maintaining
consistent layout, theme integration, and store management.

Usage:
    from depictio.dash.layouts.shared_app_shell import create_app_shell

    layout = create_app_shell(
        app_name="Management",
        main_content=my_content,
        header_content=my_header,  # Optional
        sidebar_content=my_sidebar,  # Optional
        show_sidebar=True,  # Optional
    )
"""

from typing import Any, Optional

import dash_mantine_components as dmc
from dash import dcc


def create_shared_stores():
    """
    Create shared dcc.Store components used across all apps.

    Two-cache architecture:
    1. Dashboard metadata (dashboard-init-data): Dashboard + component configs + permissions
    2. Project metadata (project-metadata-store): Project + delta_locations + column_specs

    Returns:
        list: List of dcc.Store components
    """
    from depictio.api.v1.configs.config import settings
    from depictio.dash.layouts.auth_modal import create_auth_sign_in_modal

    stores = [
        # Shared across apps (localStorage)
        dcc.Store(id="local-store", storage_type="local"),  # JWT tokens, user_id, logged_in
        dcc.Store(id="theme-store", storage_type="local"),  # Light/dark theme
        dcc.Store(
            id="sidebar-collapsed", storage_type="local", data=False
        ),  # Sidebar state (False = expanded)
        # Session storage (persists within browser session)
        dcc.Store(
            id="user-cache-store", storage_type="session"
        ),  # User data cache (populated by consolidated_api)
        dcc.Store(id="server-status-cache", storage_type="session"),  # Server status and version
        dcc.Store(
            id="project-metadata-store", storage_type="session"
        ),  # Project + delta_locations + column_specs (10-min cache)
        dcc.Store(
            id="dashboard-init-data", storage_type="session"
        ),  # Dashboard + component metadata + permissions
        # Theme relay for clientside callbacks
        dcc.Store(id="theme-relay-store", storage_type="memory"),
        # API base URL for clientside callbacks (populated on load)
        dcc.Store(id="api-base-url-store", storage_type="memory"),
        # Edit page context (populated only on component edit pages, but needed by design callbacks)
        dcc.Store(id="edit-page-context", storage_type="memory", data=None),
        # Screenshot debounce tracking (memory-based to reset per session)
        dcc.Store(
            id="screenshot-debounce-store", storage_type="memory", data={"last_screenshot": 0}
        ),
        # Real-time WebSocket stores
        dcc.Store(id="ws-message-store", storage_type="memory"),  # Incoming WebSocket messages
        dcc.Store(
            id="ws-connection-config",
            storage_type="memory",
            data={
                "enabled": True,
                "refresh_mode": "notification",  # "notification" or "auto-refresh"
                "paused": False,
            },
        ),
        dcc.Store(
            id="ws-pending-updates", storage_type="memory", data=False
        ),  # Pending update flag
        dcc.Store(
            id="ws-new-data-ids", storage_type="memory", data=[]
        ),  # IDs of newly arrived data
        # Demo tour state (localStorage for persistence across sessions)
        # No default data - let localStorage persist tour state across page loads.
        # The handle_tour_state callback initializes data on first visit.
        dcc.Store(
            id="demo-tour-store",
            storage_type="local",
        ),
        # URL location
        dcc.Location(id="url", refresh=False),
        # Server status check interval (30 seconds) - pure clientside implementation
        dcc.Interval(
            id="server-status-interval",
            interval=30 * 1000,  # 30 seconds in milliseconds
            n_intervals=0,
        ),
    ]

    # Add public auth modal if in public mode
    if settings.auth.is_public_mode:
        stores.append(create_auth_sign_in_modal())

    return stores


def create_default_header(app_name: str = "Depictio"):
    """
    Create a default header for apps that don't provide custom header.

    Args:
        app_name: Name of the app to display in header

    Returns:
        dmc.AppShellHeader: Default header component
    """
    return dmc.AppShellHeader(
        dmc.Group(
            [
                dmc.Text(
                    app_name,
                    size="lg",
                    fw="bold",
                    c="blue",
                    style={"fontFamily": "Virgil"},
                ),
            ],
            justify="space-between",
            p="md",
        ),
        withBorder=True,
    )


def create_default_sidebar():
    """
    Create a default sidebar (empty placeholder).

    Returns:
        dmc.AppShellNavbar: Default sidebar component
    """
    return dmc.AppShellNavbar(
        dmc.Stack(
            [
                dmc.Text("Sidebar", size="sm", c="gray", p="md"),
            ],
            gap="xs",
        ),
        withBorder=True,
    )


def create_app_shell(
    app_name: str,
    main_content: Any,
    header_content: Optional[Any] = None,
    sidebar_content: Optional[Any] = None,
    show_sidebar: bool = True,
    additional_stores: Optional[list] = None,
) -> dmc.MantineProvider:
    """
    Create a Mantine AppShell layout with customizable header and sidebar.

    This function provides a consistent AppShell structure across all Depictio apps
    while allowing each app to customize its header and sidebar content.

    Args:
        app_name: Name of the app (used in default header)
        main_content: Main page content to display in AppShell.main
        header_content: Custom header content (uses default if None)
        sidebar_content: Custom sidebar content (uses default if None)
        show_sidebar: Whether to show the sidebar (default: True)
        additional_stores: Additional dcc.Store components specific to this app

    Returns:
        dmc.MantineProvider: Complete layout with AppShell

    Example:
        >>> from depictio.dash.layouts.header import design_header
        >>> from depictio.dash.layouts.sidebar import create_static_navbar_content
        >>>
        >>> layout = create_app_shell(
        ...     app_name="Management",
        ...     main_content=html.Div([...]),
        ...     header_content=design_header(),
        ...     sidebar_content=create_static_navbar_content(),
        ...     show_sidebar=True,
        ... )
    """
    # Create shared stores
    stores = create_shared_stores()

    # Add additional app-specific stores if provided
    if additional_stores:
        stores.extend(additional_stores)

    # Use custom header or default
    if header_content is not None:
        header = header_content
    else:
        header = create_default_header(app_name)

    # Use custom sidebar or default (only if show_sidebar is True)
    navbar = None
    if show_sidebar:
        if sidebar_content is not None:
            navbar = sidebar_content
        else:
            navbar = create_default_sidebar()

    # Create AppShell layout
    app_shell = dmc.AppShell(
        [
            # Header
            header,
            # Sidebar (if enabled)
            navbar,
            # Main content area
            dmc.AppShellMain(
                main_content,
                id="main-content",
            ),
        ],
        layout="alt",
        header={"height": 60},
        navbar={
            "width": 250,
            "breakpoint": "sm",
            "collapsed": {"mobile": True, "desktop": False},
        }
        if show_sidebar
        else None,
        padding="md",
    )

    # Wrap in MantineProvider for theme support
    return dmc.MantineProvider(
        [
            *stores,  # All dcc.Store components
            app_shell,  # The AppShell layout
        ],
        id="mantine-provider",
        forceColorScheme="light",  # Default, will be updated by theme callbacks
    )


def create_minimal_app_shell(
    app_name: str,
    main_content: Any,
    show_header: bool = True,
    additional_stores: Optional[list] = None,
) -> dmc.MantineProvider:
    """
    Create a minimal AppShell with dynamic header and sidebar for viewer/editor apps.

    Updated to support dynamic header population via callbacks and include sidebar navigation.

    Args:
        app_name: Name of the app
        main_content: Main page content
        show_header: Whether to show the header (default: True)
        additional_stores: Additional app-specific stores

    Returns:
        dmc.MantineProvider: Layout with dynamic header and sidebar

    Example:
        >>> layout = create_minimal_app_shell(
        ...     app_name="Dashboard Viewer",
        ...     main_content=dashboard_content,
        ...     show_header=True,
        ... )
    """
    # Import dashboard viewer sidebar (tabs only, no navigation links)
    from depictio.dash.components.realtime_websocket import create_websocket_component
    from depictio.dash.layouts.sidebar import create_dashboard_viewer_sidebar
    from depictio.dash.layouts.tab_modal import create_tab_modal

    # Create shared stores
    stores = create_shared_stores()

    # Add WebSocket component for real-time updates
    stores.append(create_websocket_component("ws"))

    # Add additional app-specific stores if provided
    if additional_stores:
        stores.extend(additional_stores)

    # Create dynamic header (empty, will be populated by callback)
    if show_header:
        header = dmc.AppShellHeader(
            children=[],  # Will be populated by routing callback
            id="header-content",
        )
    else:
        header = None

    # Create sidebar with workflow tabs only (no navigation links for viewer)
    navbar = dmc.AppShellNavbar(
        children=create_dashboard_viewer_sidebar(),
        id="app-shell-navbar-content",
    )

    # AppShell with header and sidebar
    app_shell = dmc.AppShell(
        id="app-shell",
        layout="alt",
        navbar={
            "width": 220,
            "breakpoint": "sm",
            "collapsed": {"mobile": True, "desktop": False},
        },
        header={"height": 65, "padding": "0"} if show_header else None,
        # styles={
        #     "root": {"overflow": "hidden"},  # Prevent AppShell root scrolling
        # },
        style={
            "height": "100vh",
        },
        children=[
            navbar,
            header,
            dmc.AppShellMain(
                main_content,
                id="main-content",
            ),
        ],
    )

    # Wrap in MantineProvider
    return dmc.MantineProvider(
        [
            *stores,
            create_tab_modal(),  # Add tab creation modal for editor functionality
            app_shell,
        ],
        id="mantine-provider",
        forceColorScheme="light",
    )


# Utility function for creating dashboard-specific layouts
def create_dashboard_layout(
    main_content: Any,
    dashboard_name: Optional[str] = None,
    additional_stores: Optional[list] = None,
) -> dmc.MantineProvider:
    """
    Create a dashboard-specific layout (viewer or editor).

    This is optimized for dashboard apps with minimal chrome and
    focus on content.

    Args:
        main_content: Dashboard content
        dashboard_name: Name of dashboard (for header)
        additional_stores: Additional dashboard-specific stores

    Returns:
        dmc.MantineProvider: Dashboard layout
    """
    app_name = f"Dashboard: {dashboard_name}" if dashboard_name else "Dashboard"

    return create_minimal_app_shell(
        app_name=app_name,
        main_content=main_content,
        show_header=True,
        additional_stores=additional_stores,
    )
