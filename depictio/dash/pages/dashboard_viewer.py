"""
Dashboard Viewer App for multi-app Depictio architecture.

This module provides the read-only dashboard viewing Dash app that handles:
- Dashboard viewing (/dashboard/{id})
- Component rendering (cards, figures, interactive filters, tables)
- Real-time data updates via callbacks
- Theme switching

Routes:
    /dashboard/{id} - View dashboard (read-only)

Key Features:
    - Minimal AppShell (no sidebar, compact header)
    - Read-only mode (no edit buttons or save functionality)
    - Lightweight callback registry (~30 callbacks)
    - Shared localStorage for auth and theme
    - Component rendering with pattern-matching callbacks
"""

from typing import Optional

import dash_mantine_components as dmc
from dash import Input, Output, State, ctx, html, no_update

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.components.analytics_tracker import create_analytics_tracker
from depictio.dash.components.workflow_logo_overlay import create_workflow_logo_overlay
from depictio.dash.core.shared_auth import (
    extract_theme_from_store,
    validate_and_refresh_token,
)
from depictio.dash.layouts.draggable import design_draggable
from depictio.dash.layouts.draggable_scenarios.restore_dashboard import load_depictio_data_sync
from depictio.dash.layouts.header import design_header
from depictio.dash.layouts.shared_app_shell import create_minimal_app_shell


def create_viewer_layout():
    """
    Create layout for Dashboard Viewer App.

    Minimal AppShell without sidebar, optimized for dashboard viewing.

    Returns:
        dmc.MantineProvider: Complete layout with minimal AppShell and stores
    """
    # Create main content placeholder
    main_content = html.Div(
        id="page-content",
        style={
            "padding": "0",
            "minHeight": "calc(100vh - 60px)",
            "overflowY": "auto",
        },
    )

    # Create additional stores specific to Viewer App
    # Note: project-cache, theme-relay-store, and dashboard-init-data are already in create_shared_stores()
    additional_stores = [
        # Notification container for user feedback (filter updates, etc.)
        dmc.NotificationContainer(
            id="notification-container",
            position="bottom-right",
            zIndex=10000,
        ),
        # Analytics tracking
        create_analytics_tracker(),
        # Hidden output divs for clientside callbacks
        html.Div(id="dummy-plotly-output", style={"display": "none"}),
        html.Div(id="test-output", style={"display": "none"}),
    ]

    # Use minimal AppShell (no sidebar)
    layout = create_minimal_app_shell(
        app_name="Depictio - Dashboard Viewer",
        main_content=main_content,
        show_header=True,
        additional_stores=additional_stores,
    )

    return layout


# Module-level layout function for flask_dispatcher.py
# IMPORTANT: Must be a function, not a layout instance, because dash.get_asset_url()
# and other Dash functions require a Dash app context which doesn't exist during module import
def layout():
    """Return layout for Viewer App (called by Dash after app creation)."""
    return create_viewer_layout()


def register_callbacks(app):
    """
    Register all callbacks for Dashboard Viewer App.

    Viewer app includes (~30 callbacks):
    - Main routing callback (1)
    - Component rendering callbacks (20-25)
      - Card components
      - Figure components
      - Interactive filters
      - Table components
    - Header callbacks (minimal, 3-5)
    - Theme switching (clientside, 2)

    Args:
        app (dash.Dash): Viewer app instance
    """
    logger.info("🔥 VIEWER APP: Registering callbacks")

    # 1. Main routing callback
    register_routing_callback(app)

    # 1.5. Cache population callbacks (consolidated API)
    from depictio.dash.layouts.consolidated_api import register_consolidated_api_callbacks

    logger.info("  📦 Registering consolidated API cache population callbacks")
    register_consolidated_api_callbacks(app)

    # 2. Component rendering callbacks
    register_component_callbacks(app)

    # 2.5. Theme system callbacks
    from depictio.dash.simple_theme import register_simple_theme_system

    logger.info("  🎨 Registering theme system callbacks")
    register_simple_theme_system(app)

    # 3. Header callbacks (minimal)
    register_header_callbacks(app)

    logger.info("✅ VIEWER APP: All callbacks registered (~30 callbacks)")


