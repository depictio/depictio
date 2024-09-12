from dash import html, dcc, Input, Output, State, ALL
import dash
from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging import logger
import httpx
from datetime import datetime


def register_callbacks_save(app):


    @app.callback(
        Output("dummy-output", "children"),
        Input("save-button-dashboard", "n_clicks"),
        State("draggable", "layouts"),
        State(
            {
                "type": "stored-metadata-component",
                "index": dash.dependencies.ALL,
            },
            "data",
        ),
        # State("draggable", "children"),
        State("stored-edit-dashboard-mode-button", "data"),
        State("stored-add-button", "data"),
        State({"type": "interactive-component-value", "index": ALL}, "value"),
        State("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def save_data_dashboard(
        n_clicks,
        stored_layout_data,
        stored_metadata,
        # children,
        edit_dashboard_mode_button,
        add_button,
        interactive_component_values,
        pathname,
        local_store,
    ):
        logger.info(f"URL pathname: {pathname}")
        if not local_store:
            logger.warn("User not logged in.")
            return dash.no_update

        TOKEN = local_store["access_token"]
        logger.info(f"save_data_dashboard - TOKEN: {TOKEN}")
        # current_user = fetch_user_from_token(TOKEN)

        if n_clicks:
            dashboard_id = pathname.split("/")[-1]

            logger.info(f"save_data_dashboard INSIDE")
            logger.info(f"stored-metadata-component: {stored_metadata}")

            # FIXME: check if some component are duplicated based on index value, if yes, remove them
            stored_metadata_indexes = list()
            for elem in stored_metadata:
                if elem["index"] in stored_metadata_indexes:
                    stored_metadata.remove(elem)
                else:
                    stored_metadata_indexes.append(elem["index"])

            # Get existing metadata for the dashboard
            dashboard_data_response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}", headers={"Authorization": f"Bearer {TOKEN}"})
            if dashboard_data_response.status_code == 200:
                dashboard_data = dashboard_data_response.json()
                logger.info(f"save_data_dashboard - Dashboard data: {dashboard_data}")
                # Replace the existing metadata with the new metadata
                dashboard_data["stored_metadata"] = stored_metadata
                dashboard_data["stored_layout_data"] = stored_layout_data
                dashboard_data["stored_edit_dashboard_mode_button"] = edit_dashboard_mode_button
                dashboard_data["stored_add_button"] = add_button
                current_time = datetime.now()
                dashboard_data["last_saved_ts"] = str(current_time)

                logger.info(f"save_data_dashboard - Dashboard data: {dashboard_data}")

                logger.info(f"Dashboard data: {dashboard_data}")

                response = httpx.post(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}",
                    json=dashboard_data,
                    headers={
                        "Authorization": f"Bearer {TOKEN}",
                    },
                )
                if response.status_code == 200:
                    logger.warn("Dashboard data saved successfully.")
                else:
                    logger.warn(f"Failed to save dashboard data: {response.json()}")

                # Screenshot the dashboard
                screenshot_response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/screenshot/{dashboard_id}",
                    headers={
                        "Authorization": f"Bearer {TOKEN}",
                    },
                )
                if screenshot_response.status_code == 200:
                    logger.warn("Dashboard screenshot saved successfully.")
                else:
                    logger.warn(f"Failed to save dashboard screenshot: {screenshot_response.json()}")

                return []

            else:
                logger.warn(f"Failed to fetch dashboard data: {dashboard_data_response.json()}")
                return []

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