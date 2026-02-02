"""
Image Component - Edit/Save Callbacks

This module contains callbacks for saving image component changes.
These callbacks are lazy-loaded only when entering edit mode.

Callbacks:
- save_image_edit: Save image component changes to dashboard
"""

from __future__ import annotations

from typing import Any

import dash
from dash import ALL, Input, Output, State, ctx

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_get_dashboard, api_call_save_dashboard


def register_image_edit_callback(app):
    """Register edit save callback for image component."""

    @app.callback(
        Output("notification-container", "sendNotifications", allow_duplicate=True),
        Input({"type": "btn-save-edit-image", "index": ALL}, "n_clicks"),
        State({"type": "image-input", "index": ALL}, "value"),
        State({"type": "image-dropdown-column", "index": ALL}, "value"),
        State({"type": "image-s3-base-folder", "index": ALL}, "value"),
        State({"type": "workflow-selection-label", "index": ALL}, "value"),
        State({"type": "datacollection-selection-label", "index": ALL}, "value"),
        State({"type": "btn-save-edit-image", "index": ALL}, "id"),
        State("edit-page-context", "data"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def save_image_edit(
        n_clicks_list: list[int | None],
        title_list: list[str | None],
        image_column_list: list[str | None],
        s3_base_folder_list: list[str | None],
        wf_id_list: list[str | None],
        dc_id_list: list[str | None],
        button_ids: list[dict[str, str]],
        edit_context: dict[str, Any] | None,
        local_data: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """
        Save image component changes to dashboard.

        This callback is triggered when the save button is clicked on the
        image component edit page. It updates the component metadata in the
        dashboard and saves to the database.

        Args:
            n_clicks_list: List of click counts for all image save buttons
            title_list: List of titles for all image components
            image_column_list: List of selected image columns
            s3_base_folder_list: List of S3 base folder paths
            wf_id_list: List of workflow IDs
            dc_id_list: List of data collection IDs
            button_ids: List of button IDs
            edit_context: Edit page context with dashboard_id and component_id
            local_data: Local storage data with access token

        Returns:
            List of notification dicts for success/failure feedback
        """
        from dash_iconify import DashIconify

        # Check if any button was clicked
        if not n_clicks_list or not any(n_clicks_list):
            raise dash.exceptions.PreventUpdate

        # Find which button was clicked
        triggered_id = ctx.triggered_id
        if not triggered_id:
            raise dash.exceptions.PreventUpdate

        # Find the index of the clicked button
        clicked_idx = None
        for i, btn_id in enumerate(button_ids):
            if btn_id == triggered_id:
                clicked_idx = i
                break

        if clicked_idx is None:
            raise dash.exceptions.PreventUpdate

        # Extract values for the clicked component
        n_clicks = n_clicks_list[clicked_idx] if clicked_idx < len(n_clicks_list) else None
        title = title_list[clicked_idx] if clicked_idx < len(title_list) else None
        image_column = (
            image_column_list[clicked_idx] if clicked_idx < len(image_column_list) else None
        )
        s3_base_folder = (
            s3_base_folder_list[clicked_idx] if clicked_idx < len(s3_base_folder_list) else None
        )
        wf_id = wf_id_list[clicked_idx] if clicked_idx < len(wf_id_list) else None
        dc_id = dc_id_list[clicked_idx] if clicked_idx < len(dc_id_list) else None

        if not n_clicks:
            raise dash.exceptions.PreventUpdate

        # Validate required data
        if not local_data or not local_data.get("access_token"):
            return [
                {
                    "id": "image-save-error",
                    "title": "Error",
                    "message": "Authentication required",
                    "color": "red",
                    "icon": DashIconify(icon="mdi:alert-circle", width=20),
                }
            ]

        if not edit_context:
            return [
                {
                    "id": "image-save-error",
                    "title": "Error",
                    "message": "Edit context not found",
                    "color": "red",
                    "icon": DashIconify(icon="mdi:alert-circle", width=20),
                }
            ]

        dashboard_id = edit_context.get("dashboard_id")
        component_id = edit_context.get("component_id")

        if not dashboard_id or not component_id:
            return [
                {
                    "id": "image-save-error",
                    "title": "Error",
                    "message": "Missing dashboard or component ID",
                    "color": "red",
                    "icon": DashIconify(icon="mdi:alert-circle", width=20),
                }
            ]

        # Validate required fields
        if not image_column:
            return [
                {
                    "id": "image-save-error",
                    "title": "Validation Error",
                    "message": "Image column is required",
                    "color": "yellow",
                    "icon": DashIconify(icon="mdi:alert", width=20),
                }
            ]

        try:
            TOKEN = local_data["access_token"]

            # Fetch current dashboard data
            dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)

            if not dashboard_data:
                return [
                    {
                        "id": "image-save-error",
                        "title": "Error",
                        "message": "Dashboard not found",
                        "color": "red",
                        "icon": DashIconify(icon="mdi:alert-circle", width=20),
                    }
                ]

            # Find and update the component in stored_metadata
            stored_metadata = dashboard_data.get("stored_metadata", [])
            component_found = False

            for i, meta in enumerate(stored_metadata):
                meta_id = str(meta.get("component_id", meta.get("index", meta.get("_id"))))
                if meta_id == str(component_id):
                    # Update component metadata
                    stored_metadata[i]["title"] = title or "Image Gallery"
                    stored_metadata[i]["image_column"] = image_column
                    stored_metadata[i]["s3_base_folder"] = s3_base_folder or ""
                    stored_metadata[i]["wf_id"] = wf_id
                    stored_metadata[i]["dc_id"] = dc_id
                    component_found = True
                    break

            if not component_found:
                return [
                    {
                        "id": "image-save-error",
                        "title": "Error",
                        "message": f"Component {component_id} not found",
                        "color": "red",
                        "icon": DashIconify(icon="mdi:alert-circle", width=20),
                    }
                ]

            # Save updated dashboard
            dashboard_data["stored_metadata"] = stored_metadata
            api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN)

            logger.info(f"Image component {component_id} saved successfully")

            return [
                {
                    "id": "image-save-success",
                    "title": "Saved",
                    "message": "Image component updated successfully",
                    "color": "green",
                    "icon": DashIconify(icon="mdi:check-circle", width=20),
                }
            ]

        except Exception as e:
            logger.error(f"Error saving image component: {e}")
            return [
                {
                    "id": "image-save-error",
                    "title": "Error",
                    "message": f"Failed to save: {str(e)}",
                    "color": "red",
                    "icon": DashIconify(icon="mdi:alert-circle", width=20),
                }
            ]
