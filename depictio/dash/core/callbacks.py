"""
Callback registration for the Depictio Dash application.

This module contains legacy callback registration code from the single-app
architecture. The new multi-app architecture (flask_dispatcher.py + pages/*.py)
handles all callback registration.

Note:
    This file is kept for reference but should not be used in production.
    Multi-app callback registration happens in:
        - depictio/dash/pages/management_app.py (Management app callbacks)
        - depictio/dash/pages/dashboard_viewer.py (Viewer app callbacks)
        - depictio/dash/pages/dashboard_editor.py (Editor app callbacks)

Functions:
    register_main_callback: Register the main callback for page routing
    register_all_callbacks: Legacy function to register all callbacks (deprecated)
    register_layout_callbacks: Legacy layout callbacks registration (deprecated)
    register_component_callbacks: Legacy component callbacks registration (deprecated)
"""

from dash import Input, Output, State, ctx

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.core.auth import process_authentication


def register_main_callback(app) -> None:
    """
    Register the main callback for page routing and authentication.

    This callback handles URL pathname changes and local storage data changes,
    performing authentication validation and routing to appropriate pages.

    Args:
        app: The Dash application instance.
    """

    # Cache for tracking last processed state to prevent duplicate processing
    last_processed_state = {"pathname": None, "timestamp": 0, "user_state_hash": None}

    def get_user_state_hash(local_data):
        """
        Hash only fields that affect page visual rendering.

        Token refresh (access_token change) should NOT trigger re-render.
        Only user-visible state changes (login status, user identity) should
        cause a page update.

        Args:
            local_data: Local storage data dictionary.

        Returns:
            Hash of user-visible state, or None if no local_data.
        """
        if not local_data:
            return None
        return hash((local_data.get("logged_in"), local_data.get("user_id")))

    @app.callback(
        Output("page-content", "children"),
        Output("header-content", "children"),
        Output("url", "pathname"),
        Output("local-store", "data", allow_duplicate=True),
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
            State("theme-store", "data"),
            State("project-cache", "data"),
            State("dashboard-init-data", "data"),  # API Consolidation: Dashboard init data
        ],
        prevent_initial_call="initial_duplicate",
    )
    def display_page(
        pathname,
        local_data,
        theme_store,
        cached_project_data,
        dashboard_init_data,
    ):
        """
        Main callback for handling page routing and authentication.

        Includes performance optimizations to prevent duplicate processing
        when authentication updates trigger local-store changes.

        Args:
            pathname: Current URL pathname.
            local_data: Local storage data containing authentication information.
            theme_store: Theme store data (light/dark).
            cached_project_data: Cached project data.
            dashboard_init_data: Dashboard initialization data.

        Returns:
            Tuple of (page_content, header, pathname, local_data).
        """
        import time

        from dash import no_update

        trigger_id = ctx.triggered_id

        # CRITICAL OPTIMIZATION: Early return if triggered by local-store with unchanged state
        # This prevents duplicate processing when authentication updates local-store
        if trigger_id == "local-store" and pathname == last_processed_state["pathname"]:
            current_hash = get_user_state_hash(local_data)
            time_since_last = time.time() - last_processed_state["timestamp"]

            # Only skip if BOTH pathname AND user-visible state unchanged
            # Token refresh changes access_token but NOT user_state_hash (silent refresh)
            # CONSERVATIVE: 1 second window (not 5) to avoid catching browser refreshes
            if time_since_last < 1 and current_hash == last_processed_state["user_state_hash"]:
                # Safe to skip - only tokens changed (silent refresh) or duplicate trigger
                # Return no_update for all outputs to prevent any changes
                return no_update, no_update, no_update, no_update

        # Update state including hash
        last_processed_state.update(
            {
                "pathname": pathname,
                "timestamp": time.time(),
                "user_state_hash": get_user_state_hash(local_data),
            }
        )

        # Process authentication and return appropriate content
        result = process_authentication(
            pathname,
            local_data,
            theme_store,
            cached_project_data,
            dashboard_init_data,
        )

        return result

    # Move header visibility to clientside for instant response
    # app.clientside_callback(
    #     """
    #     function(pathname) {
    #         console.log('🔥 CLIENTSIDE HEADER VISIBILITY: pathname=' + pathname);
    #         if (pathname === '/auth') {
    #             // Hide header on auth page
    #             return null;
    #         } else if (pathname && pathname.startsWith('/dashboard/')) {
    #             // Dashboard pages: 45px header
    #             return {"height": 45, "padding": "0"};
    #         } else {
    #             // Other pages: 65px header for better vertical space
    #             return {"height": 65, "padding": "0"};
    #         }
    #     }
    #     """,
    #     Output("app-shell", "header"),
    #     Input("url", "pathname"),
    #     prevent_initial_call=True,
    # )

    # # Control AppShell layout based on page type
    # app.clientside_callback(
    #     """
    #     function(pathname) {
    #         console.log('🔥 CLIENTSIDE LAYOUT CONTROL: pathname=' + pathname);
    #         if (pathname && pathname.startsWith('/dashboard/')) {
    #             // Dashboard pages: default layout (navbar offset by header)
    #             return "default";
    #         } else {
    #             // Other pages: alt layout (navbar extends to top)
    #             return "alt";
    #         }
    #     }
    #     """,
    #     Output("app-shell", "layout"),
    #     Input("url", "pathname"),
    #     prevent_initial_call=True,
    # )

    # Add clientside callback to manage body classes for auth page
    # Dash v3: No Output required for DOM-only manipulation callbacks
    app.clientside_callback(
        """
        function(pathname) {
            // Also check location.pathname for initial load
            const currentPath = pathname || window.location.pathname;

            // Add a small delay to ensure smooth transitions
            setTimeout(() => {
                if (currentPath === '/auth') {
                    document.body.classList.add('auth-page');
                    document.body.classList.remove('page-loaded');
                } else {
                    document.body.classList.remove('auth-page');
                    document.body.classList.add('page-loaded');
                }
            }, 50); // 50ms delay for smooth transition
        }
        """,
        Input("url", "pathname"),
        prevent_initial_call="initial_duplicate",
    )

    # Add clientside callback to manage page-content padding for dashboard vs other pages
    # app.clientside_callback(
    #     """
    #     function(pathname) {
    #         const currentPath = pathname || window.location.pathname;

    #         // Add a small delay to ensure DOM is ready
    #         setTimeout(() => {
    #             const pageContent = document.getElementById('page-content');
    #             if (pageContent) {
    #                 if (currentPath && currentPath.startsWith('/dashboard/')) {
    #                     // Dashboard pages: minimal padding (grid layout handles spacing)
    #                     pageContent.style.padding = '0.25rem 0';
    #                 } else {
    #                     // Other pages: proper horizontal padding for readability
    #                     pageContent.style.padding = '1rem 2rem';
    #                     pageContent.style.maxWidth = '100%';
    #                 }
    #             }
    #         }, 50);

    #         return window.dash_clientside.no_update;
    #     }
    #     """,
    #     Output("dummy-padding-output", "children", allow_duplicate=True),
    #     Input("url", "pathname"),
    #     prevent_initial_call="initial_duplicate",
    # )