def register_routing_callback(app):
    """
    Register main routing callback for Viewer App.

    Extracts dashboard ID from pathname and loads dashboard data.
    Handles authentication via shared localStorage.
    """
    logger.info("  📋 Registering main routing callback")

    @app.callback(
        Output("page-content", "children"),
        Output("header-content", "children"),
        Output("url", "pathname"),
        Output("local-store", "data", allow_duplicate=True),
        # ✅ REMOVED: server-status-cache output (now handled by consolidated_api callback)
        [
            Input("url", "pathname"),
        ],
        [
            State("local-store", "data"),
            State("theme-store", "data"),
            State("project-metadata-store", "data"),  # ✅ Fixed: renamed from project-cache
            State("dashboard-init-data", "data"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def route_dashboard(
        pathname,
        local_data,
        theme_store,
        cached_project_data,
        dashboard_init_data,
    ):
        """
        Main routing callback for Viewer App.

        Args:
            pathname: Current URL pathname (/dashboard/{id})
            local_data: Local storage data (auth tokens)
            theme_store: Theme store data (light/dark)
            cached_project_data: Cached project data from project-metadata-store
            dashboard_init_data: Dashboard initialization data

        Returns:
            tuple: (page_content, header_content, pathname, local_data)
        """
        logger.info(f"🔄 VIEWER ROUTING: pathname={pathname}")
        logger.info(f"   Triggered by: {ctx.triggered_id}")

        # CRITICAL FIX: When triggered by local-store update (not URL change),
        # don't update the pathname to prevent circular URL changes
        triggered_by_local_store = ctx.triggered_id == "local-store"

        if triggered_by_local_store:
            logger.info("   ⚠️ Triggered by local-store - will preserve current URL")

        # Extract theme
        theme = extract_theme_from_store(theme_store)

        # Validate authentication
        updated_local_data, is_authenticated, reason = validate_and_refresh_token(local_data)

        logger.info(f"🔐 AUTH STATUS: is_authenticated={is_authenticated}, reason={reason}")

        # Handle unauthenticated users - redirect to management app /auth
        if not is_authenticated:
            logger.info("User not authenticated - redirecting to /auth")
            # Return empty content and redirect pathname
            # User will be redirected to Management app by browser
            return (
                html.Div("Redirecting to login..."),
                html.Div(),  # Empty header
                "/auth",
                {"logged_in": False, "access_token": None},
            )

        # Type guard
        if not updated_local_data:
            logger.error("Auth validation returned None - forcing logout")
            return (
                html.Div("Authentication error - redirecting..."),
                html.Div(),  # Empty header
                "/auth",
                {"logged_in": False, "access_token": None},
            )

        # Extract dashboard ID from pathname
        dashboard_id = extract_dashboard_id(pathname)

        if not dashboard_id:
            logger.warning(f"Invalid pathname format: {pathname}")
            error_content = create_error_layout("Invalid dashboard URL")
            return error_content, html.Div(), pathname, updated_local_data

        # Load dashboard data
        logger.info(f"📊 Loading dashboard: {dashboard_id}")
        content, header_content = load_and_render_dashboard(
            dashboard_id=dashboard_id,
            local_data=updated_local_data,
            theme=theme,
            cached_project_data=cached_project_data,
            dashboard_init_data=dashboard_init_data,
        )

        # If triggered by local-store, preserve current URL
        if triggered_by_local_store:
            logger.info(
                "📤 VIEWER ROUTING RETURNING - pathname: no_update (preserving current URL)"
            )
            return content, header_content, no_update, updated_local_data

        logger.info(f"📤 VIEWER ROUTING RETURNING - pathname: {pathname}")
        return content, header_content, pathname, updated_local_data


def extract_dashboard_id(pathname: str) -> Optional[str]:
    """
    Extract dashboard ID from pathname.

    Args:
        pathname: URL pathname (/dashboard/{id})

    Returns:
        Dashboard ID or None if invalid format
    """
    if not pathname or not pathname.startswith("/dashboard/"):
        return None

    parts = pathname.strip("/").split("/")
    # parts: ['dashboard', '{id}']
    if len(parts) >= 2:
        return parts[1]

    return None


def load_and_render_dashboard(
    dashboard_id: str,
    local_data: dict,
    theme: str,
    cached_project_data: Optional[dict] = None,
    dashboard_init_data: Optional[dict] = None,
):
    """
    Load dashboard data and render components.

    Args:
        dashboard_id: Dashboard ID to load
        local_data: User authentication data
        theme: Current theme (light/dark)
        cached_project_data: Cached project data
        dashboard_init_data: Dashboard initialization data

    Returns:
        tuple: (dashboard_layout, header_content) - Dashboard layout and header content
    """
    # Load dashboard data
    depictio_dash_data = load_depictio_data_sync(
        dashboard_id=dashboard_id,
        local_data=local_data,
        theme=theme,
        init_data=dashboard_init_data,
    )

    if not depictio_dash_data:
        logger.error(f"Failed to load dashboard {dashboard_id}")
        return create_error_layout("Dashboard not found or you don't have access")

    # Create header (view-only, no edit buttons)
    header_content, backend_components = design_header(
        depictio_dash_data, local_data, edit_mode=False
    )

    # Extract layout and children data
    init_layout = depictio_dash_data.get("stored_layout_data", {})
    init_children = depictio_dash_data.get("stored_children_data", [])
    stored_metadata = depictio_dash_data.get("stored_metadata", [])
    # Extract dual-panel layout data
    left_panel_layout_data = depictio_dash_data.get("left_panel_layout_data", [])
    right_panel_layout_data = depictio_dash_data.get("right_panel_layout_data", [])

    # Render draggable layout (view-only)
    core = design_draggable(
        init_layout,
        init_children,
        dashboard_id,
        local_data,
        cached_project_data=cached_project_data,
        stored_metadata=stored_metadata,
        edit_mode=False,  # Read-only mode
        left_panel_layout_data=left_panel_layout_data,
        right_panel_layout_data=right_panel_layout_data,
    )

    # Create workflow logo overlay if project data available
    workflow_logo_overlay = html.Div()
    if cached_project_data and isinstance(cached_project_data, dict):
        project_data = cached_project_data.get("project")
        if project_data:
            workflow_logo_overlay = create_workflow_logo_overlay(project_data, theme)

    # Create dashboard layout
    dashboard_layout = dmc.Container(
        [
            # Backend components (Store components)
            backend_components if backend_components else html.Div(),
            # Draggable layout
            html.Div([core]),
            # Workflow logo overlay
            workflow_logo_overlay,
            # Hidden outputs
            html.Div(id="test-output", style={"display": "none"}),
        ],
        fluid=True,
        p=0,
        style={
            "display": "flex",
            "maxWidth": "100%",
            "flexGrow": "1",
            "maxHeight": "100%",
            "flexDirection": "column",
            "height": "100%",
            "position": "relative",
        },
    )

    return dashboard_layout, header_content


def create_error_layout(message: str):
    """
    Create error layout for display.

    Args:
        message: Error message to display

    Returns:
        Error layout component
    """
    return dmc.Center(
        dmc.Alert(
            message,
            title="Error",
            color="red",
            style={"marginTop": "2rem"},
        ),
        style={"height": "calc(100vh - 60px)"},
    )


def register_component_callbacks(app):
    """
    Register component rendering callbacks for Viewer App.

    Includes callbacks for:
    - Card components (data display)
    - Figure components (charts, graphs)
    - Interactive components (filters, selectors)
    - Table components (data tables with sorting/pagination)

    All callbacks are view-only (no editing functionality).

    Args:
        app: Dash app instance
    """
    logger.info("  📋 Registering component rendering callbacks")

    # Register card component callbacks
    from depictio.dash.modules.card_component.callbacks import register_callbacks_card_component

    register_callbacks_card_component(app)

    # Register figure component callbacks
    from depictio.dash.modules.figure_component.callbacks import (
        register_callbacks_figure_component,
    )

    register_callbacks_figure_component(app)

    # Register interactive component callbacks
    from depictio.dash.modules.interactive_component.callbacks import (
        register_callbacks_interactive_component,
    )

    register_callbacks_interactive_component(app)

    # Register table component view mode callbacks
    from depictio.dash.modules.table_component.callbacks import register_callbacks_table_component

    register_callbacks_table_component(app)

    # Register MultiQC component view mode callbacks
    from depictio.dash.modules.multiqc_component.callbacks import (
        register_callbacks_multiqc_component,
    )

    register_callbacks_multiqc_component(app)

    logger.info("  ✅ Component rendering callbacks registered")


def register_header_callbacks(app):
    """
    Register minimal header callbacks for Viewer App.

    Includes only view-mode header functionality:
    - Share modal
    - Theme switching
    - Navigation

    Excludes:
    - Edit mode buttons
    - Save functionality
    - Component editing

    Args:
        app: Dash app instance
    """
    logger.info("  📋 Registering minimal header callbacks")

    # Register minimal header callbacks (no edit mode)
    from depictio.dash.layouts.header import register_callbacks_header

    register_callbacks_header(app)

    # Register sidebar callbacks (admin link, server status, avatar)
    from depictio.dash.layouts.sidebar import register_sidebar_callbacks

    register_sidebar_callbacks(app)

    # Add clientside callback for theme-aware body class
    app.clientside_callback(
        """
        function(pathname) {
            const currentPath = pathname || window.location.pathname;

            setTimeout(() => {
                document.body.classList.add('page-loaded');
                document.body.classList.remove('auth-page');
            }, 50);
        }
        """,
        Input("url", "pathname"),
        prevent_initial_call="initial_duplicate",
    )

    logger.info("  ✅ Header callbacks registered")
