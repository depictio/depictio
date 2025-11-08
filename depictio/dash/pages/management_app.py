"""
Management App for multi-app Depictio architecture.

This module provides the main management Dash app that handles:
- Authentication (/auth)
- Dashboard management (/dashboards)
- Project management (/projects)
- User profile (/profile)
- Admin panel (/admin)
- Token management (/cli_configs)
- About page (/about)
- Project-specific pages (/project/{id}/permissions, /project/{id}/data)

Routes:
    / - Redirects to /dashboards
    /auth - Login/register
    /dashboards - Dashboard listing and management
    /projects - Project listing and management
    /profile - User profile
    /admin - Admin panel (admin only)
    /cli_configs - Token management
    /about - About page
    /project/{id}/permissions - Project permissions management
    /project/{id}/data - Project data collections management
"""

import dash_mantine_components as dmc
from dash import Input, Output, State, html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token
from depictio.dash.components.analytics_tracker import create_analytics_tracker
from depictio.dash.core.shared_auth import (
    extract_theme_from_store,
    get_access_token_from_local_data,
    should_redirect_to_dashboards,
    validate_and_refresh_token,
)
from depictio.dash.layouts.app_layout import (
    create_admin_header,
    create_dashboards_management_layout,
    create_default_header,
    create_header_with_button,
    create_profile_layout,
    create_projects_layout,
    create_tokens_management_layout,
    create_users_management_layout,
    return_create_dashboard_button,
    return_create_project_button,
)
from depictio.dash.layouts.project_data_collections import (
    layout as project_data_collections_layout,
)
from depictio.dash.layouts.projectwise_user_management import (
    layout as projectwise_user_management_layout,
)
from depictio.dash.layouts.shared_app_shell import create_app_shell
from depictio.dash.layouts.sidebar import create_static_navbar_content


def create_management_layout():
    """
    Create layout for Management App.

    Returns:
        dmc.MantineProvider: Complete layout with AppShell, stores, and routing
    """
    # Create main content placeholder
    main_content = html.Div(id="page-content")

    # Create additional stores specific to Management App
    # Note: project-cache and theme-relay-store are already in create_shared_stores()
    additional_stores = [
        # Analytics tracking
        create_analytics_tracker(),
        # Theme detection trigger
        html.Div(id="theme-detection-trigger", style={"display": "none"}),
        # Admin notifications
        dmc.NotificationContainer(id="notification-container"),
        # Drawer for modals
        dmc.Drawer(
            title="",
            id="drawer-simple",
            padding="md",
            zIndex=10000,
            size="xl",
            overlayProps={"overlayOpacity": 0.1},
            children=[],
        ),
        # Hidden output divs for clientside callbacks
        html.Div(id="dummy-plotly-output", style={"display": "none"}),
        html.Div(id="dummy-resize-output", style={"display": "none"}),
        html.Div(id="admin-password-warning-trigger", style={"display": "none"}),
    ]

    # Get header and sidebar from existing modules
    # Note: Header content will be set dynamically by routing callback
    header_content = create_default_header("Depictio")
    sidebar_content = dmc.AppShellNavbar(  # type: ignore[unresolved-attribute]
        children=create_static_navbar_content(),
        id="app-shell-navbar-content",
    )

    # Create AppShell layout
    layout = create_app_shell(
        app_name="Depictio - Management",
        main_content=main_content,
        header_content=dmc.AppShellHeader(  # type: ignore[unresolved-attribute]
            children=header_content, id="header-content"
        ),
        sidebar_content=sidebar_content,
        show_sidebar=True,
        additional_stores=additional_stores,
    )

    return layout


# Module-level layout function for flask_dispatcher.py
# IMPORTANT: Must be a function, not a layout instance, because dash.get_asset_url()
# requires a Dash app context which doesn't exist during module import
def layout():
    """Return layout for Management App (called by Dash after app creation)."""
    return create_management_layout()


def register_callbacks(app):
    """
    Register all callbacks for Management App.

    NO LAZY-LOADING: Since we're using separate apps, each app loads all its
    callbacks upfront. This simplifies architecture and provides true isolation.

    Management app includes (~70 callbacks):
    - Routing and authentication (1 callback)
    - Header and layout (8 callbacks)
    - Auth/login (5 callbacks)
    - Dashboards management (15 callbacks)
    - Projects management (12 callbacks)
    - Profile management (8 callbacks)
    - Admin panel (15 callbacks)
    - Tokens management (6 callbacks)

    Args:
        app (dash.Dash): Management app instance
    """
    logger.info("🔥 MANAGEMENT APP: Registering all callbacks upfront")

    # 1. Main routing callback
    register_routing_callback(app)

    # 2. Core layout callbacks
    register_layout_callbacks(app)

    # 2.5. Theme system callbacks
    from depictio.dash.simple_theme import register_simple_theme_system

    logger.info("  🎨 Registering theme system callbacks")
    register_simple_theme_system(app)

    # 3. Feature-specific callbacks (all loaded upfront)
    register_feature_callbacks(app)

    logger.info("✅ MANAGEMENT APP: All callbacks registered (~70 callbacks)")


