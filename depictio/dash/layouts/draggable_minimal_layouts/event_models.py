"""
Pydantic models for dashboard events.
Type-safe event models for the dashboard event system.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Supported dashboard event types."""

    COMPONENT_CREATED = "component_created"
    SECTION_CREATED = "section_created"
    COMPONENT_DELETED = "component_deleted"
    COMPONENT_UPDATED = "component_updated"
    SECTION_DELETED = "section_deleted"
    FILTER_CREATED = "filter_created"

    # New events for structured dashboard
    COMPONENT_ADDED_TO_SECTION = "component_added_to_section"
    SECTION_STRUCTURE_CREATED = "section_structure_created"


class BaseEventPayload(BaseModel):
    """Base class for all event payloads."""

    trigger: str = Field(..., description="What triggered this event")


class ComponentCreatedPayload(BaseEventPayload):
    """Payload for component creation events."""

    component_id: str = Field(..., description="Unique identifier for the component")
    # component_type: str = Field(
    #     ..., description="Type of component (e.g., 'figure', 'card', 'table')"
    # )
    workflow_id: Optional[str] = Field(None, description="Associated workflow ID")
    datacollection_id: Optional[str] = Field(None, description="Associated data collection ID")
    section_id: Optional[str] = Field(None, description="Target section ID for the component")
    metadata: Optional[dict] = Field(None, description="Component metadata and configuration")


class SectionCreatedPayload(BaseEventPayload):
    """Payload for section creation events."""

    section_name: str = Field(..., description="Name of the created section")
    click_count: int = Field(..., description="Number of times the button was clicked")


class ComponentDeletedPayload(BaseEventPayload):
    """Payload for component deletion events."""

    component_id: str = Field(..., description="ID of the deleted component")
    section_id: Optional[str] = Field(None, description="Section containing the component")


class ComponentUpdatedPayload(BaseEventPayload):
    """Payload for component update events."""

    component_id: str = Field(..., description="ID of the updated component")
    updated_fields: Dict[str, Any] = Field(..., description="Fields that were updated")


class FilterCreatedPayload(BaseEventPayload):
    """Payload for filter creation events."""

    filter_name: str = Field(..., description="Name of the created filter")
    filter_type: str = Field(..., description="Type of filter")


class ComponentAddedToSectionPayload(BaseEventPayload):
    """Payload for adding a component to a specific section."""

    section_id: str = Field(..., description="ID of the target section")
    component_id: str = Field(..., description="ID of the created component")
    component_type: str = Field(..., description="Type of component")
    section_type: Optional[str] = Field(None, description="Type of section")


class SectionStructureCreatedPayload(BaseEventPayload):
    """Payload for creating a section with the new structure."""

    section_id: str = Field(..., description="ID of the created section")
    section_name: str = Field(..., description="Name of the created section")
    section_type: str = Field(..., description="Type of section")
    icon: Optional[str] = Field(None, description="Section icon")


# Union type for all possible payloads
EventPayload = Union[
    ComponentCreatedPayload,
    SectionCreatedPayload,
    ComponentDeletedPayload,
    ComponentUpdatedPayload,
    FilterCreatedPayload,
    ComponentAddedToSectionPayload,
    SectionStructureCreatedPayload,
]


class DashboardEvent(BaseModel):
    """Main event model for dashboard events."""

    event_type: EventType = Field(..., description="Type of the event")
    timestamp: datetime = Field(default_factory=datetime.now, description="When the event occurred")
    payload: EventPayload = Field(..., description="Event-specific data")

    class Config:
        """Pydantic configuration."""

        use_enum_values = True  # Serialize enums as their values


class DashboardEventStore(BaseModel):
    """Model for the dashboard event store state."""

    event_type: Optional[EventType] = Field(None, description="Current event type")
    timestamp: Optional[datetime] = Field(None, description="Timestamp of current event")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Current event payload")

    class Config:
        """Pydantic configuration."""

        use_enum_values = True
