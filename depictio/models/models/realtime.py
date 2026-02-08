"""
Real-time event system models for WebSocket notifications.

This module defines the data models for the real-time event system that enables
automatic dashboard updates when backend data changes.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventSourceType(str, Enum):
    """Types of event sources that can trigger real-time updates."""

    MONGODB_CHANGES = "mongodb_changes"  # MongoDB change streams (MVP)
    FILE_WATCHER = "file_watcher"  # File system watching (future)
    CELERY_COMPLETION = "celery_completion"  # Celery task completion (future)
    S3_WATCH = "s3_watch"  # S3/MinIO notifications (future)
    WEBHOOK = "webhook"  # External webhook triggers (future)


class RefreshMode(str, Enum):
    """How components should refresh when data changes."""

    FULL = "full"  # Complete reload of component data
    INCREMENTAL = "incremental"  # Only fetch changed/new records
    APPEND = "append"  # Add new data to existing (for time series, streaming)
    SMART = "smart"  # Auto-detect best strategy based on data size


class EventType(str, Enum):
    """Types of events that can be sent via WebSocket."""

    # Data events
    DATA_COLLECTION_UPDATED = "data_collection_updated"
    DATA_COLLECTION_CREATED = "data_collection_created"
    DATA_COLLECTION_DELETED = "data_collection_deleted"

    # Dashboard events
    DASHBOARD_UPDATED = "dashboard_updated"
    DASHBOARD_COMPONENT_UPDATED = "dashboard_component_updated"

    # System events
    CONNECTION_ESTABLISHED = "connection_established"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class EventMessage(BaseModel):
    """Message format for WebSocket events."""

    event_type: EventType = Field(description="Type of event")
    source_type: EventSourceType = Field(
        default=EventSourceType.MONGODB_CHANGES, description="Source that generated the event"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")

    # Context identifiers
    project_id: str | None = Field(default=None, description="Project ID if applicable")
    dashboard_id: str | None = Field(default=None, description="Dashboard ID if applicable")
    data_collection_id: str | None = Field(
        default=None, description="Data collection ID if applicable"
    )

    # Event payload
    payload: dict[str, Any] = Field(default_factory=dict, description="Event-specific payload data")

    # Metadata
    message_id: str | None = Field(default=None, description="Unique message identifier")

    model_config = ConfigDict(use_enum_values=True)


class RealtimeConfig(BaseModel):
    """Project-level real-time configuration (stored in project.yaml or Project model)."""

    enabled: bool = Field(default=True, description="Enable real-time updates for this project")
    debounce_ms: int = Field(
        default=1000, description="Debounce interval in milliseconds for rapid updates"
    )
    watch_data_collections: list[str] | None = Field(
        default=None,
        description="Specific data collection tags to watch (None = all)",
    )

    model_config = ConfigDict(extra="forbid")


class ComponentRealtimeOptions(BaseModel):
    """Component-level real-time options (future enhancement)."""

    enabled: bool = Field(default=True, description="Enable real-time updates for this component")
    auto_refresh: bool = Field(
        default=False, description="Auto-refresh on data change (vs show notification)"
    )
    refresh_mode: RefreshMode = Field(
        default=RefreshMode.FULL, description="How to refresh component data"
    )
    highlight_new: bool = Field(default=True, description="Visually highlight new data points/rows")
    highlight_duration_ms: int = Field(
        default=3000, description="How long to show highlight in milliseconds"
    )
    highlight_color: str | None = Field(
        default=None, description="Optional custom highlight color (e.g., '#4CAF50')"
    )

    model_config = ConfigDict(extra="forbid")


class WebSocketSubscription(BaseModel):
    """Represents a WebSocket subscription to events."""

    client_id: str = Field(description="Unique client/connection identifier")
    dashboard_id: str | None = Field(default=None, description="Dashboard being viewed")
    project_id: str | None = Field(default=None, description="Project context")
    subscribed_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(extra="forbid")


class ConnectionStatus(BaseModel):
    """Response when WebSocket connection is established."""

    status: str = Field(default="connected")
    client_id: str = Field(description="Assigned client ID")
    subscriptions: list[str] = Field(
        default_factory=list, description="Active subscription channels"
    )
    server_time: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(extra="forbid")
