"""
Callback registration for the Depictio Dash application.
"""

from dash import Input, Output, State, ctx

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.core.auth import process_authentication


def register_main_callback(app):
    """
    Register the main callback for page routing and authentication.

    Args:
        app (dash.Dash): The Dash application instance
    """
    logger.info("🔥 REGISTERING MAIN CALLBACK for page routing and authentication")

    @app.callback(
        Output("page-content", "children"),
        Output("header-content", "children"),
        Output("url", "pathname"),
        Output("local-store", "data", allow_duplicate=True),
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
            State("theme-store", "data"),
            State("project-cache-store", "data"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def display_page(pathname, local_data, theme_store, cached_project_data):
        """
        Main callback for handling page routing and authentication.

        Args:
            pathname (str): Current URL pathname
            local_data (dict): Local storage data containing authentication information

        Returns:
            tuple: (page_content, header, pathname, local_data)
        """
        trigger = ctx.triggered_id
        logger.info(f"🔥 MAIN CALLBACK TRIGGERED: {trigger}, pathname={pathname}")

        # PERFORMANCE DEBUG: Log data sizes to identify serialization bottlenecks
        # import sys

        # local_data_size = sys.getsizeof(str(local_data)) if local_data else 0
        # theme_store_size = sys.getsizeof(str(theme_store)) if theme_store else 0
        # cached_project_size = sys.getsizeof(str(cached_project_data)) if cached_project_data else 0

        # logger.info(
        #     f"🔍 CALLBACK DATA SIZES: local_data={local_data_size:,}B, theme_store={theme_store_size:,}B, cached_project={cached_project_size:,}B"
        # )

        # if cached_project_size > 100000:  # > 100KB
        #     logger.warning(
        #         f"⚠️ LARGE PROJECT CACHE: {cached_project_size:,} bytes - potential performance bottleneck!"
        #     )

        # Process authentication and return appropriate content
        result = process_authentication(pathname, local_data, theme_store, cached_project_data)
        logger.info(
            f"🔥 MAIN CALLBACK RESULT: page_content={'<content>' if result[0] else 'None'}, header_content={'<header>' if result[1] else 'None'}, pathname={result[2]}"
        )
        return result

    logger.info("🔥 MAIN CALLBACK REGISTERED SUCCESSFULLY")

    # Move header visibility to clientside for instant response
    app.clientside_callback(
        """
        function(pathname) {
            console.log('🔥 CLIENTSIDE HEADER VISIBILITY: pathname=' + pathname);
            if (pathname === '/auth') {
                // Hide header on auth page
                return null;
            } else {
                // Show header on all other pages (including dashboard routes)
                return {"height": 50};
            }
        }
        """,
        Output("app-shell", "header"),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    # Add clientside callback to manage body classes for auth page
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

            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-resize-output", "children", allow_duplicate=True),
        Input("url", "pathname"),
        prevent_initial_call="initial_duplicate",
    )


def register_all_callbacks(app):
    """
    Register all callbacks for the application.

    Args:
        app (dash.Dash): The Dash application instance
    """
    # Register main callback for page routing
    register_main_callback(app)

    # Register layout callbacks
    register_layout_callbacks(app)

    # Register component callbacks
    # register_component_callbacks(app)

    # Register feature-specific callbacks
    register_feature_callbacks(app)

    # Register theme bridge callback
    # Register progressive loading callbacks
    # from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
    #     register_progressive_loading_callbacks,
    # )
    # from depictio.dash.layouts.edit import register_reset_button_callbacks
    # register_reset_button_callbacks(app)
    # register_dashboard_callbacks(app)

    # from depictio.dash.theme_utils import register_theme_bridge_callback

    # register_theme_bridge_callback(app)
    # register_progressive_loading_callbacks(app)

    # Register analytics callbacks
    # from depictio.dash.components.analytics_tracker import register_analytics_callbacks
    # from depictio.dash.layouts.admin_analytics_callbacks import register_admin_analytics_callbacks

    # register_analytics_callbacks(app)
    # register_admin_analytics_callbacks(app)


def register_dashboard_callbacks(app):
    from depictio.dash.layouts.draggable import register_callbacks_draggable
    from depictio.dash.layouts.notes_footer import register_callbacks_notes_footer
    from depictio.dash.layouts.save import register_callbacks_save
    from depictio.dash.layouts.stepper import register_callbacks_stepper

    register_callbacks_stepper(app)
    register_callbacks_draggable(app)
    register_callbacks_notes_footer(app)
    register_callbacks_save(app)


def register_layout_callbacks(app):
    """
    Register callbacks for layout components.

    Args:
        app (dash.Dash): The Dash application instance
    """
    from depictio.dash.layouts.app_layout import register_tab_routing_callback
    from depictio.dash.layouts.component_creator import register_component_creator_callbacks
    from depictio.dash.layouts.consolidated_api import register_consolidated_api_callbacks
    from depictio.dash.layouts.dashboard_content import register_dashboard_content_callbacks
    from depictio.dash.layouts.header import register_callbacks_header
    from depictio.dash.layouts.navigation_editor import register_navigation_editor_callbacks
    from depictio.dash.layouts.sidebar import register_sidebar_callbacks

    # from depictio.dash.layouts.stepper_parts.part_one import register_callbacks_stepper_part_one
    # from depictio.dash.layouts.stepper_parts.part_three import register_callbacks_stepper_part_three
    # from depictio.dash.layouts.stepper_parts.part_two import register_callbacks_stepper_part_two
    from depictio.dash.simple_theme import register_simple_theme_system

    # Register consolidated API callbacks first (highest priority)
    register_consolidated_api_callbacks(app)

    # Register dashboard content callbacks (background callback for dashboard container)
    register_dashboard_content_callbacks(app)

    # Register component creator callbacks (for add component stepper)
    register_component_creator_callbacks(app)

    # Register navigation editor callbacks (for dynamic tab/navlink creation)
    register_navigation_editor_callbacks(app)

    # Register layout callbacks

    # register_callbacks_stepper_part_one(app)
    # register_callbacks_stepper_part_two(app)
    # register_callbacks_stepper_part_three(app)
    register_callbacks_header(app)

    register_sidebar_callbacks(app)
    register_simple_theme_system(app)

    # Register tab routing callback for URL updates
    register_tab_routing_callback(app)


def register_component_callbacks(app):
    """
    Register callbacks for UI components.

    Args:
        app (dash.Dash): The Dash application instance
    """
    from depictio.dash.modules.card_component.frontend import register_callbacks_card_component
    from depictio.dash.modules.figure_component.frontend import register_callbacks_figure_component
    from depictio.dash.modules.interactive_component.frontend import (
        register_callbacks_interactive_component,
    )
    from depictio.dash.modules.jbrowse_component.frontend import (
        register_callbacks_jbrowse_component,
    )
    from depictio.dash.modules.table_component.frontend import register_callbacks_table_component
    from depictio.dash.modules.text_component.frontend import register_callbacks_text_component

    # Register component callbacks
    register_callbacks_card_component(app)
    register_callbacks_interactive_component(app)
    register_callbacks_figure_component(app)
    register_callbacks_jbrowse_component(app)
    register_callbacks_table_component(app)
    register_callbacks_text_component(app)


def register_feature_callbacks(app):
    """
    Register callbacks for specific features.

    Args:
        app (dash.Dash): The Dash application instance
    """
    from depictio.dash.layouts.admin_management import register_admin_callbacks
    from depictio.dash.layouts.admin_notifications import register_admin_notifications_callbacks
    from depictio.dash.layouts.dashboards_management import register_callbacks_dashboards_management
    from depictio.dash.layouts.profile import register_profile_callbacks
    from depictio.dash.layouts.project_data_collections import (
        register_project_data_collections_callbacks,
    )
    from depictio.dash.layouts.projects import (
        register_projects_callbacks,
        register_workflows_callbacks,
    )
    from depictio.dash.layouts.projectwise_user_management import (
        register_projectwise_user_management_callbacks,
    )
    from depictio.dash.layouts.tokens_management import register_tokens_management_callbacks
    from depictio.dash.layouts.users_management import register_callbacks_users_management

    # Register feature callbacks
    register_callbacks_dashboards_management(app)
    register_profile_callbacks(app)
    register_callbacks_users_management(app)
    register_tokens_management_callbacks(app)
    register_workflows_callbacks(app)
    register_projects_callbacks(app)
    register_admin_callbacks(app)
    register_projectwise_user_management_callbacks(app)
    register_project_data_collections_callbacks(app)
    register_admin_notifications_callbacks(app)
