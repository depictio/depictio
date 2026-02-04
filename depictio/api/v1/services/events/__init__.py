"""
Real-time event services for WebSocket notifications.

This package provides the infrastructure for real-time dashboard updates
when backend data changes (MongoDB change streams, file watchers, etc.).
"""

from depictio.api.v1.services.events.connection_manager import (
    ConnectionManager,
    connection_manager,
)
from depictio.api.v1.services.events.event_service import EventService, event_service

__all__ = ["ConnectionManager", "EventService", "connection_manager", "event_service"]