def register_routing_callback(app):
    """
    Register main routing callback for Management App.

    Handles:
    - Authentication validation and token refresh
    - Page routing based on pathname
    - Header updates based on current page
    """
    logger.info("  📋 Registering main routing callback")

    @app.callback(
        Output("page-content", "children"),
        Output("header-content", "children"),
        Output("url", "pathname"),
        Output("local-store", "data", allow_duplicate=True),
        Output("server-status-cache", "data"),
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
            State("theme-store", "data"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def route_page(pathname, local_data, theme_store):
        """
        Main routing callback for Management App.

        Args:
            pathname: Current URL pathname
            local_data: Local storage data (auth tokens)
            theme_store: Theme store data (light/dark)

        Returns:
            tuple: (page_content, header, pathname, local_data, server_status_cache)
        """
        logger.info(f"🔄 MANAGEMENT ROUTING: pathname={pathname}")

        # Prepare server status cache data
        from depictio.version import get_version

        try:
            depictio_version = get_version()
        except Exception as e:
            logger.warning(f"Failed to get version: {e}")
            depictio_version = "unknown"

        server_status_cache = {"status": "online", "version": depictio_version}

        # Extract theme
        theme = extract_theme_from_store(theme_store)

        # Validate authentication and refresh token if needed
        updated_local_data, is_authenticated, reason = validate_and_refresh_token(local_data)

        logger.info(f"🔐 AUTH STATUS: is_authenticated={is_authenticated}, reason={reason}")

        # Handle unauthenticated users
        if not is_authenticated:
            logger.info("Redirecting to /auth - user not authenticated")
            header = create_default_header("Welcome to Depictio")
            content = create_users_management_layout()
            return (
                content,
                header,
                "/auth",
                {"logged_in": False, "access_token": None},
                server_status_cache,
            )

        # Redirect root path to /dashboards
        if should_redirect_to_dashboards(pathname):
            logger.info("Redirecting / to /dashboards")
            pathname = "/dashboards"

        # Type guard: validate_and_refresh_token guarantees non-None when is_authenticated=True
        # But add defensive check for type safety
        if not updated_local_data:
            logger.error("Auth validation returned None for authenticated user - forcing logout")
            header = create_default_header("Welcome to Depictio")
            content = create_users_management_layout()
            return (
                content,
                header,
                "/auth",
                {"logged_in": False, "access_token": None},
                server_status_cache,
            )

        # Route to appropriate page
        content, header = route_authenticated_user(pathname, updated_local_data, theme)

        return content, header, pathname, updated_local_data, server_status_cache


def route_authenticated_user(
    pathname: str,
    local_data: dict,
    theme: str = "light",
):
    """
    Route authenticated users to appropriate pages.

    Args:
        pathname: URL pathname
        local_data: User authentication data
        theme: Current theme (light/dark)

    Returns:
        tuple: (page_content, header_content)
    """
    access_token = get_access_token_from_local_data(local_data)

    # Fetch user data (API call is cached)
    user = api_call_fetch_user_from_token(access_token)

    # Check if user is anonymous
    is_anonymous = hasattr(user, "is_anonymous") and user.is_anonymous

    # Route based on pathname
    if pathname == "/dashboards":
        create_button = return_create_dashboard_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Dashboards", create_button)
        content = create_dashboards_management_layout()
        return content, header

    elif pathname == "/projects":
        create_button = return_create_project_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Projects", create_button)
        content = create_projects_layout()
        return content, header

    elif pathname == "/profile":
        header = create_default_header("Profile")
        content = create_profile_layout()
        return content, header

    elif pathname == "/admin":
        # Check if user is admin
        if not user.is_admin:
            # Redirect non-admin users to dashboards
            logger.warning(f"Non-admin user {user.email} attempted to access /admin")
            create_button = return_create_dashboard_button(user.email, is_anonymous=is_anonymous)
            header = create_header_with_button("Dashboards", create_button)
            content = create_dashboards_management_layout()
            return content, header

        header = create_admin_header("Admin")
        admin_content = html.Div(id="admin-management-content")
        return admin_content, header

    elif pathname == "/cli_configs":
        header = create_default_header("Depictio-CLI configs Management")
        content = create_tokens_management_layout()
        return content, header

    elif pathname == "/about":
        from depictio.dash.layouts.about import layout as about_layout

        header = create_default_header("About")
        return about_layout, header

    elif pathname.startswith("/project/") and pathname.endswith("/permissions"):
        header = create_default_header("Project Permissions Manager")
        return projectwise_user_management_layout, header

    elif pathname.startswith("/project/") and pathname.endswith("/data"):
        header = create_default_header("Project Data Collections Manager")
        return project_data_collections_layout, header

    elif pathname == "/auth":
        # Already authenticated, redirect to dashboards
        logger.info("Authenticated user accessing /auth, redirecting to /dashboards")
        create_button = return_create_dashboard_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Dashboards", create_button)
        content = create_dashboards_management_layout()
        return content, header

    else:
        # Fallback to dashboards for unrecognized routes
        logger.info(f"Unrecognized route {pathname}, redirecting to /dashboards")
        create_button = return_create_dashboard_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Dashboards", create_button)
        content = create_dashboards_management_layout()
        return content, header


def register_layout_callbacks(app):
    """
    Register core layout callbacks for Management App.

    Includes:
    - Header navigation and interactions
    - Sidebar burger menu (if needed)
    - Theme switching clientside callbacks
    - Auth page body class management

    Args:
        app: Dash app instance
    """
    logger.info("  📋 Registering core layout callbacks")

    # Register header callbacks (navigation, modals, etc.)
    from depictio.dash.layouts.header import register_callbacks_header

    register_callbacks_header(app)

    # Register sidebar callbacks (admin link, server status, avatar)
    from depictio.dash.layouts.sidebar import register_sidebar_callbacks

    register_sidebar_callbacks(app)

    # Add clientside callback for auth page body class
    app.clientside_callback(
        """
        function(pathname) {
            const currentPath = pathname || window.location.pathname;

            setTimeout(() => {
                if (currentPath === '/auth') {
                    document.body.classList.add('auth-page');
                    document.body.classList.remove('page-loaded');
                } else {
                    document.body.classList.remove('auth-page');
                    document.body.classList.add('page-loaded');
                }
            }, 50);
        }
        """,
        Input("url", "pathname"),
        prevent_initial_call="initial_duplicate",
    )

    logger.info("  ✅ Core layout callbacks registered")


def register_feature_callbacks(app):
    """
    Register all feature-specific callbacks for Management App.

    All callbacks are registered upfront (no lazy-loading) since we're using
    separate apps for true isolation.

    Includes:
    - Authentication (login, register, OAuth)
    - Dashboards management (CRUD operations, sharing)
    - Projects management (CRUD operations, permissions)
    - Profile management (settings, tokens)
    - Admin panel (users, groups, analytics)
    - Tokens management (CLI configs)

    Args:
        app: Dash app instance
    """
    logger.info("  📋 Registering feature-specific callbacks")

    # Auth callbacks
    logger.info("    🔐 Registering authentication callbacks")
    from depictio.dash.layouts.users_management import register_callbacks_users_management

    register_callbacks_users_management(app)

    # Dashboards management callbacks
    logger.info("    📊 Registering dashboards management callbacks")
    from depictio.dash.layouts.dashboards_management import (
        register_callbacks_dashboards_management,
    )

    register_callbacks_dashboards_management(app)

    # Projects management callbacks
    logger.info("    📁 Registering projects management callbacks")
    from depictio.dash.layouts.projects import (
        register_projects_callbacks,
        register_workflows_callbacks,
    )

    register_projects_callbacks(app)
    register_workflows_callbacks(app)

    # Profile callbacks
    logger.info("    👤 Registering profile callbacks")
    from depictio.dash.layouts.profile import register_profile_callbacks

    register_profile_callbacks(app)

    # Admin callbacks
    logger.info("    ⚙️  Registering admin callbacks")
    from depictio.dash.layouts.admin_management import register_admin_callbacks

    register_admin_callbacks(app)

    # Tokens management callbacks
    logger.info("    🔑 Registering tokens management callbacks")
    from depictio.dash.layouts.tokens_management import register_tokens_management_callbacks

    register_tokens_management_callbacks(app)

    logger.info("  ✅ All feature callbacks registered")
