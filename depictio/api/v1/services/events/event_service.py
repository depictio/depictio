"""
Event service coordinator for real-time updates.

Coordinates event sources (MongoDB change streams, etc.) and routes
events to the WebSocket ConnectionManager for broadcasting.
"""

import asyncio
from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.events.connection_manager import ConnectionManager, connection_manager
from depictio.api.v1.services.events.mongodb_watcher import MongoDBChangeWatcher
from depictio.models.models.realtime import EventMessage


class EventService:
    """
    Coordinates real-time event sources and broadcasting.

    Manages:
    - MongoDB change stream watcher
    - WebSocket connection manager
    - Event routing and broadcasting
    """

    def __init__(self, conn_manager: ConnectionManager | None = None):
        """
        Initialize the event service.

        Args:
            conn_manager: Optional ConnectionManager instance (uses global singleton if not provided)
        """
        self._connection_manager = conn_manager or connection_manager
        self._mongodb_watcher: MongoDBChangeWatcher | None = None
        self._running = False
        self._heartbeat_task: asyncio.Task | None = None

    @property
    def connection_manager(self) -> ConnectionManager:
        """Get the connection manager instance."""
        return self._connection_manager

    async def start(self) -> None:
        """Start all event sources and the connection manager."""
        if not settings.events.enabled:
            logger.info("Real-time events disabled (DEPICTIO_EVENTS_ENABLED=false)")
            return

        self._running = True
        logger.info("Starting real-time event service")

        # Start Redis pub/sub listener for cross-instance messaging
        await self._connection_manager.start_pubsub_listener()

        # Start MongoDB change watcher
        if settings.events.mongodb_change_streams_enabled:
            self._mongodb_watcher = MongoDBChangeWatcher(
                on_change_callback=self._handle_dc_change,
            )
            await self._mongodb_watcher.start()

        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("Real-time event service started")

    async def stop(self) -> None:
        """Stop all event sources and clean up."""
        self._running = False

        # Stop heartbeat
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        # Stop MongoDB watcher
        if self._mongodb_watcher:
            await self._mongodb_watcher.stop()
            self._mongodb_watcher = None

        # Stop Redis pub/sub
        await self._connection_manager.stop_pubsub_listener()

        logger.info("Real-time event service stopped")

    async def _handle_dc_change(self, event: EventMessage, dashboard_ids: list[str]) -> None:
        """
        Handle a data collection change event.

        Routes the event to all dashboards that use the changed DC.

        Args:
            event: The event message
            dashboard_ids: List of dashboard IDs to notify
        """
        for dashboard_id in dashboard_ids:
            # Set the dashboard_id in the event for this broadcast
            event_copy = event.model_copy(update={"dashboard_id": dashboard_id})
            await self._connection_manager.broadcast_to_dashboard(dashboard_id, event_copy)

    async def notify_dashboard(
        self,
        dashboard_id: str,
        event: EventMessage,
    ) -> None:
        """
        Send an event to all clients viewing a specific dashboard.

        Args:
            dashboard_id: The dashboard ID
            event: The event message to send
        """
        event_with_dashboard = event.model_copy(update={"dashboard_id": dashboard_id})
        await self._connection_manager.broadcast_to_dashboard(dashboard_id, event_with_dashboard)

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to all connected clients."""
        interval = settings.events.ws_heartbeat_interval

        while self._running:
            try:
                await asyncio.sleep(interval)

                # Send heartbeat to all connected clients
                for client_id in self._connection_manager.get_all_client_ids():
                    await self._connection_manager.send_heartbeat(client_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Heartbeat loop error: {e}")

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the event service."""
        return {
            "enabled": settings.events.enabled,
            "running": self._running,
            "total_connections": self._connection_manager.get_connection_count(),
            "mongodb_watcher_active": self._mongodb_watcher is not None,
        }


# Global singleton instance
event_service = EventService()
