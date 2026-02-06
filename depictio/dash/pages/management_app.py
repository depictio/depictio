"""
Management App for multi-app Depictio architecture.

This module provides the main management Dash app that handles authentication,
dashboard management, project management, user profile, admin panel, and
token management.

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

Functions:
    create_management_layout: Create the complete layout with AppShell
    layout: Module-level layout function for flask_dispatcher.py
    register_callbacks: Register all callbacks for the Management App
    register_routing_callback: Register main routing callback
    route_authenticated_user: Route authenticated users to appropriate pages
    register_layout_callbacks: Register core layout callbacks
    register_feature_callbacks: Register all feature-specific callbacks
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
from depictio.dash.layouts.users_management import create_auth_modal_components


def _create_management_additional_stores() -> list:
    """
    Create additional dcc.Store components specific to Management App.

    Returns:
        List of Dash components for analytics tracking, notifications,
        drawer modals, auth modal components, and hidden callback utility elements.
    """
    from depictio.api.v1.configs.config import settings

    stores = [
        create_analytics_tracker(),
        html.Div(id="theme-detection-trigger", style={"display": "none"}),
        dmc.NotificationContainer(id="notification-container"),
        dmc.Drawer(
            title="",
            id="drawer-simple",
            padding="md",
            zIndex=10000,
            size="xl",
            overlayProps={"overlayOpacity": 0.1},
            children=[],
        ),
        html.Div(id="dummy-plotly-output", style={"display": "none"}),
        html.Div(id="dummy-resize-output", style={"display": "none"}),
        html.Div(id="admin-password-warning-trigger", style={"display": "none"}),
    ]

    # Add auth-modal components for callback support across all pages
    stores.extend(create_auth_modal_components())

    # Add floating tour guide for demo mode
    if settings.auth.is_demo_mode:
        from depictio.dash.components.demo_tour import create_floating_tour_guide

        stores.append(create_floating_tour_guide())

    return stores


def create_management_layout():
    """
    Create layout for Management App.

    Creates the complete layout including the AppShell structure with header,
    sidebar, main content area, notification containers, and hidden utility
    components for clientside callbacks.

    Returns:
        dmc.MantineProvider: Complete layout with AppShell, stores, and routing.
    """
    main_content = html.Div(id="page-content")
    additional_stores = _create_management_additional_stores()

    header_content = create_default_header("Depictio")
    sidebar_content = dmc.AppShellNavbar(  # type: ignore[unresolved-attribute]
        children=create_static_navbar_content(),
        id="app-shell-navbar-content",
    )

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

    No lazy-loading is used since we're using separate apps. Each app loads
    all its callbacks upfront for architecture simplicity and true isolation.

    The Management App includes approximately 70 callbacks covering:
        - Routing and authentication (1 callback)
        - Header and layout (8 callbacks)
        - Auth/login (5 callbacks)
        - Dashboards management (15 callbacks)
        - Projects management (12 callbacks)
        - Profile management (8 callbacks)
        - Admin panel (15 callbacks)
        - Tokens management (6 callbacks)

    Args:
        app: Dash application instance for the Management App.
    """

    # 1. Main routing callback
    register_routing_callback(app)

    # 2. Core layout callbacks
    register_layout_callbacks(app)

    # 2.5. Theme system callbacks
    from depictio.dash.simple_theme import register_simple_theme_system

    register_simple_theme_system(app)

    # 3. Feature-specific callbacks (all loaded upfront)
    register_feature_callbacks(app)


