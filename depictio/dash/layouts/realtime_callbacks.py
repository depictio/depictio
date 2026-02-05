"""
Real-time WebSocket callbacks for dashboard updates.

Provides callbacks for:
- Native WebSocket management (clientside) - replaces dash-extensions WebSocket
- Message parsing (clientside)
- Notification display (serverside)

Note: We use native JavaScript WebSocket instead of dash-extensions WebSocket
because the dash-extensions component has two issues:
1. When url="" (empty string), it falls back to a malformed URL
2. The component doesn't support URL changes after mount
"""

from dash import Dash, Input, Output, State, no_update

from depictio.api.v1.configs.logging_init import logger


def register_realtime_callbacks(app: Dash) -> None:
    """
    Register all real-time WebSocket callbacks for a Dash app.

    Should be called for both viewer and editor apps.
    """
    register_native_websocket_callback(app)
    register_data_update_notification_callback(app)


def register_native_websocket_callback(app: Dash) -> None:
    """
    Register clientside callback to manage native WebSocket connection.

    This replaces the dash-extensions WebSocket component with direct JavaScript
    WebSocket management, giving us full control over connection lifecycle.

    The callback:
    1. Extracts dashboard ID from pathname
    2. Constructs the proper WebSocket URL (ws://host:8058/depictio/api/v1/events/ws)
    3. Manages WebSocket connection (creates new, closes old on URL change)
    4. Updates ws-message-store when messages are received
    """
    app.clientside_callback(
        """
        function(pathname, localStore, currentState) {
            console.log('[WebSocket] Callback fired! pathname:', pathname);

            // Extract dashboard ID from pathname
            // Patterns: /dashboard/{id} or /dashboard/{id}/edit
            const match = pathname ? pathname.match(/\\/dashboard\\/([a-f0-9]+)/) : null;
            if (!match) {
                console.log('[WebSocket] Not on a dashboard page, closing any existing connection');
                // Close existing connection if navigating away from dashboard
                if (window._depictioWs) {
                    window._depictioWs.close();
                    window._depictioWs = null;
                }
                return window.dash_clientside.no_update;
            }

            const dashboardId = match[1];

            // Get token if available (optional for unauthenticated mode)
            const token = (localStore && localStore.access_token) ? localStore.access_token : '';

            // Construct WebSocket URL - always use port 8058 for API
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const host = window.location.hostname;
            const port = '8058';

            let wsUrl = `${protocol}//${host}:${port}/depictio/api/v1/events/ws?dashboard_id=${dashboardId}`;
            if (token) {
                wsUrl += `&token=${token}`;
            }

            // Check if we already have a connection to this exact URL
            if (window._depictioWs &&
                window._depictioWs.readyState === WebSocket.OPEN &&
                window._depictioWs._url === wsUrl) {
                console.log('[WebSocket] Already connected to this URL');
                return window.dash_clientside.no_update;
            }

            // Close existing connection if URL changed
            if (window._depictioWs) {
                console.log('[WebSocket] Closing existing connection for URL change');
                window._depictioWs.close();
                window._depictioWs = null;
            }

            console.log('[WebSocket] Connecting to:', wsUrl.replace(/token=[^&]+/, 'token=***'));

            // Create new WebSocket connection
            const ws = new WebSocket(wsUrl);
            ws._url = wsUrl;  // Store URL for comparison

            // Set up message handler that updates ws-message-store
            ws.onmessage = function(event) {
                console.log('[WebSocket] Received raw message:', event.data);

                try {
                    const data = JSON.parse(event.data);
                    console.log('[WebSocket] Parsed message:', data);

                    // Create store data object
                    const storeData = {
                        event_type: data.event_type,
                        timestamp: data.timestamp || new Date().toISOString(),
                        dashboard_id: data.dashboard_id,
                        data_collection_id: data.data_collection_id,
                        payload: data.payload || {},
                        received_at: Date.now()
                    };

                    // Update the ws-message-store via setProps
                    window._lastWsMessage = storeData;
                    console.log('[WebSocket] Attempting to update store...');

                    // Use Dash's setProps mechanism to trigger callback
                    if (window.dash_clientside && window.dash_clientside.set_props) {
                        console.log('[WebSocket] Using set_props to update ws-message-store');
                        window.dash_clientside.set_props('ws-message-store', {data: storeData});
                    } else {
                        console.warn('[WebSocket] set_props not available');
                    }

                    // Also show a native browser notification as fallback for data updates
                    if (data.event_type === 'data_collection_updated' || data.event_type === 'data_collection_created') {
                        const tag = data.payload?.data_collection_tag || 'Data';
                        const op = data.payload?.operation || 'updated';
                        console.log('[WebSocket] Data update notification:', tag, op);

                        // Try to use Mantine notifications if available
                        if (window.mantineNotifications && window.mantineNotifications.show) {
                            window.mantineNotifications.show({
                                title: 'Data Updated',
                                message: tag + ' has been ' + op + '. Refresh to see changes.',
                                color: 'blue',
                                autoClose: 8000
                            });
                        }
                    }
                } catch(e) {
                    console.error('[WebSocket] Message parse error:', e);
                }
            };

            ws.onopen = function() {
                console.log('[WebSocket] Connection established');
            };

            ws.onerror = function(error) {
                console.error('[WebSocket] Connection error:', error);
            };

            ws.onclose = function(event) {
                console.log('[WebSocket] Connection closed:', event.code, event.reason);
                // Don't auto-reconnect here - let the callback handle it on next trigger
            };

            // Store reference globally
            window._depictioWs = ws;

            return window.dash_clientside.no_update;
        }
        """,
        Output("ws-state", "children"),
        Input("url", "pathname"),
        State("local-store", "data"),
        State("ws-state", "children"),
        prevent_initial_call=False,
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
