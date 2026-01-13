"""
Dashboard Editor App for multi-app Depictio architecture.

This module provides the dashboard editing Dash app that handles:
- Dashboard editing (/dashboard-edit/{id})
- Component rendering with edit controls (cards, figures, interactive filters, tables)
- Component creation/editing via stepper UI
- Drag & drop, resize, positioning
- Save functionality
- Real-time data updates via callbacks

Routes:
    /dashboard-edit/{id} - Edit dashboard (full edit mode)
    /dashboard-edit/{id}/component/add/{uuid} - Component creation stepper
    /dashboard-edit/{id}/component/edit/{uuid} - Component editing stepper

Key Features:
    - Full AppShell with sidebar
    - Edit mode enabled (all edit controls visible)
    - Drag & drop component positioning
    - Component creation and editing
    - Save dashboard layouts
    - Callback registry for editing functionality (~65 callbacks)
    - Shared localStorage for auth and theme
"""

from typing import Optional

import dash_mantine_components as dmc
from dash import Input, Output, State, ctx, dcc, html, no_update

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


def create_editor_layout():
    """
    Create layout for Dashboard Editor App.

    Full AppShell with all edit controls enabled.

    Returns:
        dmc.MantineProvider: Complete layout with AppShell and stores
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

    # Create additional stores specific to Editor App
    # Note: project-cache, theme-relay-store, and dashboard-init-data are already in create_shared_stores()
    additional_stores = [
        # Notification container for user feedback (save operations, errors, etc.)
        dmc.NotificationContainer(id="notification-container"),
        # Analytics tracking
        create_analytics_tracker(),
        # Hidden store to track if dashboard layout has unsaved changes (True = saved, False = unsaved)
        dcc.Store(id="layout-saved-state", data=True, storage_type="memory"),
        # Hidden button that JavaScript can trigger to mark layout as unsaved
        html.Button(id="layout-change-trigger", style={"display": "none"}, n_clicks=0),
        # Hidden output divs for clientside callbacks
        html.Div(id="dummy-plotly-output", style={"display": "none"}),
        html.Div(id="test-output", style={"display": "none"}),
    ]

    # Use minimal AppShell (can be extended to include sidebar later)
    layout = create_minimal_app_shell(
        app_name="Depictio - Dashboard Editor",
        main_content=main_content,
        show_header=True,
        additional_stores=additional_stores,
    )

    return layout


# Module-level layout function for flask_dispatcher.py
# IMPORTANT: Must be a function, not a layout instance, because dash.get_asset_url()
# and other Dash functions require a Dash app context which doesn't exist during module import
def layout():
    """Return layout for Editor App (called by Dash after app creation)."""
    return create_editor_layout()


def register_callbacks(app):
    """
    Register all callbacks for Dashboard Editor App.

    Editor app includes (~65 callbacks):
    - Main routing callback (1)
    - Component rendering callbacks (20-25)
      - Card components
      - Figure components
      - Interactive filters
      - Table components
    - Header callbacks (full edit mode, 10-15)
    - Component creation/editing (15-20)
    - Save/layout management (5-10)
    - Theme switching (clientside, 2)

    Args:
        app (dash.Dash): Editor app instance
    """
    logger.info("🔥 EDITOR APP: Registering callbacks")

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

    # 3. Header callbacks (full edit mode)
    register_header_callbacks(app)

    # 4. Component creation/editing callbacks
    register_component_editing_callbacks(app)

    # 5. Save and layout management callbacks
    register_save_callbacks(app)

    logger.info("✅ EDITOR APP: All callbacks registered (~65 callbacks)")


def register_routing_callback(app):
    """
    Register main routing callback for Editor App.

    Handles:
    - Dashboard editing (/dashboard-edit/{id})
    - Component creation (/dashboard-edit/{id}/component/add/{uuid})
    - Component editing (/dashboard-edit/{id}/component/edit/{uuid})
    """
    logger.info("  📋 Registering main routing callback")

    @app.callback(
        Output("page-content", "children"),
        Output("header-content", "children"),
        Output("url", "pathname"),
        Output("local-store", "data", allow_duplicate=True),
        [
            Input("url", "pathname"),
        ],
        [
            State("local-store", "data"),
            State("theme-store", "data"),
            State("project-metadata-store", "data"),
            State("dashboard-init-data", "data"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def route_editor(
        pathname,
        local_data,
        theme_store,
        cached_project_data,
        dashboard_init_data,
    ):
        """
        Main routing callback for Editor App.

        Routes:
        - /dashboard-edit/{id} - Edit dashboard
        - /dashboard-edit/{id}/component/add/{uuid} - Create component
        - /dashboard-edit/{id}/component/edit/{uuid} - Edit component

        Args:
            pathname: Current URL pathname
            local_data: Local storage data (auth tokens)
            theme_store: Theme store data (light/dark)
            cached_project_data: Cached project data from project-metadata-store
            dashboard_init_data: Dashboard initialization data

        Returns:
            tuple: (page_content, header_content, pathname, local_data)
        """
        logger.info("=" * 100)
        logger.info("🔄 EDITOR ROUTING CALLBACK STARTED")
        logger.info(f"   Input pathname: {pathname}")
        logger.info(f"   Triggered by: {ctx.triggered_id}")
        logger.info(f"   Triggered prop: {ctx.triggered}")

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
            # Always redirect to /auth on auth failure, even if triggered by local-store
            return (
                html.Div("Redirecting to login..."),
                html.Div(),  # Empty header
                "/auth",
                {"logged_in": False, "access_token": None},
            )

        # Type guard
        if not updated_local_data:
            logger.error("Auth validation returned None - forcing logout")
            # Always redirect to /auth on auth failure, even if triggered by local-store
            return (
                html.Div("Authentication error - redirecting..."),
                html.Div(),  # Empty header
                "/auth",
                {"logged_in": False, "access_token": None},
            )

        # Check if this is a component creation/editing route
        if "/component/add/" in pathname:
            logger.info(f"📝 Component creation route detected - pathname: {pathname}")
            result = route_component_creation(pathname, updated_local_data, theme)
            logger.info(f"📝 Component creation returning pathname: {result[2]}")
            logger.info("=" * 100)
            # If triggered by local-store, preserve current URL
            if triggered_by_local_store:
                return result[0], result[1], no_update, result[3]
            return result
        elif "/component/edit/" in pathname:
            logger.info(f"✏️ Component editing route detected - pathname: {pathname}")
            result = route_component_editing(pathname, updated_local_data, theme)
            logger.info(f"📤 COMPONENT EDITING RETURNING - pathname: {result[2]}")
            logger.info("=" * 100)
            # If triggered by local-store, preserve current URL
            if triggered_by_local_store:
                logger.info("   🔒 Preserving edit URL (not updating pathname)")
                return result[0], result[1], no_update, result[3]
            return result

        # Extract dashboard ID from pathname
        dashboard_id = extract_dashboard_id(pathname)

        if not dashboard_id:
            logger.warning(f"Invalid pathname format: {pathname}")
            error_content = create_error_layout("Invalid dashboard URL")
            # If triggered by local-store, preserve current URL
            if triggered_by_local_store:
                return error_content, html.Div(), no_update, updated_local_data
            return error_content, html.Div(), pathname, updated_local_data

        # Load dashboard data in edit mode
        logger.info(f"📊 Loading dashboard for editing: {dashboard_id}")
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
                "📤 EDITOR ROUTING RETURNING - pathname: no_update (preserving current URL)"
            )
            logger.info("=" * 100)
            return content, header_content, no_update, updated_local_data
        else:
            logger.info(f"📤 EDITOR ROUTING RETURNING - pathname: {pathname}")
            logger.info("=" * 100)
            return content, header_content, pathname, updated_local_data


def route_component_creation(pathname: str, local_data: dict, theme: str):
    """
    Route to component creation stepper page.

    Args:
        pathname: URL pathname (/dashboard-edit/{id}/component/add/{uuid})
        local_data: User authentication data
        theme: Current theme (light/dark)

    Returns:
        tuple: (stepper_layout, header_content, pathname, local_data)
    """
    from depictio.dash.layouts.stepper_page import create_stepper_page

    # Extract dashboard ID and component UUID
    parts = pathname.strip("/").split("/")
    # parts: ['dashboard-edit', '{id}', 'component', 'add', '{uuid}']
    if len(parts) >= 5:
        dashboard_id = parts[1]
        component_uuid = parts[4]

        # Create stepper page for component creation (in editor app, so is_edit_mode=True)
        stepper_layout = create_stepper_page(dashboard_id, component_uuid, theme, is_edit_mode=True)

        # Empty header for stepper page (or create minimal header)
        header_content = html.Div()

        return stepper_layout, header_content, pathname, local_data

    # Invalid format
    error_content = create_error_layout("Invalid component creation URL")
    return error_content, html.Div(), pathname, local_data


def route_component_editing(pathname: str, local_data: dict, theme: str):
    """
    Route to component editing page.

    Args:
        pathname: URL pathname (/dashboard-edit/{id}/component/edit/{uuid})
        local_data: User authentication data
        theme: Current theme (light/dark)

    Returns:
        tuple: (edit_layout, header_content, pathname, local_data)
    """
    from depictio.dash.api_calls import api_call_get_dashboard
    from depictio.dash.layouts.edit_page import create_edit_page

    # Extract dashboard ID and component UUID
    parts = pathname.strip("/").split("/")
    # parts: ['dashboard-edit', '{id}', 'component', 'edit', '{uuid}']
    if len(parts) >= 5:
        dashboard_id = parts[1]
        component_id = parts[4]

        logger.info(f"✏️ EDIT COMPONENT - Dashboard: {dashboard_id}, Component: {component_id}")

        # Fetch dashboard data to get component metadata
        dashboard_data = None
        component_data = None

        if local_data:
            try:
                dashboard_data = api_call_get_dashboard(dashboard_id, local_data["access_token"])

                # Find component in stored_metadata
                stored_metadata = dashboard_data.get("stored_metadata", [])
                logger.info(f"🔍 EDIT COMPONENT - Looking for component_id: {component_id}")
                logger.info(f"🔍 EDIT COMPONENT - stored_metadata count: {len(stored_metadata)}")

                # Try multiple fields: component_id, index, _id
                for meta in stored_metadata:
                    meta_id = str(meta.get("component_id", meta.get("index", meta.get("_id"))))
                    logger.debug(f"  Comparing {meta_id} with {component_id}")
                    if meta_id == str(component_id):
                        component_data = meta
                        logger.info(
                            f"✅ EDIT COMPONENT - Found component data: {meta.get('component_type')}"
                        )
                        break

                if not component_data:
                    logger.error(f"❌ Component {component_id} not found in dashboard metadata")
                    logger.error(
                        f"Available component IDs: {[str(m.get('component_id', m.get('index', m.get('_id')))) for m in stored_metadata]}"
                    )
                    error_content = create_error_layout(
                        f"Component {component_id} not found in dashboard"
                    )
                    return error_content, html.Div(), pathname, local_data

            except Exception as e:
                logger.error(f"Failed to load component data: {e}")
                error_content = create_error_layout("Failed to load component data")
                return error_content, html.Div(), pathname, local_data
        else:
            error_content = create_error_layout("Authentication required")
            return error_content, html.Div(), pathname, local_data

        # Get dashboard title
        dashboard_title = (
            dashboard_data.get("dashboard_name", dashboard_data.get("title"))
            if dashboard_data
            else None
        )

        # Create edit page for component editing (in editor app, so is_edit_mode=True)
        edit_layout = create_edit_page(
            dashboard_id=dashboard_id,
            component_id=component_id,
            component_data=component_data,
            dashboard_title=dashboard_title,
            theme=theme,
            TOKEN=local_data.get("access_token"),
            is_edit_mode=True,  # Editor app - back button should go to /dashboard-edit/{id}
        )

        # Empty header for edit page (or create minimal header)
        header_content = html.Div()

        return edit_layout, header_content, pathname, local_data

    # Invalid format
    error_content = create_error_layout("Invalid component editing URL")
    return error_content, html.Div(), pathname, local_data


def extract_dashboard_id(pathname: str) -> Optional[str]:
    """
    Extract dashboard ID from pathname.

    Args:
        pathname: URL pathname (/dashboard-edit/{id})

    Returns:
        Dashboard ID or None if invalid format
    """
    if not pathname or not pathname.startswith("/dashboard-edit/"):
        return None

    parts = pathname.strip("/").split("/")
    # parts: ['dashboard-edit', '{id}']
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
    Load dashboard data and render components in edit mode.

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

    # Create header (EDIT MODE - with all edit controls)
    header_content, backend_components = design_header(
        depictio_dash_data, local_data, edit_mode=True
    )

    # Extract layout and children data
    init_layout = depictio_dash_data.get("stored_layout_data", {})
    init_children = depictio_dash_data.get("stored_children_data", [])
    stored_metadata = depictio_dash_data.get("stored_metadata", [])
    # Extract dual-panel layout data
    left_panel_layout_data = depictio_dash_data.get("left_panel_layout_data", [])
    right_panel_layout_data = depictio_dash_data.get("right_panel_layout_data", [])

    # DEBUG: Log loaded layout data
    logger.info("📐 EDITOR: Loaded layout data from dashboard:")
    logger.info(f"   - LEFT panel: {len(left_panel_layout_data)} layout items")
    logger.info(f"   - RIGHT panel: {len(right_panel_layout_data)} layout items")
    if left_panel_layout_data:
        logger.info(f"   - LEFT sample: {left_panel_layout_data[:2]}")
    if right_panel_layout_data:
        logger.info(f"   - RIGHT sample: {right_panel_layout_data[:2]}")

    # Render draggable layout (EDIT MODE)
    core = design_draggable(
        init_layout,
        init_children,
        dashboard_id,
        local_data,
        cached_project_data=cached_project_data,
        stored_metadata=stored_metadata,
        edit_mode=True,  # EDIT MODE - enables drag & drop, resize, etc.
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
    Register component rendering callbacks for Editor App.

    Includes callbacks for:
    - Card components (data display)
    - Figure components (charts, graphs)
    - Interactive components (filters, selectors)
    - Table components (data tables with sorting/pagination)

    All callbacks include edit functionality.

    Args:
        app: Dash app instance
    """
    logger.info("  📋 Registering component rendering callbacks")

    # Register card component callbacks (core + design for editor app)
    from depictio.dash.modules.card_component.callbacks import (
        load_design_callbacks as load_card_design,
    )
    from depictio.dash.modules.card_component.callbacks import (
        register_callbacks_card_component,
    )

    register_callbacks_card_component(app)
    load_card_design(app)  # Load design callbacks immediately (editor app is always in edit mode)

    # Register figure component callbacks (core + design for editor app)
    from depictio.dash.modules.figure_component.callbacks import (
        load_design_callbacks as load_figure_design,
    )
    from depictio.dash.modules.figure_component.callbacks import (
        register_callbacks_figure_component,
    )

    register_callbacks_figure_component(app)
    load_figure_design(app)  # Load design callbacks immediately

    # Register interactive component callbacks (core + design for editor app)
    from depictio.dash.modules.interactive_component.callbacks import (
        load_design_callbacks as load_interactive_design,
    )
    from depictio.dash.modules.interactive_component.callbacks import (
        register_callbacks_interactive_component,
    )

    register_callbacks_interactive_component(app)
    load_interactive_design(app)  # Load design callbacks immediately

    # Register table component view mode callbacks
    from depictio.dash.modules.table_component.callbacks import register_callbacks_table_component

    register_callbacks_table_component(app)

    logger.info("  ✅ Component rendering callbacks registered")


