import httpx
from datetime import datetime
import os, sys
from dash import html, dcc, Input, Output, State, ALL
import dash
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token


def register_callbacks_save(app):
    @app.callback(
        Output("dummy-output", "children"),
        Input("save-button-dashboard", "n_clicks"),
        Input("draggable", "layouts"),
        State(
            {
                "type": "stored-metadata-component",
                "index": dash.dependencies.ALL,
            },
            "data",
        ),
        # State("draggable", "children"),
        State("stored-edit-dashboard-mode-button", "data"),
        Input("edit-dashboard-mode-button", "checked"),
        Input("edit-components-mode-button", "checked"),
        State("stored-add-button", "data"),
        State({"type": "interactive-component-value", "index": ALL}, "value"),
        State("url", "pathname"),
        State("local-store", "data"),
        # Input("interval-component", "n_intervals"),
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
        # children,
        edit_dashboard_mode_button,
        edit_dashboard_mode_button_checked,
        edit_components_mode_button_checked,
        add_button,
        interactive_component_values,
        pathname,
        local_store,
        # n_intervals,
        n_clicks_done,
        n_clicks_done_edit,
        n_clicks_duplicate,
        n_clicks_remove,
        n_clicks_remove_all,
    ):
        logger.debug(f"URL pathname: {pathname}")
        if not local_store:
            logger.warning("User not logged in.")
            return dash.no_update

        TOKEN = local_store["access_token"]
        logger.debug(f"save_data_dashboard - TOKEN: {TOKEN}")
        # current_user = fetch_user_from_token(TOKEN)

        # Check user status
        current_user = fetch_user_from_token(TOKEN)
        if not current_user:
            logger.warning("User not found.")
            return dash.no_update

        dashboard_id = pathname.split("/")[-1]

        # Get existing metadata for the dashboard
        dashboard_data_response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}", headers={"Authorization": f"Bearer {TOKEN}"})
        if dashboard_data_response.status_code == 200:
            dashboard_data = dashboard_data_response.json()
            logger.debug(f"save_data_dashboard - Dashboard data: {dashboard_data}")

            # Check user permissions
            if str(current_user.id) not in [e["_id"] for e in dashboard_data["permissions"]["owners"]]:
                logger.warning("User does not have permission to edit & save this dashboard.")
                return dash.no_update

            from dash import ctx

            triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
            logger.info(f"save_data_dashboard - Triggered ID: {triggered_id}")

            # if n_clicks:
            if (
                (triggered_id == "save-button-dashboard")
                or ("btn-done" in triggered_id)
                or ("btn-done-edit" in triggered_id)
                or ("duplicate-box-button" in triggered_id)
                or ("remove-box-button" in triggered_id)
                or ("remove-all-components-button" in triggered_id)
                or (triggered_id == "edit-components-mode-button")
                or (triggered_id == "draggable")
            ) and edit_dashboard_mode_button_checked:
                # if n_clicks or n_intervals:

                logger.debug(f"save_data_dashboard INSIDE")
                logger.info(f"stored-metadata-component: {stored_metadata}")

                # FIXME: check if some component are duplicated based on index value, if yes, remove them
                stored_metadata_indexes = list()
                for elem in stored_metadata:
                    if elem["index"] in stored_metadata_indexes:
                        stored_metadata.remove(elem)
                    else:
                        stored_metadata_indexes.append(elem["index"])

                    if "btn-done-edit" in triggered_id:
                        parent_indexes = [elem["parent_index"] for elem in stored_metadata if "parent_index" in elem]
                        stored_metadata = [elem for elem in stored_metadata if elem["index"] not in parent_indexes]

                    # Replace the existing metadata with the new metadata

                    if "draggable" in triggered_id:
                        stored_metadata = dashboard_data["stored_metadata"]

                    dashboard_data["stored_metadata"] = stored_metadata
                    dashboard_data["stored_layout_data"] = stored_layout_data
                    dashboard_data["stored_edit_dashboard_mode_button"] = edit_dashboard_mode_button
                    dashboard_data["stored_add_button"] = add_button
                    dashboard_data["buttons_data"]["edit_components_button"] = edit_components_mode_button_checked
                    dashboard_data["buttons_data"]["add_components_button"] = add_button
                    dashboard_data["buttons_data"]["edit_dashboard_mode_button"] = edit_dashboard_mode_button_checked

                    current_time = datetime.now()
                    dashboard_data["last_saved_ts"] = str(current_time)

                    logger.debug(f"save_data_dashboard - Dashboard data: {dashboard_data}")

                    logger.debug(f"Dashboard data: {dashboard_data}")

                    response = httpx.post(
                        f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}",
                        json=dashboard_data,
                        headers={
                            "Authorization": f"Bearer {TOKEN}",
                        },
                    )
                    if response.status_code == 200:
                        logger.info(f"Dashboard data saved successfully for dashboard {dashboard_id}.")
                    else:
                        logger.warning(f"Failed to save dashboard data: {response.json()}")

                    if n_clicks:
                        # Screenshot the dashboard
                        screenshot_response = httpx.get(
                            f"{API_BASE_URL}/depictio/api/v1/dashboards/screenshot/{dashboard_id}",
                            headers={
                                "Authorization": f"Bearer {TOKEN}",
                            },
                            timeout=60.0,  # Timeout set to 60 seconds
                        )
                        if screenshot_response.status_code == 200:
                            logger.info("Dashboard screenshot saved successfully.")
                        else:
                            logger.warning(f"Failed to save dashboard screenshot: {screenshot_response.json()}")

                        return dash.no_update

                    # else:
                    return dash.no_update

                else:
                    logger.warning(f"Failed to fetch dashboard data: {dashboard_data_response.json()}")
                    return dash.no_update

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
        # logger.info(trigger_id, n_save, n_close)

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
