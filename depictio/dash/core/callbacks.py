"""
Callback registration for the Depictio Dash application.
"""

from dash import Input, Output, ctx

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.core.auth import process_authentication


def register_main_callback(app):
    """
    Register the main callback for page routing and authentication.

    Args:
        app (dash.Dash): The Dash application instance
    """

    @app.callback(
        Output("page-content", "children"),
        Output("header", "children"),
        Output("url", "pathname"),
        Output("local-store", "data", allow_duplicate=True),
        [Input("url", "pathname"), Input("local-store", "data")],
        prevent_initial_call=True,
    )
    def display_page(pathname, local_data):
        """
        Main callback for handling page routing and authentication.

        Args:
            pathname (str): Current URL pathname
            local_data (dict): Local storage data containing authentication information

        Returns:
            tuple: (page_content, header, pathname, local_data)
        """
        trigger = ctx.triggered_id
        logger.debug(f"Trigger: {trigger}")

        # Process authentication and return appropriate content
        return process_authentication(pathname, local_data)


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


def register_layout_callbacks(app):
    """
    Register callbacks for layout components.

    Args:
        app (dash.Dash): The Dash application instance
    """
    from depictio.dash.layouts.draggable import register_callbacks_draggable
    from depictio.dash.layouts.header import register_callbacks_header
    from depictio.dash.layouts.save import register_callbacks_save
    from depictio.dash.layouts.sidebar import register_sidebar_callbacks
    from depictio.dash.layouts.stepper import register_callbacks_stepper
    from depictio.dash.layouts.stepper_parts.part_one import \
        register_callbacks_stepper_part_one
    from depictio.dash.layouts.stepper_parts.part_three import \
        register_callbacks_stepper_part_three
    from depictio.dash.layouts.stepper_parts.part_two import \
        register_callbacks_stepper_part_two

    # Register layout callbacks
    register_callbacks_stepper(app)
    register_callbacks_stepper_part_one(app)
    register_callbacks_stepper_part_two(app)
    register_callbacks_stepper_part_three(app)
    register_callbacks_header(app)
    register_callbacks_draggable(app)
    register_sidebar_callbacks(app)
    register_callbacks_save(app)


def register_component_callbacks(app):
    """
    Register callbacks for UI components.

    Args:
        app (dash.Dash): The Dash application instance
    """
    from depictio.dash.modules.card_component.frontend import \
        register_callbacks_card_component
    from depictio.dash.modules.figure_component.frontend import \
        register_callbacks_figure_component
    from depictio.dash.modules.interactive_component.frontend import \
        register_callbacks_interactive_component
    from depictio.dash.modules.jbrowse_component.frontend import \
        register_callbacks_jbrowse_component
    from depictio.dash.modules.table_component.frontend import \
        register_callbacks_table_component

    # Register component callbacks
    register_callbacks_card_component(app)
    register_callbacks_interactive_component(app)
    register_callbacks_figure_component(app)
    register_callbacks_jbrowse_component(app)
    register_callbacks_table_component(app)


def register_feature_callbacks(app):
    """
    Register callbacks for specific features.

    Args:
        app (dash.Dash): The Dash application instance
    """
    from depictio.dash.layouts.admin_management import register_admin_callbacks
    from depictio.dash.layouts.dashboards_management import \
        register_callbacks_dashboards_management
    from depictio.dash.layouts.profile import register_profile_callbacks
    from depictio.dash.layouts.projects import (register_projects_callbacks,
                                                register_workflows_callbacks)
    from depictio.dash.layouts.projectwise_user_management import \
        register_projectwise_user_management_callbacks
    from depictio.dash.layouts.tokens_management import \
        register_tokens_management_callbacks
    from depictio.dash.layouts.users_management import \
        register_callbacks_users_management

    # Register feature callbacks
    register_callbacks_dashboards_management(app)
    register_profile_callbacks(app)
    register_callbacks_users_management(app)
    register_tokens_management_callbacks(app)
    register_workflows_callbacks(app)
    register_projects_callbacks(app)
    register_admin_callbacks(app)
    register_projectwise_user_management_callbacks(app)
