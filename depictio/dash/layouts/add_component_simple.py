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
    logger.info("=" * 80)
    logger.info("📋 REGISTERING ADD COMPONENT CALLBACK")
    logger.info(f"   App name: {app.config.get('name', 'Unknown')}")
    logger.info("=" * 80)

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Output("stored-add-button", "data", allow_duplicate=True),
        Input("add-button", "n_clicks"),
        State("url", "pathname"),
        State("stored-add-button", "data"),
        prevent_initial_call=True,
    )
    def navigate_to_add_component(n_clicks, current_pathname, stored_clicks):
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
        from dash import ctx

        # EARLY EXIT: Don't process on component edit pages
        if current_pathname and "/component/edit/" in current_pathname:
            logger.info("🔒 On component edit page - skipping add button callback")
            raise PreventUpdate

        # CRITICAL: Log immediately when callback is entered
        logger.info("=" * 80)
        logger.info("🚀 ADD BUTTON CALLBACK ENTERED")
        logger.info("=" * 80)

        # Log for debugging URL redirection issues
        logger.info(
            f"🔍 ADD BUTTON CALLBACK - n_clicks: {n_clicks}, stored_clicks: {stored_clicks}, pathname: {current_pathname}"
        )
        logger.info(
            f"🔍 ADD BUTTON CALLBACK - triggered_id: {ctx.triggered_id}, triggered: {ctx.triggered}"
        )

        if not n_clicks:
            raise PreventUpdate

        # Extract count from stored_clicks (it's a dict with structure: {"count": 0, "initialized": False, "_id": ""})
        stored_count = (
            stored_clicks.get("count", 0)
            if isinstance(stored_clicks, dict)
            else (stored_clicks or 0)
        )

        # GUARD: Handle localStorage stale data
        # If stored_count > n_clicks, it means localStorage has stale data from previous session
        # In this case, we should reset and allow the click
        if stored_count > n_clicks:
            logger.info(
                f"🔄 ADD BUTTON - Stale stored_count detected (stored={stored_count}, current={n_clicks}), resetting"
            )
            # Don't prevent update - allow the click and reset the stored count
        # GUARD: Prevent duplicate processing of same click (fixes URL re-navigation after stepper return)
        # This happens when returning from stepper - the dashboard re-renders with add-button having n_clicks=N
        # Without this check, the callback would trigger again and navigate to a NEW stepper URL
        elif n_clicks == stored_count:
            logger.info(
                f"🚫 ADD BUTTON - Click already processed (n_clicks={n_clicks}, stored_count={stored_count})"
            )
            raise PreventUpdate

        # GUARD: Don't navigate if already on a stepper page (prevents recursive navigation)
        if current_pathname and "/component/add/" in current_pathname:
            logger.warning(
                "⚠️ Already on stepper page - preventing recursive navigation from stepper to stepper"
            )
            raise PreventUpdate

        # Extract dashboard_id from current pathname using robust parsing
        # Expected URL patterns:
        # - Viewer app: /dashboard/{dashboard_id}
        # - Editor app: /dashboard-edit/{dashboard_id}
        # - Stepper page (viewer): /dashboard/{dashboard_id}/component/add/{component_id}
        # - Stepper page (editor): /dashboard-edit/{dashboard_id}/component/add/{component_id}
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

        # Generate new component ID
        component_id = str(uuid4())

        # Build stepper page URL (preserves viewer/editor app prefix)
        stepper_url = f"/{app_prefix}/{dashboard_id}/component/add/{component_id}"

        logger.info(
            f"✨ NAVIGATE TO STEPPER - Dashboard: {dashboard_id}, Component: {component_id}"
        )
        logger.info(f"  🔗 URL: {stepper_url}")
        logger.info(f"  📝 Storing n_clicks: {n_clicks}")

        # Return both the URL and the updated stored clicks dict (maintaining the dict structure)
        return stepper_url, {"count": n_clicks, "initialized": True, "_id": ""}

    logger.info("✅ Component creation navigation callback registered")
