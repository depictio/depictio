"""
WebSocket routes for real-time event notifications.

Provides WebSocket endpoint for dashboard real-time updates with JWT authentication.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette import status

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _async_fetch_user_from_token
from depictio.api.v1.services.events import connection_manager, event_service

events_router = APIRouter()


async def verify_websocket_token(token: str | None) -> dict[str, str] | None:
    """
    Verify JWT token for WebSocket connection.

    WebSocket doesn't support Authorization headers, so we use query params.

    Args:
        token: JWT token from query parameter

    Returns:
        User dict if valid, None otherwise
    """
    if not token:
        return None

    try:
        user = await _async_fetch_user_from_token(token)
        if user:
            return {"user_id": str(user.id), "email": user.email}
    except Exception as e:
        logger.debug(f"WebSocket token verification failed: {e}")

    return None


@events_router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="JWT access token"),
    dashboard_id: str | None = Query(default=None, description="Dashboard ID to subscribe to"),
):
    """
    WebSocket endpoint for real-time event notifications.

    Connect to receive real-time updates when data collections change.
    The server will automatically detect which dashboards are affected
    and send notifications to connected clients.

    Query Parameters:
        token: JWT access token for authentication
        dashboard_id: Dashboard ID to subscribe to for updates

    Message Types Received:
        - connection_established: Sent immediately after connection
        - data_collection_updated: When a DC used by your dashboard changes
        - heartbeat: Periodic keep-alive messages

    Example JavaScript:
        ```javascript
        const ws = new WebSocket(
            `ws://localhost:8058/depictio/api/v1/events/ws?token=${jwt}&dashboard_id=${dashboardId}`
        );
        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.event_type === 'data_collection_updated') {
                // Refresh dashboard component
            }
        };
        ```
    """
    if not settings.events.enabled:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Events disabled")
        return

    # Verify token (optional - allows unauthenticated connections if auth mode allows)
    user_info = await verify_websocket_token(token)
    user_id = user_info["user_id"] if user_info else None

    if not user_info and not settings.auth.unauthenticated_mode:
        # Require authentication if not in unauthenticated mode
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required"
        )
        return

    # Accept connection and register with connection manager
    client_id = await connection_manager.connect(
        websocket=websocket,
        dashboard_id=dashboard_id,
        user_id=user_id,
    )

    try:
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages from client (ping/pong, subscription changes)
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=settings.events.ws_connection_timeout,
                )
                await handle_client_message(client_id, data, websocket)

            except asyncio.TimeoutError:
                # No message received, but connection is still alive
                # The heartbeat loop in EventService handles keep-alive
                continue

    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected normally: {client_id}")
    except Exception as e:
        logger.warning(f"WebSocket error for {client_id}: {e}")
    finally:
        await connection_manager.disconnect(client_id)


async def handle_client_message(client_id: str, data: dict[str, Any], websocket: WebSocket) -> None:
    """
    Handle incoming messages from WebSocket clients.

    Supports:
        - subscribe: Subscribe to a dashboard
        - unsubscribe: Unsubscribe from a dashboard
        - ping: Client ping (responds with pong)
    """
    msg_type = data.get("type", "")
    dashboard_id = data.get("dashboard_id")

    if msg_type == "subscribe" and dashboard_id:
        await connection_manager.subscribe_to_dashboard(client_id, dashboard_id)
        await websocket.send_json({"type": "subscribed", "dashboard_id": dashboard_id})

    elif msg_type == "unsubscribe" and dashboard_id:
        await connection_manager.unsubscribe_from_dashboard(client_id, dashboard_id)
        await websocket.send_json({"type": "unsubscribed", "dashboard_id": dashboard_id})

    elif msg_type == "ping":
        await websocket.send_json({"type": "pong"})


@events_router.get("/status")
async def get_events_status() -> dict[str, Any]:
    """
    Get the status of the real-time events system.

    Returns:
        Status information including enabled state, connection counts, etc.
    """
    return {
        "enabled": settings.events.enabled,
        "mongodb_change_streams": settings.events.mongodb_change_streams_enabled,
        "total_connections": connection_manager.get_connection_count(),
        "service_stats": event_service.get_stats(),
    }


@events_router.post("/test-trigger/{dc_id}")
async def test_trigger_event(dc_id: str) -> dict[str, Any]:
    """
    Manually trigger a data collection update event for testing.

    This bypasses MongoDB change streams - useful for testing WebSocket
    notifications without a replica set.

    Broadcasts to ALL currently connected dashboards (not database query).

    Args:
        dc_id: The data collection ID to simulate an update for
    """
    from datetime import datetime, timezone

    from depictio.models.models.realtime import EventMessage, EventSourceType, EventType

    # Create a test event
    event = EventMessage(
        event_type=EventType.DATA_COLLECTION_UPDATED,
        source_type=EventSourceType.MONGODB_CHANGES,
        timestamp=datetime.now(timezone.utc),
        data_collection_id=dc_id,
        payload={
            "operation": "update",
            "data_collection_tag": "test_trigger",
            "test_trigger": True,
        },
    )

    # Get all currently subscribed dashboards from the connection manager
    subscribed_dashboards = connection_manager.get_all_subscribed_dashboards()

    if subscribed_dashboards:
        # Broadcast to all connected dashboards
        for dashboard_id in subscribed_dashboards:
            event_copy = event.model_copy(update={"dashboard_id": dashboard_id})
            await connection_manager.broadcast_to_dashboard(dashboard_id, event_copy)

        logger.info(f"Test event triggered for {len(subscribed_dashboards)} connected dashboards")

        return {
            "success": True,
            "message": f"Event triggered for {len(subscribed_dashboards)} connected dashboards",
            "dashboard_ids": list(subscribed_dashboards),
            "connections": connection_manager.get_connection_count(),
        }
    else:
        return {
            "success": False,
            "message": "No connected dashboards to notify",
            "connections": connection_manager.get_connection_count(),
        }
