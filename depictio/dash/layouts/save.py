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
        Input("draggable", "currentLayout"),
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
        # Early return if user is not logged in
        if not local_store:
            logger.warning("User not logged in.")
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
            logger.info("=== BTN-DONE-EDIT TRIGGERED - PROCESSING EDIT MODE ===")
            logger.info(f"Unique metadata BEFORE filtering: {len(unique_metadata)} items")
            for i, elem in enumerate(unique_metadata):
                logger.info(
                    f"Item {i}: index={elem.get('index')}, parent_index={elem.get('parent_index')}, component_type={elem.get('component_type')}"
                )

            # In edit mode, we need to:
            # 1. Find the edited component (has parent_index)
            # 2. Remove the original component (with index = parent_index)
            # 3. Add the edited component with parent_index removed
            original_count = len(unique_metadata)

            # Find the component being edited (it will have parent_index set)
            edited_components = [
                elem for elem in unique_metadata if elem.get("parent_index") is not None
            ]
            non_edited_components = [
                elem for elem in unique_metadata if elem.get("parent_index") is None
            ]

            logger.info(
                f"Found {len(edited_components)} edited components and {len(non_edited_components)} non-edited components"
            )

            # Log all component indices for debugging
            logger.info("=== ALL COMPONENTS BEFORE PROCESSING ===")
            for i, comp in enumerate(unique_metadata):
                logger.info(
                    f"Component {i}: index={comp.get('index')}, parent_index={comp.get('parent_index')}, type={comp.get('component_type')}, title={comp.get('title')}"
                )

            logger.info("=== EDITED COMPONENTS ===")
            for i, comp in enumerate(edited_components):
                logger.info(
                    f"Edited {i}: index={comp.get('index')}, parent_index={comp.get('parent_index')}, type={comp.get('component_type')}, title={comp.get('title')}"
                )

            logger.info("=== NON-EDITED COMPONENTS ===")
            for i, comp in enumerate(non_edited_components):
                logger.info(
                    f"Non-edited {i}: index={comp.get('index')}, parent_index={comp.get('parent_index')}, type={comp.get('component_type')}, title={comp.get('title')}"
                )

            # Process edited components
            for component in edited_components:
                parent_index = component.get("parent_index")
                component_index = component.get("index")

                logger.info(
                    f"Processing edited component: {component_index} (parent_index: {parent_index})"
                )
                logger.info(
                    f"Component data: type={component.get('component_type')}, title={component.get('title')}, aggregation={component.get('aggregation')}"
                )

                # Find and log the original component that will be removed
                original_component = None
                for elem in non_edited_components:
                    if elem.get("index") == parent_index:
                        original_component = elem
                        break

                if original_component:
                    logger.info(
                        f"Found original component to remove: index={original_component.get('index')}, type={original_component.get('component_type')}, title={original_component.get('title')}, aggregation={original_component.get('aggregation')}"
                    )
                else:
                    logger.warning(f"Could not find original component with index {parent_index}")

                # Remove the original component that was being edited
                non_edited_components = [
                    elem for elem in non_edited_components if elem.get("index") != parent_index
                ]
                logger.info(f"Removed original component with index {parent_index}")

                # Update the edited component's index to be the same as the original
                component["index"] = parent_index
                logger.info(
                    f"Updated edited component index from {component_index} to {parent_index}"
                )
                logger.info(
                    f"Updated component data: type={component.get('component_type')}, title={component.get('title')}, aggregation={component.get('aggregation')}"
                )

                # Remove parent_index from the component data before saving
                if "parent_index" in component:
                    del component["parent_index"]
                    logger.info(f"Removed parent_index from component {parent_index}")

            # Combine all components back together
            unique_metadata = non_edited_components + edited_components

            logger.info(
                f"Unique metadata AFTER processing: {len(unique_metadata)} items (removed {original_count - len(unique_metadata)} items)"
            )
            logger.info("=== FINAL COMPONENTS AFTER PROCESSING ===")
            for i, elem in enumerate(unique_metadata):
                logger.info(
                    f"Final item {i}: index={elem.get('index')}, parent_index={elem.get('parent_index')}, component_type={elem.get('component_type')}, title={elem.get('title')}, aggregation={elem.get('aggregation')}"
                )
            logger.info("=== BTN-DONE-EDIT PROCESSING COMPLETE ===")

        # Use draggable layout metadata if triggered by draggable
        if "draggable" in triggered_id:
            unique_metadata = dashboard_data.get("stored_metadata", unique_metadata)
            # logger.info(f"Unique metadata after using draggable layout metadata: {unique_metadata}")

        # Debug logging for layout data
        logger.info(f"🔍 SAVE DEBUG - stored_layout_data received: {stored_layout_data}")
        logger.info(f"🔍 SAVE DEBUG - type: {type(stored_layout_data)}")
        logger.info(f"🔍 SAVE DEBUG - triggered_id: {triggered_id}")

        # Ensure layout data is in list format - no backward compatibility
        if stored_layout_data is None:
            stored_layout_data = []
            logger.info("⚠️ SAVE DEBUG - stored_layout_data was None, set to empty list")

        # If layout data is empty but we have existing dashboard data, preserve the existing layout
        if not stored_layout_data and dashboard_data and dashboard_data.get("stored_layout_data"):
            existing_layout = dashboard_data.get("stored_layout_data")
            if isinstance(existing_layout, list):
                stored_layout_data = existing_layout
                logger.info(f"🔄 SAVE DEBUG - preserved existing layout: {stored_layout_data}")
            else:
                logger.warning(
                    f"⚠️ SAVE DEBUG - existing layout is not a list: {type(existing_layout)}"
                )

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