def register_all_callbacks(app) -> None:
    """
    Register all callbacks for the application (deprecated).

    Deprecated:
        This function is no longer used in the multi-app architecture.
        Callback registration now happens in page-specific modules.

    Args:
        app: The Dash application instance.
    """
    # DEPRECATED: This callback registration is no longer used
    logger.warning(
        "⚠️  DEPRECATED: register_all_callbacks() called - use page-specific registration instead"
    )
    register_main_callback(app)  # Page routing and authentication
    register_layout_callbacks(app)  # Header, sidebar, navigation

    # DEPRECATED: Component and feature callbacks now registered per app
    register_component_callbacks(app)  # Component core rendering
    # register_feature_callbacks(app)  # REMOVED - now in page modules

    # Register theme bridge callback
    # Register progressive loading callbacks
    # REMOVED: Position controls replaced with drag & drop
    # from depictio.dash.layouts import (
    #     position_controls,  # noqa: F401 - callback registers via decorator
    # )
    # from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
    #     register_progressive_loading_callbacks,
    # )
    # from depictio.dash.layouts.edit import (
    #     # register_partial_data_button_callbacks,
    #     # register_reset_button_callbacks,
    # )
    # REMOVED: Position controls replaced with drag & drop
    # from depictio.dash.layouts.position_controls import register_position_clientside_callback

    # from depictio.dash.theme_utils import register_theme_bridge_callback

    # register_theme_bridge_callback(app)
    # register_progressive_loading_callbacks(app)
    # register_reset_button_callbacks(app)
    # register_partial_data_button_callbacks(app)
    # REMOVED: Position controls replaced with drag & drop
    # register_position_clientside_callback(app)  # Register clientside position update callback

    # Register analytics callbacks
    # from depictio.dash.components.analytics_tracker import register_analytics_callbacks

    # PERFORMANCE OPTIMIZATION: Admin analytics callbacks commented out to reduce initial load time
    # These 8 callbacks were adding ~50-100ms to the Dash renderer initialization (callback graph building)
    # They only need to run on /admin page, not on every page load
    # TODO: Re-enable with lazy loading when /admin page is accessed
    # from depictio.dash.layouts.admin_analytics_callbacks import register_admin_analytics_callbacks

    # register_analytics_callbacks(app)
    # register_admin_analytics_callbacks(app)  # Commented out for performance


