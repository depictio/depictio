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

import dash
from dash import Dash, Input, Output, State, no_update

from depictio.api.v1.configs.logging_init import logger


def register_realtime_callbacks(app: Dash) -> None:
    """
    Register all real-time WebSocket callbacks for a Dash app.

    Should be called for both viewer and editor apps.
    """
    logger.info(f"Registering real-time WebSocket callbacks for app: {app.title}")
    register_native_websocket_callback(app)
    register_data_update_notification_callback(app)
    register_track_updated_data_collections_callback(app)
    register_track_new_table_rows_callback(app)
    register_auto_refresh_components_callback(app)
    register_invalidate_dash_cache_callback(app)
    # Disabled: Flash animation replaced with persistent marker highlighting
    # register_figure_flash_animation_callback(app)
    logger.info("Real-time WebSocket callbacks registered successfully")


def register_native_websocket_callback(app: Dash) -> None:
    """
    Register clientside callback to manage native WebSocket connection.

    This replaces the dash-extensions WebSocket component with direct JavaScript
    WebSocket management, giving us full control over connection lifecycle.

    The callback:
    1. Extracts dashboard ID from pathname
    2. Constructs the proper WebSocket URL from api-base-url-store (public URL)
    3. Manages WebSocket connection (creates new, closes old on URL change)
    4. Updates ws-message-store when messages are received
    """
    app.clientside_callback(
        """
        function(pathname, apiBaseUrl, localStore, currentState) {
            console.log('[WebSocket] Callback fired! pathname:', pathname, 'apiBaseUrl:', apiBaseUrl);

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

            // Construct WebSocket URL from api-base-url-store (public/external URL)
            let wsUrl = '';
            if (apiBaseUrl) {
                try {
                    const parsed = new URL(apiBaseUrl);
                    const wsProtocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:';
                    wsUrl = `${wsProtocol}//${parsed.host}/depictio/api/v1/events/ws?dashboard_id=${dashboardId}`;
                } catch(e) {
                    console.warn('[WebSocket] Could not parse API base URL:', apiBaseUrl);
                }
            }
            if (!wsUrl) {
                // Fallback: derive from current page
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                wsUrl = `${protocol}//${window.location.hostname}:8058/depictio/api/v1/events/ws?dashboard_id=${dashboardId}`;
            }
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

                    // For data updates, also update the previous row counts tracker
                    if (data.event_type === 'data_collection_updated' || data.event_type === 'data_collection_created') {
                        const dcId = data.data_collection_id;
                        const tag = data.payload?.data_collection_tag || 'Data';
                        const op = data.payload?.operation || 'updated';
                        console.log('[WebSocket] Data update notification:', tag, op, 'DC:', dcId);

                        // Store the update info for row highlighting
                        // Components will use this to determine which rows are new
                        if (!window._depictioUpdateTimestamps) {
                            window._depictioUpdateTimestamps = {};
                        }
                        window._depictioUpdateTimestamps[dcId] = {
                            timestamp: Date.now(),
                            tag: tag,
                            operation: op
                        };
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
        [Input("url", "pathname"), Input("api-base-url-store", "data")],
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


def register_track_updated_data_collections_callback(app: Dash) -> None:
    """
    Register callback to track which data collections have new data.

    Updates ws-new-data-ids store with DC IDs that have been updated.
    Components can watch this store to refresh when their DC is updated.
    """

    @app.callback(
        Output("ws-new-data-ids", "data"),
        Input("ws-message-store", "data"),
        State("ws-new-data-ids", "data"),
        State("ws-connection-config", "data"),
        prevent_initial_call=True,
    )
    def track_updated_data_collections(
        ws_data: dict | None, current_ids: list | None, config: dict | None
    ) -> list | type[no_update]:
        """
        Track data collection IDs that have been updated.

        Maintains a list of DC IDs with update timestamps so components
        can check if they need to refresh.
        """
        if not ws_data:
            return no_update

        event_type = ws_data.get("event_type", "")
        valid_events = {"data_collection_updated", "data_collection_created"}

        if event_type not in valid_events:
            return no_update

        # Check if auto-refresh is enabled
        if config and config.get("refresh_mode") != "auto-refresh":
            return no_update

        dc_id = ws_data.get("data_collection_id")
        if not dc_id:
            return no_update

        # Add to list with timestamp (keep last 50 to prevent unbounded growth)
        current_ids = current_ids or []
        new_entry = {
            "dc_id": dc_id,
            "timestamp": ws_data.get("received_at", 0),
            "event_type": event_type,
            "payload": ws_data.get("payload", {}),
        }

        # Remove old entries for this DC and add new one
        updated_ids = [e for e in current_ids if e.get("dc_id") != dc_id]
        updated_ids.append(new_entry)

        # Keep only last 50 entries
        if len(updated_ids) > 50:
            updated_ids = updated_ids[-50:]

        logger.info(f"Tracking updated DC: {dc_id}, total tracked: {len(updated_ids)}")
        return updated_ids


def register_track_new_table_rows_callback(app: Dash) -> None:
    """
    Track new table row IDs for highlighting across pagination.

    When data_collection_updated event fires, extract row count BEFORE update
    and mark rows beyond that count as new. Works because data is appended.
    """
    app.clientside_callback(
        """
        function(wsData, config) {
            if (!config || config.refresh_mode !== 'auto-refresh') {
                return window.dash_clientside.no_update;
            }
            if (!wsData) {
                return window.dash_clientside.no_update;
            }

            const eventType = wsData.event_type;
            if (eventType !== 'data_collection_updated' && eventType !== 'data_collection_created') {
                return window.dash_clientside.no_update;
            }

            const dcId = wsData.data_collection_id;
            if (!dcId) {
                return window.dash_clientside.no_update;
            }

            // Initialize tracking object
            if (!window._depictioNewRows) {
                window._depictioNewRows = {};
            }

            // Mark this DC as having new rows (tables will check their DC)
            // Store timestamp - tables will use this to know highlights are active
            window._depictioNewRows[dcId] = {
                timestamp: Date.now(),
                // Rows will be highlighted based on recent timestamp
                // AG Grid will check: row timestamp > (current time - 5 seconds)
            };

            console.log('[TableHighlight] Marked DC as updated:', dcId);

            // Clear after 5 seconds
            setTimeout(function() {
                delete window._depictioNewRows[dcId];
                console.log('[TableHighlight] Cleared highlight for DC:', dcId);
            }, 5000);

            return window.dash_clientside.no_update;
        }
        """,
        Output("ws-state", "children", allow_duplicate=True),
        Input("ws-message-store", "data"),
        State("ws-connection-config", "data"),
        prevent_initial_call=True,
    )


def register_auto_refresh_components_callback(app: Dash) -> None:
    """
    Register clientside callback to trigger component refresh when data is updated.

    This callback watches ws-new-data-ids and triggers a refresh of figure
    and table components that use the updated data collections.
    """
    # Clientside callback to trigger figure refresh
    # This updates figure-trigger stores to force re-render
    app.clientside_callback(
        """
        function(newDataIds, triggerData, triggerIds, config) {
            // Check if auto-refresh is enabled
            if (!config || config.refresh_mode !== 'auto-refresh') {
                console.log('[AutoRefresh] Auto-refresh not enabled');
                return window.dash_clientside.no_update;
            }

            if (!newDataIds || newDataIds.length === 0) {
                return window.dash_clientside.no_update;
            }

            if (!triggerData || !triggerIds || triggerData.length === 0) {
                return window.dash_clientside.no_update;
            }

            // Get set of updated DC IDs
            const updatedDcIds = new Set(newDataIds.map(item => item.dc_id));
            console.log('[AutoRefresh] Updated DC IDs:', Array.from(updatedDcIds));

            // Check if any figure uses an updated DC
            let needsUpdate = false;
            const updatedTriggers = triggerData.map((trigger, idx) => {
                if (!trigger) return trigger;

                const dcId = trigger.dc_id;
                if (updatedDcIds.has(dcId)) {
                    console.log('[AutoRefresh] Triggering refresh for figure with DC:', dcId);
                    needsUpdate = true;
                    // Add refresh timestamp to force re-render
                    return {
                        ...trigger,
                        _refresh_timestamp: Date.now(),
                        _is_realtime_update: true
                    };
                }
                return trigger;
            });

            if (needsUpdate) {
                console.log('[AutoRefresh] Triggering figure refresh');
                return updatedTriggers;
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output({"type": "figure-trigger", "index": dash.ALL}, "data", allow_duplicate=True),
        Input("ws-new-data-ids", "data"),
        State({"type": "figure-trigger", "index": dash.ALL}, "data"),
        State({"type": "figure-trigger", "index": dash.ALL}, "id"),
        State("ws-connection-config", "data"),
        prevent_initial_call=True,
    )


def register_figure_flash_animation_callback(app: Dash) -> None:
    """
    Apply visual effects to scatter plots when they update from WebSocket.

    Watches figure-trigger data for _is_realtime_update flag and:
    1. Applies CSS animation (pulsing border) to figure wrapper for 3 seconds
    2. Auto-scales axes via Plotly.relayout to show all new data points
    """
    app.clientside_callback(
        """
        function(triggerDataList, triggerIds, config) {
            if (!config || config.refresh_mode !== 'auto-refresh') {
                return window.dash_clientside.no_update;
            }
            if (!triggerDataList || !triggerIds || triggerDataList.length === 0) {
                return window.dash_clientside.no_update;
            }

            // Find figures that have realtime updates
            triggerDataList.forEach(function(trigger, idx) {
                if (!trigger || !trigger._is_realtime_update) return;

                const index = triggerIds[idx].index;
                const wrapperId = {"type": "figure-graph-wrapper", "index": index};
                const figureId = 'figure-graph-' + index;

                // Apply flash animation class
                window.dash_clientside.set_props(wrapperId, {
                    className: "realtime-flash"
                });

                // Remove animation after 3 seconds
                setTimeout(function() {
                    window.dash_clientside.set_props(wrapperId, {
                        className: ""
                    });
                }, 3000);

                // Auto-scale axes after figure updates
                setTimeout(function() {
                    const figureDiv = document.getElementById(figureId);
                    if (figureDiv && window.Plotly) {
                        // Auto-scale both axes to show all data
                        window.Plotly.relayout(figureDiv, {
                            'xaxis.autorange': true,
                            'yaxis.autorange': true
                        });
                        console.log('[AutoScale] Applied to figure:', figureId);
                    } else {
                        console.warn('[AutoScale] Figure not found or Plotly not loaded:', figureId);
                    }
                }, 100);  // Small delay to ensure figure data is rendered
            });

            return window.dash_clientside.no_update;
        }
        """,
        Output("ws-state", "children", allow_duplicate=True),
        Input({"type": "figure-trigger", "index": dash.ALL}, "data"),
        State({"type": "figure-trigger", "index": dash.ALL}, "id"),
        State("ws-connection-config", "data"),
        prevent_initial_call=True,
    )


def register_invalidate_dash_cache_callback(app: Dash) -> None:
    """
    Invalidate the Dash-process in-memory data cache when DCs are updated.

    invalidate_dc_cache() in the API process clears the API's own memory cache
    and Redis, but the Dash process has its own _dataframe_memory_cache that
    must be cleared separately so re-renders fetch fresh data.
    """

    @app.callback(
        Output("ws-pending-updates", "data"),
        Input("ws-new-data-ids", "data"),
        prevent_initial_call=True,
    )
    def invalidate_dash_process_cache(new_data_ids: list | None) -> bool | type[no_update]:
        if not new_data_ids:
            return no_update
        from depictio.api.v1.deltatables_utils import invalidate_dc_cache

        for entry in new_data_ids:
            dc_id = entry.get("dc_id")
            if dc_id:
                logger.info(f"Invalidating Dash-side cache for DC: {dc_id}")
                invalidate_dc_cache(dc_id)
        return True
