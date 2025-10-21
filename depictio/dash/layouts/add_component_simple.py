"""
Component creation navigation system.

This module handles navigation to the component creation stepper page.
Instead of adding components directly to the dashboard, it generates a new UUID
and navigates to the dedicated stepper page where users can design their component.
"""

from uuid import uuid4

from dash import Input, Output, State
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger


def register_add_component_simple_callback(app):
    """Register the component creation navigation callback."""

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input("add-button", "n_clicks"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def navigate_to_add_component(n_clicks, current_pathname):
        """
        Navigate to the component creation stepper page.

        Generates a new UUID for the component and navigates to the stepper page
        where the user can design and configure their component through a
        multi-step wizard.

        Args:
            n_clicks: Number of times add-button was clicked
            current_pathname: Current URL pathname (e.g., "/dashboard/{id}")

        Returns:
            str: New pathname to navigate to (e.g., "/dashboard/{id}/component/add/{uuid}")
        """
        if not n_clicks:
            raise PreventUpdate

        # Extract dashboard_id from current pathname
        dashboard_id = current_pathname.split("/")[-1] if current_pathname else None
        if not dashboard_id:
            logger.warning("⚠️ Could not extract dashboard_id from pathname")
            raise PreventUpdate

        # Generate new component ID
        component_id = str(uuid4())

        # Build stepper page URL
        stepper_url = f"/dashboard/{dashboard_id}/component/add/{component_id}"

        logger.info(
            f"✨ NAVIGATE TO STEPPER - Dashboard: {dashboard_id}, Component: {component_id}"
        )
        logger.info(f"  🔗 URL: {stepper_url}")

        return stepper_url

    logger.info("✅ Component creation navigation callback registered")
