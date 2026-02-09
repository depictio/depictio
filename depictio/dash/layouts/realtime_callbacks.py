"""
Real-time WebSocket callbacks for dashboard updates.

Provides callbacks for:
- WebSocket URL construction (clientside)
- Message parsing (clientside)
- Notification display (serverside)
"""

from dash import Dash, Input, Output, State, no_update

from depictio.api.v1.configs.logging_init import logger


def register_realtime_callbacks(app: Dash) -> None:
    """
    Register all real-time WebSocket callbacks for a Dash app.

    Should be called for both viewer and editor apps.
    """
    register_websocket_url_callback(app)
    register_websocket_message_callback(app)
    register_data_update_notification_callback(app)


def register_websocket_url_callback(app: Dash) -> None:
    """
    Register clientside callback to construct WebSocket URL.

    Adapts to the current protocol (ws/wss) and includes JWT token
    and dashboard ID as query parameters.
    """
    app.clientside_callback(
        """
        function(pathname, localStore) {
            // Check if we have JWT token
            if (!localStore || !localStore.access_token) {
                console.log('[WebSocket] No access token, skipping connection');
                return window.dash_clientside.no_update;
            }

            // Extract dashboard ID from pathname
            // Patterns: /dashboard/{id} or /dashboard/{id}/edit
            const match = pathname ? pathname.match(/\\/dashboard\\/([a-f0-9]+)/) : null;
            if (!match) {
                console.log('[WebSocket] Not on a dashboard page, skipping');
                return window.dash_clientside.no_update;
            }

            const dashboardId = match[1];
            const token = localStore.access_token;

            // Construct WebSocket URL
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const host = window.location.hostname;

            // Build base URL - in production (HTTPS with no port), use standard ports
            // In development, use explicit port (8058 for API, or current port)
            let baseUrl;
            if (window.location.protocol === 'https:' && !window.location.port) {
                // Production HTTPS: use standard port (443), no explicit port in URL
                baseUrl = `${protocol}//${host}`;
            } else if (window.location.port && window.location.port !== '5080') {
                // Development with custom port (e.g., 8058)
                baseUrl = `${protocol}//${host}:${window.location.port}`;
            } else {
                // Development on Dash port (5080): connect to API port (8058)
                baseUrl = `${protocol}//${host}:8058`;
            }

            const wsUrl = `${baseUrl}/depictio/api/v1/events/ws?token=${token}&dashboard_id=${dashboardId}`;

            console.log('[WebSocket] Connecting to:', wsUrl.replace(/token=[^&]+/, 'token=***'));
            return wsUrl;
        }
        """,
        Output("ws", "url"),
        Input("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )


def register_websocket_message_callback(app: Dash) -> None:
    """
    Register clientside callback to parse WebSocket messages.

    Parses incoming JSON messages and stores them in ws-message-store.
    """
    app.clientside_callback(
        """
        function(msg) {
            if (!msg) return window.dash_clientside.no_update;

            console.log('[WebSocket] Received message:', msg);

            try {
                const data = JSON.parse(msg.data);
                console.log('[WebSocket] Parsed data:', data);

                // Store the parsed message
                const storeData = {
                    event_type: data.event_type,
                    timestamp: data.timestamp || new Date().toISOString(),
                    dashboard_id: data.dashboard_id,
                    data_collection_id: data.data_collection_id,
                    payload: data.payload || {},
                    received_at: Date.now()
                };

                console.log('[WebSocket] Storing message:', storeData);
                return storeData;

            } catch(e) {
                console.error('[WebSocket] Parse error:', e);
                return window.dash_clientside.no_update;
            }
        }
        """,
        Output("ws-message-store", "data"),
        Input("ws", "message"),
        prevent_initial_call=True,
    )


def register_data_update_notification_callback(app: Dash) -> None:
    """
    Register callback to show notification when data is updated.

    Displays a notification when a data_collection_updated event is received,
    prompting the user to refresh the dashboard.
    """

    @app.callback(
        Output("notification-container", "sendNotifications", allow_duplicate=True),
        Input("ws-message-store", "data"),
        State("ws-connection-config", "data"),
        prevent_initial_call=True,
    )
    def show_data_update_notification(
        ws_data: dict | None, config: dict | None
    ) -> list[dict] | type[no_update]:
        """Show notification when data collection is updated."""
        if not ws_data:
            return no_update

        event_type = ws_data.get("event_type", "")
        valid_events = {"data_collection_updated", "data_collection_created"}

        if event_type not in valid_events:
            return no_update

        if config and config.get("paused"):
            logger.debug("Real-time notifications paused, skipping")
            return no_update

        payload = ws_data.get("payload", {})
        dc_tag = payload.get("data_collection_tag", "Data")
        operation = payload.get("operation", "updated")
        dc_id = ws_data.get("data_collection_id", "unknown")
        received_at = ws_data.get("received_at", 0)

        logger.info(f"Real-time notification: {dc_tag} {operation}")
        return [
            {
                "action": "show",
                "id": f"data-update-{dc_id}-{received_at}",
                "title": "Data Updated",
                "message": f"{dc_tag} has been {operation}. Refresh to see changes.",
                "color": "blue",
                "autoClose": 8000,
            }
        ]