def register_header_callbacks(app):
    """
    Register header callbacks for Editor App (full edit mode).

    Includes:
    - Edit mode toggle
    - Save functionality
    - Add component button
    - Share modal
    - Theme switching
    - Navigation

    Args:
        app: Dash app instance
    """
    logger.info("  📋 Registering header callbacks (edit mode)")

    # Register full header callbacks (edit mode)
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


def register_component_editing_callbacks(app):
    """
    Register component creation and editing callbacks.

    Includes:
    - Add component button callback
    - Edit component button callback
    - Remove component callback
    - Duplicate component callback
    - Stepper navigation callbacks
    - Component save callbacks

    Args:
        app: Dash app instance
    """
    logger.info("  📋 Registering component editing callbacks")

    # Register add component callback
    from depictio.dash.layouts.add_component_simple import (
        register_add_component_simple_callback,
    )

    register_add_component_simple_callback(app)

    # Register edit component callback
    from depictio.dash.layouts.edit_component_simple import (
        register_edit_component_simple_callback,
    )

    register_edit_component_simple_callback(app)

    # Register remove component callback (new dual-panel implementation)
    from depictio.dash.layouts.callbacks.remove_component import (
        register_remove_component_callback,
    )

    register_remove_component_callback(app)

    # Register duplicate component callback (new dual-panel implementation)
    from depictio.dash.layouts.callbacks.duplicate_component import (
        register_duplicate_component_callback,
    )

    register_duplicate_component_callback(app)

    # Register stepper callbacks (for component creation flow)
    from depictio.dash.layouts.stepper import register_callbacks_stepper

    register_callbacks_stepper(app)

    # NOTE: Component edit/save callbacks are registered via lazy loading
    # when entering edit mode. See:
    # - depictio/dash/modules/card_component/callbacks/edit.py
    # - depictio/dash/modules/interactive_component/callbacks/edit.py

    logger.info("  ✅ Component editing callbacks registered (lazy loading)")


def register_save_callbacks(app):
    """
    Register save and layout management callbacks.

    Includes:
    - Save dashboard layout
    - Auto-save functionality
    - Layout persistence
    - Drag & drop position saving

    Args:
        app: Dash app instance
    """
    logger.info("  📋 Registering save callbacks")

    # Register save callback for dashboard persistence
    from depictio.dash.layouts.save import register_callbacks_save_lite

    register_callbacks_save_lite(app)

    # Register draggable grid callbacks (drag & drop, resize, save)
    from depictio.dash.layouts.draggable import register_callbacks_draggable

    register_callbacks_draggable(app)

    logger.info("  ✅ Save callbacks registered")
