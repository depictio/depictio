"""
WebSocket connection manager for real-time event broadcasting.

Manages WebSocket connections with Redis pub/sub for multi-instance support.
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.realtime import ConnectionStatus, EventMessage, EventType
from redis.asyncio import Redis


class ConnectionManager:
    """
    Manages WebSocket connections and message broadcasting.

    Supports:
    - Multiple concurrent WebSocket connections
    - Dashboard-scoped subscriptions
    - Redis pub/sub for multi-instance coordination
    - Heartbeat/ping-pong for connection health
    """

    def __init__(self):
        # Active WebSocket connections: client_id -> WebSocket
        self._connections: dict[str, WebSocket] = {}

        # Dashboard subscriptions: dashboard_id -> set of client_ids
        self._dashboard_subscriptions: dict[str, set[str]] = {}

        # Client metadata: client_id -> metadata dict
        self._client_metadata: dict[str, dict[str, Any]] = {}

        # Redis pub/sub client (initialized lazily)
        self._redis: Redis | None = None
        self._pubsub_task: asyncio.Task | None = None

        # Channel prefix for Redis pub/sub
        self._channel_prefix = "depictio:events:"

    async def _get_redis(self) -> Redis | None:
        """Get or create Redis connection for pub/sub."""
        if not settings.events.enabled:
            return None

        if self._redis is None:
            try:
                self._redis = Redis.from_url(
                    settings.events.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                # Test connection
                await self._redis.ping()
                logger.info("Redis pub/sub connection established for events")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis for events: {e}")
                self._redis = None

        return self._redis

    async def start_pubsub_listener(self) -> None:
        """Start the Redis pub/sub listener for cross-instance messaging."""
        redis = await self._get_redis()
        if redis is None:
            logger.info("Redis not available, running in single-instance mode")
            return

        async def listen():
            try:
                pubsub = redis.pubsub()
                await pubsub.psubscribe(f"{self._channel_prefix}*")
                logger.info("Started Redis pub/sub listener for events")

                async for message in pubsub.listen():
                    if message["type"] == "pmessage":
                        channel = message["channel"]
                        data = message["data"]
                        await self._handle_pubsub_message(channel, data)
            except asyncio.CancelledError:
                logger.info("Redis pub/sub listener cancelled")
            except Exception as e:
                logger.error(f"Redis pub/sub listener error: {e}")

        self._pubsub_task = asyncio.create_task(listen())

    async def stop_pubsub_listener(self) -> None:
        """Stop the Redis pub/sub listener."""
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
            self._pubsub_task = None

        if self._redis:
            await self._redis.close()
            self._redis = None

    async def _handle_pubsub_message(self, channel: str, data: str) -> None:
        """Handle incoming pub/sub message from another instance."""
        try:
            # Extract dashboard_id from channel
            # Channel format: depictio:events:dashboard:{dashboard_id}
            parts = channel.split(":")
            if len(parts) >= 4 and parts[2] == "dashboard":
                dashboard_id = parts[3]
                message_data = json.loads(data)

                # Broadcast to local connections subscribed to this dashboard
                await self._broadcast_to_dashboard_local(dashboard_id, message_data)
        except Exception as e:
            logger.error(f"Error handling pub/sub message: {e}")

    async def connect(
        self,
        websocket: WebSocket,
        dashboard_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """
        Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
            dashboard_id: Optional dashboard to subscribe to
            user_id: Optional user ID for the connection

        Returns:
            client_id: Unique identifier for this connection
        """
        await websocket.accept()

        client_id = str(uuid.uuid4())
        self._connections[client_id] = websocket
        self._client_metadata[client_id] = {
            "user_id": user_id,
            "connected_at": datetime.utcnow().isoformat(),
            "dashboard_id": dashboard_id,
        }

        # Subscribe to dashboard if specified
        if dashboard_id:
            await self.subscribe_to_dashboard(client_id, dashboard_id)

        # Send connection confirmation
        status = ConnectionStatus(
            status="connected",
            client_id=client_id,
            subscriptions=[dashboard_id] if dashboard_id else [],
        )
        await self._send_to_client(client_id, status.model_dump(mode="json"))

        logger.info(
            f"WebSocket connected: client_id={client_id}, "
            f"dashboard={dashboard_id}, total={len(self._connections)}"
        )

        return client_id

    async def disconnect(self, client_id: str) -> None:
        """
        Remove a WebSocket connection and clean up subscriptions.

        Args:
            client_id: The client ID to disconnect
        """
        # Remove from all dashboard subscriptions
        for dashboard_id, clients in list(self._dashboard_subscriptions.items()):
            clients.discard(client_id)
            if not clients:
                del self._dashboard_subscriptions[dashboard_id]

        # Remove connection and metadata
        self._connections.pop(client_id, None)
        self._client_metadata.pop(client_id, None)

        logger.info(
            f"WebSocket disconnected: client_id={client_id}, total={len(self._connections)}"
        )

    async def subscribe_to_dashboard(self, client_id: str, dashboard_id: str) -> None:
        """
        Subscribe a client to dashboard events.

        Args:
            client_id: The client ID
            dashboard_id: The dashboard to subscribe to
        """
        if dashboard_id not in self._dashboard_subscriptions:
            self._dashboard_subscriptions[dashboard_id] = set()
        self._dashboard_subscriptions[dashboard_id].add(client_id)

        # Update client metadata
        if client_id in self._client_metadata:
            self._client_metadata[client_id]["dashboard_id"] = dashboard_id

        logger.debug(f"Client {client_id} subscribed to dashboard {dashboard_id}")

    async def unsubscribe_from_dashboard(self, client_id: str, dashboard_id: str) -> None:
        """
        Unsubscribe a client from dashboard events.

        Args:
            client_id: The client ID
            dashboard_id: The dashboard to unsubscribe from
        """
        if dashboard_id in self._dashboard_subscriptions:
            self._dashboard_subscriptions[dashboard_id].discard(client_id)
            if not self._dashboard_subscriptions[dashboard_id]:
                del self._dashboard_subscriptions[dashboard_id]

    async def broadcast_to_dashboard(self, dashboard_id: str, message: EventMessage) -> None:
        """
        Broadcast a message to all clients viewing a specific dashboard.

        Uses Redis pub/sub for cross-instance delivery.

        Args:
            dashboard_id: The dashboard ID
            message: The event message to broadcast
        """
        message_data = message.model_dump(mode="json")

        # Publish to Redis for cross-instance delivery
        redis = await self._get_redis()
        if redis:
            try:
                channel = f"{self._channel_prefix}dashboard:{dashboard_id}"
                await redis.publish(channel, json.dumps(message_data))
            except Exception as e:
                logger.warning(f"Failed to publish to Redis: {e}")

        # Also broadcast to local connections (for single-instance or fallback)
        await self._broadcast_to_dashboard_local(dashboard_id, message_data)

    async def _broadcast_to_dashboard_local(
        self, dashboard_id: str, message_data: dict[str, Any]
    ) -> None:
        """Broadcast to local WebSocket connections for a dashboard."""
        client_ids = self._dashboard_subscriptions.get(dashboard_id, set())
        if not client_ids:
            return

        disconnected = set()
        for client_id in client_ids:
            try:
                await self._send_to_client(client_id, message_data)
            except Exception as e:
                logger.warning(f"Failed to send to client {client_id}: {e}")
                disconnected.add(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            await self.disconnect(client_id)

    async def _send_to_client(self, client_id: str, data: dict[str, Any]) -> None:
        """Send data to a specific client."""
        websocket = self._connections.get(client_id)
        if websocket:
            await websocket.send_json(data)

    async def send_heartbeat(self, client_id: str) -> None:
        """Send a heartbeat message to keep the connection alive."""
        message = EventMessage(
            event_type=EventType.HEARTBEAT,
            payload={"server_time": datetime.utcnow().isoformat()},
        )
        try:
            await self._send_to_client(client_id, message.model_dump(mode="json"))
        except Exception as e:
            logger.debug(f"Heartbeat failed for {client_id}: {e}")

    def get_dashboard_subscribers(self, dashboard_id: str) -> set[str]:
        """Get all client IDs subscribed to a dashboard."""
        return self._dashboard_subscriptions.get(dashboard_id, set()).copy()

    def get_all_client_ids(self) -> set[str]:
        """Get all active client IDs."""
        return set(self._connections.keys())

    def get_connection_count(self) -> int:
        """Get the total number of active connections."""
        return len(self._connections)

    def get_dashboard_connection_count(self, dashboard_id: str) -> int:
        """Get the number of connections viewing a specific dashboard."""
        return len(self._dashboard_subscriptions.get(dashboard_id, set()))

    def get_all_subscribed_dashboards(self) -> set[str]:
        """Get all dashboard IDs that have active subscriptions."""
        return set(self._dashboard_subscriptions.keys())


# Global singleton instance
connection_manager = ConnectionManager()
