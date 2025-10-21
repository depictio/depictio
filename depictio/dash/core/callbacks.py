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

    # Cache for tracking last processed state to prevent duplicate processing (Phase 4E-3 final)
    # Hash only user-visible state (logged_in, user_id) NOT tokens (silent refresh)
    last_processed_state = {"pathname": None, "timestamp": 0, "user_state_hash": None}

    def get_user_state_hash(local_data):
        """
        Hash only fields that affect page VISUAL rendering.
        Token refresh (access_token change) should NOT trigger re-render.

        Fields that affect UI:
        - logged_in: Login vs. logout state
        - user_id: Different user = different data

        Fields that DON'T affect UI (excluded):
        - access_token: Refreshes silently every 15 min
        - expire_datetime: Changes with token refresh
        - refresh_token: Rarely changes

        Returns:
            int: Hash of user-visible state, or None if no local_data
        """
        if not local_data:
            return None

        # Only hash fields that require visual page update
        user_visible_state = (
            local_data.get("logged_in"),
            local_data.get("user_id"),
            # Explicitly NOT including tokens - silent refresh!
        )
        return hash(user_visible_state)

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
            State("user-cache-store", "data"),  # Phase 4E-4: Pass cached user data
        ],
        prevent_initial_call="initial_duplicate",
    )
    def display_page(pathname, local_data, theme_store, cached_project_data, cached_user_data):
        """
        Main callback for handling page routing and authentication.

        PERFORMANCE OPTIMIZATION (Phase 4E):
        - Added comprehensive profiling to track duplicate executions
        - Added timing logs to identify bottlenecks
        - Added unique call ID for tracking execution flow
        - Added early return when triggered by local-store with unchanged pathname (Phase 4E-2)

        Args:
            pathname (str): Current URL pathname
            local_data (dict): Local storage data containing authentication information

        Returns:
            tuple: (page_content, header, pathname, local_data)
        """
        import time
        import uuid

        from dash import no_update

        # Generate unique call ID for tracking duplicates
        call_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # Log callback entry with full context
        trigger_id = ctx.triggered_id
        trigger_prop = ctx.triggered[0]["prop_id"] if ctx.triggered else "NONE"

        logger.info(f"[PERF-4E][{call_id}] 🔥 ROUTING CALLBACK ENTRY")
        logger.info(f"[PERF-4E][{call_id}]   pathname: {pathname}")
        logger.info(f"[PERF-4E][{call_id}]   triggered_id: {trigger_id} (type: {type(trigger_id)})")
        logger.info(f"[PERF-4E][{call_id}]   triggered_prop: {trigger_prop}")
        logger.info(f"[PERF-4E][{call_id}]   local_data: {'present' if local_data else 'None'}")
        logger.info(f"[PERF-4E][{call_id}]   theme_store: {'present' if theme_store else 'None'}")

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
                elapsed = (time.time() - start_time) * 1000
                logger.info(
                    f"[PERF-4E][{call_id}] 🔥 ROUTING CALLBACK EARLY RETURN (duplicate trigger, no user-visible changes)"
                )
                logger.info(
                    f"[PERF-4E][{call_id}]   time_since_last_process: {time_since_last:.1f}s"
                )
                logger.info(f"[PERF-4E][{call_id}]   user_state_hash: {current_hash}")
                logger.info(
                    f"[PERF-4E][{call_id}]   total_duration: {elapsed:.0f}ms (saved ~200-400ms!)"
                )
                # Return no_update for all outputs to prevent any changes
                return no_update, no_update, no_update, no_update
            elif current_hash != last_processed_state["user_state_hash"]:
                # User-visible state changed (login/logout, user switch)
                logger.info(
                    f"[PERF-4E][{call_id}] 🔥 ROUTING CALLBACK PROCESSING (user state changed)"
                )
                logger.info(
                    f"[PERF-4E][{call_id}]   old_hash: {last_processed_state['user_state_hash']}"
                )
                logger.info(f"[PERF-4E][{call_id}]   new_hash: {current_hash}")

        # Update state including hash
        last_processed_state.update(
            {
                "pathname": pathname,
                "timestamp": time.time(),
                "user_state_hash": get_user_state_hash(local_data),
            }
        )

        # Process authentication and return appropriate content
        auth_start = time.time()
        result = process_authentication(
            pathname, local_data, theme_store, cached_project_data, cached_user_data
        )
        auth_duration = (time.time() - auth_start) * 1000

        # Log callback exit with timing
        total_duration = (time.time() - start_time) * 1000
        logger.info(f"[PERF-4E][{call_id}] 🔥 ROUTING CALLBACK EXIT")
        logger.info(f"[PERF-4E][{call_id}]   auth_duration: {auth_duration:.0f}ms")
        logger.info(f"[PERF-4E][{call_id}]   total_duration: {total_duration:.0f}ms")
        logger.info(
            f"[PERF-4E][{call_id}]   result: page={'<content>' if result[0] else 'None'}, header={'<header>' if result[1] else 'None'}, pathname={result[2]}"
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
            } else if (pathname && pathname.startsWith('/dashboard/')) {
                // Dashboard pages: 45px header
                return {"height": 45, "padding": "0"};
            } else {
                // Other pages: 65px header for better vertical space
                return {"height": 65, "padding": "0"};
            }
        }
        """,
        Output("app-shell", "header"),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    # Control AppShell layout based on page type
    app.clientside_callback(
        """
        function(pathname) {
            console.log('🔥 CLIENTSIDE LAYOUT CONTROL: pathname=' + pathname);
            if (pathname && pathname.startsWith('/dashboard/')) {
                // Dashboard pages: default layout (navbar offset by header)
                return "default";
            } else {
                // Other pages: alt layout (navbar extends to top)
                return "alt";
            }
        }
        """,
        Output("app-shell", "layout"),
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

    # Add clientside callback to manage page-content padding for dashboard vs other pages
    app.clientside_callback(
        """
        function(pathname) {
            const currentPath = pathname || window.location.pathname;

            // Add a small delay to ensure DOM is ready
            setTimeout(() => {
                const pageContent = document.getElementById('page-content');
                if (pageContent) {
                    if (currentPath && currentPath.startsWith('/dashboard/')) {
                        // Dashboard pages: minimal padding (grid layout handles spacing)
                        pageContent.style.padding = '0.25rem 0';
                    } else {
                        // Other pages: proper horizontal padding for readability
                        pageContent.style.padding = '1rem 2rem';
                        pageContent.style.maxWidth = '100%';
                    }
                }
            }, 50);

            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-padding-output", "children", allow_duplicate=True),
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
    register_component_callbacks(app)

    # Register feature-specific callbacks
    register_feature_callbacks(app)

    # Register theme bridge callback
    # Register progressive loading callbacks
    # Import position_controls to register position change callback
    from depictio.dash.layouts import (
        position_controls,  # noqa: F401 - callback registers via decorator
    )
    from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
        register_progressive_loading_callbacks,
    )
    from depictio.dash.layouts.edit import (
        register_partial_data_button_callbacks,
        register_reset_button_callbacks,
    )

    # from depictio.dash.theme_utils import register_theme_bridge_callback

    # register_theme_bridge_callback(app)
    register_progressive_loading_callbacks(app)
    register_reset_button_callbacks(app)
    register_partial_data_button_callbacks(app)

    # Register analytics callbacks
    # from depictio.dash.components.analytics_tracker import register_analytics_callbacks

    # PERFORMANCE OPTIMIZATION: Admin analytics callbacks commented out to reduce initial load time
    # These 8 callbacks were adding ~50-100ms to the Dash renderer initialization (callback graph building)
    # They only need to run on /admin page, not on every page load
    # TODO: Re-enable with lazy loading when /admin page is accessed
    # from depictio.dash.layouts.admin_analytics_callbacks import register_admin_analytics_callbacks

    # register_analytics_callbacks(app)
    # register_admin_analytics_callbacks(app)  # Commented out for performance


