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
    """
    Register the component editing navigation callback.

    Navigates to the component editing stepper page when the edit button is clicked.
    Preserves the app prefix (dashboard vs dashboard-edit) for proper routing.
    """

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "edit_box_button", "index": ALL}, "n_clicks"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def navigate_to_edit_component(n_clicks_list, current_pathname):
        """
        Navigate to the component editing stepper page.

        Args:
            n_clicks_list: List of n_clicks for all edit buttons (pattern-matching callback)
            current_pathname: Current URL pathname (e.g., "/dashboard/{id}" or "/dashboard-edit/{id}")

        Returns:
            str: New pathname to navigate to (e.g., "/dashboard-edit/{id}/component/edit/{uuid}")
        """
        from dash import ctx

        # EARLY EXIT: Don't process on component add pages
        if current_pathname and "/component/add/" in current_pathname:
            logger.info("🔒 On component add page - skipping edit button callback")
            raise PreventUpdate

        # Log for debugging URL redirection issues
        logger.info(
            f"🔍 EDIT BUTTON CALLBACK - n_clicks: {n_clicks_list}, pathname: {current_pathname}"
        )
        logger.info(
            f"🔍 EDIT BUTTON CALLBACK - triggered_id: {ctx.triggered_id}, triggered: {ctx.triggered}"
        )

        # GUARD: Check if any button was actually clicked (not just rendered with n_clicks=0)
        if not n_clicks_list or not any(n_clicks_list):
            logger.info("🚫 EDIT BUTTON - No actual clicks detected, preventing update")
            raise PreventUpdate

        # Check if callback was triggered by an edit button
        if not ctx.triggered_id:
            raise PreventUpdate

        # Extract component_id from triggered button
        if isinstance(ctx.triggered_id, dict) and ctx.triggered_id.get("type") == "edit_box_button":
            component_id = ctx.triggered_id.get("index")
            logger.info(f"📝 EDIT BUTTON - Component ID: {component_id}")
        else:
            logger.warning("⚠️ Edit button callback triggered by non-edit_box_button element")
            raise PreventUpdate

        if not component_id:
            logger.warning("⚠️ Could not extract component_id from triggered button")
            raise PreventUpdate

        # Extract dashboard_id from current pathname using robust parsing
        # Expected URL patterns:
        # - Viewer app: /dashboard/{dashboard_id}
        # - Editor app: /dashboard-edit/{dashboard_id}
        dashboard_id = None
        app_prefix = None  # Will be "dashboard" or "dashboard-edit"
        if current_pathname:
            parts = current_pathname.split("/")
            # parts = ['', 'dashboard' or 'dashboard-edit', '{dashboard_id}', ...]
            if len(parts) >= 3 and parts[1] in ["dashboard", "dashboard-edit"]:
                app_prefix = parts[1]
                dashboard_id = parts[2]  # Always extract from position 2

        if not dashboard_id or not app_prefix:
            logger.warning(f"⚠️ Could not extract dashboard_id from pathname: {current_pathname}")
            raise PreventUpdate

        # Build edit stepper page URL (preserves viewer/editor app prefix)
        edit_url = f"/{app_prefix}/{dashboard_id}/component/edit/{component_id}"

        logger.info(
            f"✏️ NAVIGATE TO EDIT STEPPER - Dashboard: {dashboard_id}, Component: {component_id}"
        )
        logger.info(f"  🔗 URL: {edit_url}")

        return edit_url

    logger.info("✅ Component editing navigation callback registered")