def register_routing_callback(app):
    """
    Register main routing callback for Management App.

    This callback handles authentication validation, token refresh, page routing
    based on pathname, and header updates based on the current page.

    Args:
        app: Dash application instance to register the callback on.
    """

    @app.callback(
        Output("page-content", "children"),
        Output("header-content", "children"),
        Output("url", "pathname"),
        Output("local-store", "data", allow_duplicate=True),
        # ✅ REMOVED: server-status-cache output (now handled by clientside callback in sidebar.py)
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
            tuple: (page_content, header, pathname, local_data)
        """

        # Extract theme
        theme = extract_theme_from_store(theme_store)

        # Validate authentication and refresh token if needed
        updated_local_data, is_authenticated, reason = validate_and_refresh_token(local_data)

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
            )

        # Route to appropriate page
        result = route_authenticated_user(pathname, updated_local_data, theme)

        # Handle case where user token is invalid/expired (user is None in route_authenticated_user)
        if result is None:
            logger.warning("User token invalid - redirecting to auth and clearing local data")
            header = create_default_header("Welcome to Depictio")
            content = create_users_management_layout()
            return (
                content,
                header,
                "/auth",
                {"logged_in": False, "access_token": None},
            )

        content, header = result
        return content, header, pathname, updated_local_data


def route_authenticated_user(
    pathname: str,
    local_data: dict,
    theme: str = "light",
):
    """
    Route authenticated users to appropriate pages.

    Determines the correct page content and header based on the URL pathname.
    Handles special routes like admin (requires admin privileges), project
    permissions, and data collections management.

    Args:
        pathname: URL pathname to route.
        local_data: User authentication data containing access token.
        theme: Current theme ('light' or 'dark'). Defaults to 'light'.

    Returns:
        tuple: A tuple of (page_content, header_content) components.
    """
    access_token = get_access_token_from_local_data(local_data)

    # Fetch user data (API call is cached)
    user = api_call_fetch_user_from_token(access_token)

    # Handle invalid/expired token - user will be None
    # Return None to signal caller to redirect to auth
    if user is None:
        logger.warning("Token validation failed - user is None, signaling auth redirect")
        return None

    # Check if user is anonymous
    is_anonymous = hasattr(user, "is_anonymous") and user.is_anonymous

    # Helper for default dashboards page
    def dashboards_page():
        create_button = return_create_dashboard_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Dashboards", create_button)
        content = create_dashboards_management_layout()
        return content, header

    # Route based on pathname
    if pathname == "/dashboards":
        return dashboards_page()

    if pathname == "/projects":
        create_button = return_create_project_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Projects", create_button)
        content = create_projects_layout()
        return content, header

    if pathname == "/profile":
        header = create_default_header("Profile")
        content = create_profile_layout()
        return content, header

    if pathname == "/admin":
        if not user.is_admin:
            logger.warning(f"Non-admin user {user.email} attempted to access /admin")
            return dashboards_page()

        header = create_admin_header("Admin")
        admin_content = html.Div(id="admin-management-content")
        return admin_content, header

    if pathname == "/cli_configs":
        header = create_default_header("Depictio-CLI configs Management")
        content = create_tokens_management_layout()
        return content, header

    if pathname == "/about":
        from depictio.dash.layouts.about import layout as about_layout

        header = create_default_header("About")
        return about_layout, header

    if pathname.startswith("/project/") and pathname.endswith("/permissions"):
        header = create_default_header("Project Permissions Manager")
        return projectwise_user_management_layout, header

    if pathname.startswith("/project/") and pathname.endswith("/data"):
        header = create_default_header("Project Data Collections Manager")
        return project_data_collections_layout, header

    if pathname == "/auth":
        # In public mode, allow anonymous users to access /auth to see sign-in options
        # (temp user, Google OAuth) for upgrading their session
        if is_anonymous:
            logger.info("Anonymous user accessing /auth - showing auth page with sign-in options")
            header = create_default_header("Sign In")
            content = create_users_management_layout()
            return content, header
        # Fully authenticated users don't need /auth, redirect to dashboards
        logger.info("Authenticated user accessing /auth, redirecting to /dashboards")
        return dashboards_page()

    # Fallback to dashboards for unrecognized routes
    logger.info(f"Unrecognized route {pathname}, redirecting to /dashboards")
    return dashboards_page()


def register_layout_callbacks(app):
    """
    Register core layout callbacks for Management App.

    Registers callbacks for header navigation, sidebar interactions, theme
    switching, and auth page body class management.

    Args:
        app: Dash application instance to register callbacks on.
    """

    # Register header callbacks (navigation, modals, etc.)
    from depictio.dash.layouts.header import register_callbacks_header

    register_callbacks_header(app)

    # Register sidebar callbacks (admin link, server status, avatar)
    # Note: register_tabs=False because management app uses static navbar without tabs
    from depictio.dash.layouts.sidebar import register_sidebar_callbacks

    register_sidebar_callbacks(app, register_tabs=False)

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


def register_feature_callbacks(app):
    """
    Register all feature-specific callbacks for Management App.

    All callbacks are registered upfront (no lazy-loading) since we're using
    separate apps for true isolation. This function registers callbacks for:
        - Authentication (login, register, OAuth)
        - Dashboards management (CRUD operations, sharing)
        - Projects management (CRUD operations, permissions)
        - Profile management (settings, tokens)
        - Admin panel (users, groups, analytics)
        - Tokens management (CLI configs)
        - Project data collections management
        - Project permissions management

    Args:
        app: Dash application instance to register callbacks on.
    """

    # Auth callbacks
    from depictio.dash.layouts.users_management import register_callbacks_users_management

    register_callbacks_users_management(app)

    # Public mode auth modal callbacks
    from depictio.api.v1.configs.config import settings

    if settings.auth.is_public_mode:
        from depictio.dash.layouts.auth_modal import register_auth_modal_callbacks

        register_auth_modal_callbacks(app)

    # Demo mode guided tour callbacks
    logger.info(
        f"Demo mode check: is_demo_mode={settings.auth.is_demo_mode}, demo_mode={settings.auth.demo_mode}"
    )
    if settings.auth.is_demo_mode:
        from depictio.dash.layouts.demo_tour_callbacks import register_demo_tour_callbacks

        logger.info("Registering demo tour callbacks")
        register_demo_tour_callbacks(app)

    # Dashboards management callbacks
    from depictio.dash.layouts.dashboards_management import (
        register_callbacks_dashboards_management,
    )

    register_callbacks_dashboards_management(app)

    # Projects management callbacks
    from depictio.dash.layouts.projects import (
        register_projects_callbacks,
        register_workflows_callbacks,
    )

    register_projects_callbacks(app)
    register_workflows_callbacks(app)

    # Profile callbacks
    from depictio.dash.layouts.profile import register_profile_callbacks

    register_profile_callbacks(app)

    # Admin callbacks
    from depictio.dash.layouts.admin_management import register_admin_callbacks

    register_admin_callbacks(app)

    # Tokens management callbacks
    from depictio.dash.layouts.tokens_management import register_tokens_management_callbacks

    register_tokens_management_callbacks(app)

    # Project data collections callbacks
    from depictio.dash.layouts.project_data_collections import (
        register_project_data_collections_callbacks,
    )

    register_project_data_collections_callbacks(app)

    # Project permissions callbacks
    from depictio.dash.layouts.projectwise_user_management import (
        register_projectwise_user_management_callbacks,
    )

    register_projectwise_user_management_callbacks(app)