def register_layout_callbacks(app):
    """
    Register callbacks for layout components.

    Args:
        app (dash.Dash): The Dash application instance
    """
    from depictio.dash.layouts.consolidated_api import register_consolidated_api_callbacks
    from depictio.dash.layouts.draggable import register_callbacks_draggable
    from depictio.dash.layouts.header import register_callbacks_header
    from depictio.dash.layouts.notes_footer import register_callbacks_notes_footer
    from depictio.dash.layouts.save import register_callbacks_save
    from depictio.dash.layouts.sidebar import register_sidebar_callbacks
    from depictio.dash.layouts.stepper import register_callbacks_stepper

    # from depictio.dash.layouts.stepper_parts.part_one import register_callbacks_stepper_part_one
    # from depictio.dash.layouts.stepper_parts.part_three import register_callbacks_stepper_part_three
    # from depictio.dash.layouts.stepper_parts.part_two import register_callbacks_stepper_part_two
    from depictio.dash.simple_theme import register_simple_theme_system

    # Register consolidated API callbacks first (highest priority)
    register_consolidated_api_callbacks(app)

    # Register layout callbacks
    register_callbacks_stepper(app)
    # register_callbacks_stepper_part_one(app)
    # register_callbacks_stepper_part_two(app)
    # register_callbacks_stepper_part_three(app)
    register_callbacks_header(app)
    register_callbacks_draggable(app)
    register_sidebar_callbacks(app)
    register_callbacks_notes_footer(app)
    register_callbacks_save(app)
    register_simple_theme_system(app)


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
    from depictio.dash.modules.multiqc_component.frontend import (
        register_callbacks_multiqc_component,
    )
    from depictio.dash.modules.table_component.frontend import register_callbacks_table_component
    from depictio.dash.modules.text_component.frontend import register_callbacks_text_component

    # Register component callbacks
    register_callbacks_card_component(app)
    register_callbacks_interactive_component(app)
    register_callbacks_figure_component(app)
    register_callbacks_jbrowse_component(app)
    register_callbacks_multiqc_component(app)
    register_callbacks_table_component(app)
    register_callbacks_text_component(app)


def register_feature_callbacks(app):
    """
    Register callbacks for specific features.

    Args:
        app (dash.Dash): The Dash application instance
    """
    from depictio.dash.layouts.add_component_simple import register_add_component_simple_callback
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
    from depictio.dash.layouts.remove_component_simple import (
        register_remove_component_simple_callback,
    )
    from depictio.dash.layouts.tokens_management import register_tokens_management_callbacks
    from depictio.dash.layouts.users_management import register_callbacks_users_management

    # Register feature callbacks
    register_add_component_simple_callback(app)  # Simple add-button callback
    register_remove_component_simple_callback(app)  # Patch-based remove-button callback
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
