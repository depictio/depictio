"""
Component editing navigation system.

This module handles navigation to the component editing stepper page.
When clicking the edit action icon on a component, it extracts the component UUID
and navigates to the dedicated stepper page where users can modify their component.
"""

from dash import ALL, Input, Output, State
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger


def register_edit_component_simple_callback(app):
    """Register the component editing navigation callback."""

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "edit-box-button", "index": ALL}, "n_clicks"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def navigate_to_edit_component(n_clicks_list, current_pathname):
        """
        Navigate to the component editing stepper page.

        Extracts the component UUID from the edit button that was clicked
        and navigates to the stepper page where the user can modify their
        component through the multi-step wizard with pre-populated settings.

        Args:
            n_clicks_list: List of n_clicks from all edit buttons (pattern-matched)
            current_pathname: Current URL pathname (e.g., "/dashboard/{id}")

        Returns:
            str: New pathname to navigate to (e.g., "/dashboard/{id}/component/edit/{uuid}")
        """
        from dash import ctx

        # Log for debugging URL redirection issues
        logger.info(
            f"🔍 EDIT BUTTON CALLBACK - triggered_id: {ctx.triggered_id}, pathname: {current_pathname}"
        )

        if not ctx.triggered_id or not isinstance(ctx.triggered_id, dict):
            logger.warning("⚠️ No valid trigger ID found")
            raise PreventUpdate

        # Check if any button was actually clicked
        if not any(n_clicks_list):
            logger.warning("⚠️ No button clicks detected")
            raise PreventUpdate

        # Extract component_id from the button that was clicked
        component_id = ctx.triggered_id["index"]

        logger.info(f"✏️ EDIT BUTTON - Component ID: {component_id}")

        # Extract dashboard_id from current pathname using robust parsing
        # Expected URL patterns:
        # - Normal dashboard: /dashboard/{dashboard_id}
        # - Stepper page: /dashboard/{dashboard_id}/component/add/{component_id}
        dashboard_id = None
        if current_pathname:
            parts = current_pathname.split("/")
            # parts = ['', 'dashboard', '{dashboard_id}', ...]
            if len(parts) >= 3 and parts[1] == "dashboard":
                dashboard_id = parts[2]  # Always extract from position 2

        if not dashboard_id:
            logger.warning(f"⚠️ Could not extract dashboard_id from pathname: {current_pathname}")
            raise PreventUpdate

        # Build edit stepper page URL
        edit_url = f"/dashboard/{dashboard_id}/component/edit/{component_id}"

        logger.info(
            f"✨ NAVIGATE TO EDIT STEPPER - Dashboard: {dashboard_id}, Component: {component_id}"
        )
        logger.info(f"  🔗 URL: {edit_url}")

        return edit_url

    logger.info("✅ Component editing navigation callback registered")
