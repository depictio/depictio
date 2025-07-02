from datetime import datetime

import dash
from dash import ALL, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_fetch_user_from_token,
    api_call_get_dashboard,
    api_call_save_dashboard,
    api_call_screenshot_dashboard,
)


def register_callbacks_save(app):
    @app.callback(
        Output("dummy-output", "children"),
        Input("save-button-dashboard", "n_clicks"),
        Input("draggable", "layouts"),
        State(
            {
                "type": "stored-metadata-component",
                "index": ALL,
            },
            "data",
        ),
        State("stored-edit-dashboard-mode-button", "data"),
        Input("edit-dashboard-mode-button", "checked"),
        Input("edit-components-mode-button", "checked"),
        State("stored-add-button", "data"),
        State({"type": "interactive-component-value", "index": ALL}, "value"),
        State("url", "pathname"),
        State("local-store", "data"),
        Input(
            {
                "type": "btn-done",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input(
            {
                "type": "btn-done-edit",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input(
            {
                "type": "duplicate-box-button",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input(
            {"type": "remove-box-button", "index": ALL},
            "n_clicks",
        ),
        Input("remove-all-components-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def save_data_dashboard(
        n_clicks,
        stored_layout_data,
        stored_metadata,
        edit_dashboard_mode_button,
        edit_dashboard_mode_button_checked,
        edit_components_mode_button_checked,
        add_button,
        interactive_component_values,
        pathname,
        local_store,
        n_clicks_done,
        n_clicks_done_edit,
        n_clicks_duplicate,
        n_clicks_remove,
        n_clicks_remove_all,
    ):
        logger.info("Saving dashboard data...")
        # Early return if user is not logged in or on auth page
        if not local_store or pathname == "/auth":
            logger.warning("User not logged in or on auth page.")
            return dash.no_update

        # Validate user authentication
        TOKEN = local_store["access_token"]
        current_user = api_call_fetch_user_from_token(TOKEN)
        if not current_user:
            logger.warning("User not found.")
            return dash.no_update

        # Extract dashboard ID from pathname
        dashboard_id = pathname.split("/")[-1]

        # Fetch dashboard data using API call with proper timeout
        dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
        if not dashboard_data:
            logger.error(f"Failed to fetch dashboard data for {dashboard_id}")
            return dash.no_update

        # Check user permissions
        owner_ids = [str(e["id"]) for e in dashboard_data.get("permissions", {}).get("owners", [])]
        if str(current_user.id) not in owner_ids:
            logger.warning("User does not have permission to edit & save this dashboard.")
            return dash.no_update

        # Determine trigger context
        from dash import ctx

        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.debug(f"Triggered ID: {triggered_id}")

        # Define save-triggering conditions
        save_triggers = [
            "save-button-dashboard",
            "btn-done",
            "btn-done-edit",
            "duplicate-box-button",
            "remove-box-button",
            "remove-all-components-button",
            "edit-components-mode-button",
            "draggable",
        ]

        # Check if save should be triggered
        if (
            not any(trigger in triggered_id for trigger in save_triggers)
            or not edit_dashboard_mode_button_checked
        ):
            return dash.no_update

        # Deduplicate and clean metadata
        unique_metadata = []
        seen_indexes = set()

        # logger.info(f"Stored metadata: {stored_metadata}")
        for elem in stored_metadata:
            if elem["index"] not in seen_indexes:
                unique_metadata.append(elem)
                seen_indexes.add(elem["index"])
        # logger.info(f"Unique metadata: {unique_metadata}")
        # logger.info(f"seen_indexes: {seen_indexes}")
        # Remove child components for edit mode
        if "btn-done-edit" in triggered_id:
            unique_metadata = [elem for elem in unique_metadata if "parent_index" not in elem]
            # logger.info(f"Unique metadata after removing child components: {unique_metadata}")

        # Use draggable layout metadata if triggered by draggable
        if "draggable" in triggered_id:
            unique_metadata = dashboard_data.get("stored_metadata", unique_metadata)
            # logger.info(f"Unique metadata after using draggable layout metadata: {unique_metadata}")

        updated_dashboard_data = {
            "stored_metadata": unique_metadata,
            "stored_layout_data": stored_layout_data,
            "stored_edit_dashboard_mode_button": edit_dashboard_mode_button,
            "stored_add_button": add_button,
            "buttons_data": {
                "edit_components_button": edit_components_mode_button_checked,
                "add_components_button": add_button,
                "edit_dashboard_mode_button": edit_dashboard_mode_button_checked,
            },
            "last_saved_ts": str(datetime.now()),
        }
        # logger.info(f"Updated dashboard data: {updated_dashboard_data}")

        # Update dashboard data
        dashboard_data.update(updated_dashboard_data)
        # logger.info(f"Updated dashboard data: {dashboard_data}")

        # Save dashboard data using API call with proper timeout
        save_success = api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN)
        if not save_success:
            logger.error(f"Failed to save dashboard data for {dashboard_id}")

        # Screenshot the dashboard if save button was clicked
        if n_clicks and save_success:
            screenshot_success = api_call_screenshot_dashboard(dashboard_id)
            if not screenshot_success:
                logger.warning(f"Failed to save dashboard screenshot for {dashboard_id}")

        return dash.no_update

    @app.callback(
        Output("success-modal-dashboard", "is_open"),
        [
            Input("save-button-dashboard", "n_clicks"),
            Input("success-modal-close", "n_clicks"),
        ],
        [State("success-modal-dashboard", "is_open")],
    )
    def toggle_success_modal_dashboard(n_save, n_close, is_open):
        ctx = dash.callback_context

        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger_id == "save-button-dashboard":
            if n_save is None or n_save == 0:
                raise dash.exceptions.PreventUpdate
            else:
                return True

        elif trigger_id == "success-modal-close":
            if n_close is None or n_close == 0:
                raise dash.exceptions.PreventUpdate
            else:
                return False

        return is_open