def register_layout_callbacks(app) -> None:
    """
    Register core layout callbacks (deprecated).

    Deprecated:
        This function is no longer used in the multi-app architecture.
        Layout callbacks are now registered in page-specific modules.

    Args:
        app: The Dash application instance.
    """
    from depictio.dash.layouts.draggable import register_callbacks_draggable
    from depictio.dash.layouts.header import register_callbacks_header
    from depictio.dash.layouts.save import register_callbacks_save_lite

    # CORE: Header callbacks (always needed for navigation and edit mode switching)
    register_callbacks_header(app)  # 8 callbacks: edit mode nav, share modal, offcanvas, burger

    # CORE: Save callback (always needed - save button is in header)
    register_callbacks_save_lite(app)  # Minimal save callback

    # CORE: Draggable grid edit mode callback (always needed - toggles action icon visibility)
    register_callbacks_draggable(app)  # Edit mode className toggle based on URL

    # NOTE: Sidebar content is static (no callbacks needed - rendered once in app_layout.py)

    # NOTE: No longer relevant in multi-app architecture


def register_component_callbacks(app) -> None:
    """
    Register callbacks for UI components (deprecated).

    Deprecated:
        This function is no longer used in the multi-app architecture.
        Component callbacks are now registered per app in page modules.

    Args:
        app: The Dash application instance.
    """
    # Import core callback registration functions
    from depictio.dash.modules.card_component.callbacks import (
        register_callbacks_card_component,
    )
    from depictio.dash.modules.figure_component.callbacks import register_callbacks_figure_component
    from depictio.dash.modules.interactive_component.callbacks import (
        register_callbacks_interactive_component,
    )

    # Import other component callbacks (no lazy loading yet)
    # from depictio.dash.modules.jbrowse_component.frontend import (
    #     register_callbacks_jbrowse_component,
    # )
    # from depictio.dash.modules.multiqc_component.frontend import (
    #     register_callbacks_multiqc_component,
    # )
    # from depictio.dash.modules.table_component.frontend import register_callbacks_table_component
    # from depictio.dash.modules.text_component.frontend import register_callbacks_text_component

    # Register CORE component callbacks (always loaded at startup)
    # These handle viewing/rendering dashboards, not editing/designing components
    register_callbacks_card_component(app)
    register_callbacks_interactive_component(app)
    register_callbacks_figure_component(app)
    # register_callbacks_jbrowse_component(app)
    # register_callbacks_multiqc_component(app)
    # register_callbacks_table_component(app)
    # register_callbacks_text_component(app)

    # NOTE: Lazy loading is no longer used in the multi-app architecture.
    # All callbacks are registered upfront for each app in their respective page modules:
    #   - management_app.py: All management callbacks (~70 callbacks)
    #   - dashboard_viewer.py: All viewer callbacks (~30 callbacks)
    #   - dashboard_editor.py: All editor callbacks (~65 callbacks) - future


# REMOVED: register_edit_mode_callbacks()
# Edit mode callbacks are now registered directly in dashboard_editor.py (future implementation)
# or in management_app.py for the combined management interface


# REMOVED: register_feature_callbacks()
# Feature callbacks are now registered directly in the page modules:
#   - management_app.py: Auth, dashboards, profile, admin, tokens
#   - dashboard_viewer.py: Component rendering, minimal UI
#   - dashboard_editor.py: Edit mode, component design (future)


# REMOVED: register_extended_feature_callbacks()
# Extended features are now registered in management_app.py as needed
# Environment variables can control which features are enabled per deployment
