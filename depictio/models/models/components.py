"""
Component metadata models for storing component-level metadata in MongoDB.
Provides tracking and management of dashboard component metadata.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from depictio.models.models.base import MongoModel, PyObjectId


class ComponentType(str, Enum):
    """Supported component types in the dashboard."""

    CARD = "card"
    FIGURE = "figure"
    TABLE = "table"
    INTERACTIVE = "interactive"
    TEXT = "text"
    MULTIQC = "multiqc"


class ComponentStatus(str, Enum):
    """Component lifecycle status."""

    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ComponentMetadata(BaseModel):
    """Basic component metadata without MongoDB-specific fields."""

    component_id: str = Field(..., description="Unique identifier for the component")
    dashboard_id: PyObjectId = Field(..., description="ID of the parent dashboard")
    component_type: ComponentType = Field(..., description="Type of component")

    # Component identification
    title: Optional[str] = Field(None, description="Display title for the component")
    description: Optional[str] = Field(None, description="Description of the component")

    # Component status
    status: ComponentStatus = Field(ComponentStatus.ACTIVE, description="Component status")

    # Layout and positioning
    position: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Component position and layout info"
    )

    # Configuration and settings
    config: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Component-specific configuration"
    )

    # Data source references
    data_collection_ids: List[PyObjectId] = Field(
        default_factory=list, description="Referenced data collections"
    )

    # User and project context
    created_by: PyObjectId = Field(..., description="User who created the component")
    project_id: PyObjectId = Field(..., description="ID of the parent project")

    # Metadata and tags
    tags: List[str] = Field(default_factory=list, description="Component tags")
    custom_metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Custom metadata fields"
    )

    # Timestamps
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")

    @field_validator("component_id")
    @classmethod
    def component_id_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Component ID cannot be empty")
        return v.strip()

    @field_validator("title")
    @classmethod
    def title_valid_length(cls, v):
        if v and len(v) > 200:
            raise ValueError("Title must be less than 200 characters")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        if len(v) > 20:
            raise ValueError("Maximum 20 tags allowed")
        for tag in v:
            if len(tag) > 50:
                raise ValueError("Each tag must be less than 50 characters")
        return v

    def __init__(self, **data):
        # Set timestamps if not provided
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in data or data["updated_at"] is None:
            data["updated_at"] = datetime.now().isoformat()
        super().__init__(**data)


class ComponentMetadataData(MongoModel):
    """MongoDB document model for component metadata."""

    component_id: str = Field(..., description="Unique identifier for the component")
    dashboard_id: PyObjectId = Field(..., description="ID of the parent dashboard")
    component_type: ComponentType = Field(..., description="Type of component")

    # Component identification
    title: Optional[str] = Field(None, description="Display title for the component")

    # Component status
    status: ComponentStatus = Field(ComponentStatus.ACTIVE, description="Component status")

    # Layout and positioning
    position: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Component position and layout info"
    )

    # Configuration and settings
    config: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Component-specific configuration"
    )

    # Data source references
    data_collection_ids: List[PyObjectId] = Field(
        default_factory=list, description="Referenced data collections"
    )

    # User and project context
    created_by: PyObjectId = Field(..., description="User who created the component")
    project_id: PyObjectId = Field(..., description="ID of the parent project")

    # Metadata and tags
    tags: List[str] = Field(default_factory=list, description="Component tags")
    custom_metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Custom metadata fields"
    )

    # Timestamps
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_serializer("dashboard_id")
    def serialize_dashboard_id(self, dashboard_id: PyObjectId) -> str:
        return str(dashboard_id)

    @field_serializer("created_by")
    def serialize_created_by(self, created_by: PyObjectId) -> str:
        return str(created_by)

    @field_serializer("project_id")
    def serialize_project_id(self, project_id: PyObjectId) -> str:
        return str(project_id)

    @field_serializer("data_collection_ids")
    def serialize_data_collection_ids(self, data_collection_ids: List[PyObjectId]) -> List[str]:
        return [str(dc_id) for dc_id in data_collection_ids]

    @field_validator("component_id")
    @classmethod
    def component_id_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Component ID cannot be empty")
        return v.strip()

    @field_validator("title")
    @classmethod
    def title_valid_length(cls, v):
        if v and len(v) > 200:
            raise ValueError("Title must be less than 200 characters")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        if len(v) > 20:
            raise ValueError("Maximum 20 tags allowed")
        for tag in v:
            if len(tag) > 50:
                raise ValueError("Each tag must be less than 50 characters")
        return v

    def __init__(self, **data):
        # Set timestamps if not provided
        if "created_at" not in data or data["created_at"] is None:
            data["created_at"] = datetime.now().isoformat()
        if "updated_at" not in data or data["updated_at"] is None:
            data["updated_at"] = datetime.now().isoformat()
        super().__init__(**data)


class ComponentMetadataCreateRequest(BaseModel):
    """Request model for creating component metadata."""

    component_id: str = Field(..., description="Unique identifier for the component")
    dashboard_id: str = Field(..., description="ID of the parent dashboard")
    component_type: ComponentType = Field(..., description="Type of component")

    # Optional fields
    title: Optional[str] = Field(None, description="Display title for the component")
    description: Optional[str] = Field(None, description="Description of the component")
    status: ComponentStatus = Field(ComponentStatus.ACTIVE, description="Component status")
    position: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Component position and layout info"
    )
    config: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Component-specific configuration"
    )
    data_collection_ids: List[str] = Field(
        default_factory=list, description="Referenced data collections"
    )
    project_id: str = Field(..., description="ID of the parent project")
    tags: List[str] = Field(default_factory=list, description="Component tags")
    custom_metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Custom metadata fields"
    )


class ComponentMetadataUpdateRequest(BaseModel):
    """Request model for updating component metadata."""

    title: Optional[str] = Field(None, description="Display title for the component")
    description: Optional[str] = Field(None, description="Description of the component")
    status: Optional[ComponentStatus] = Field(None, description="Component status")
    position: Optional[Dict[str, Any]] = Field(
        None, description="Component position and layout info"
    )
    config: Optional[Dict[str, Any]] = Field(None, description="Component-specific configuration")
    data_collection_ids: Optional[List[str]] = Field(
        None, description="Referenced data collections"
    )
    tags: Optional[List[str]] = Field(None, description="Component tags")
    custom_metadata: Optional[Dict[str, Any]] = Field(None, description="Custom metadata fields")


class ComponentMetadataResponse(BaseModel):
    """Response model for component metadata operations."""

    id: str = Field(..., description="MongoDB document ID")
    component_id: str = Field(..., description="Unique identifier for the component")
    dashboard_id: str = Field(..., description="ID of the parent dashboard")
    component_type: ComponentType = Field(..., description="Type of component")
    title: Optional[str] = Field(None, description="Display title for the component")
    description: Optional[str] = Field(None, description="Description of the component")
    status: ComponentStatus = Field(..., description="Component status")
    position: Optional[Dict[str, Any]] = Field(
        None, description="Component position and layout info"
    )
    config: Optional[Dict[str, Any]] = Field(None, description="Component-specific configuration")
    data_collection_ids: List[str] = Field(..., description="Referenced data collections")
    created_by: str = Field(..., description="User who created the component")
    project_id: str = Field(..., description="ID of the parent project")
    tags: List[str] = Field(..., description="Component tags")
    custom_metadata: Optional[Dict[str, Any]] = Field(None, description="Custom metadata fields")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")


class ComponentMetadataListResponse(BaseModel):
    """Response model for listing component metadata."""

    total: int = Field(..., description="Total number of components")
    components: List[ComponentMetadataResponse] = Field(
        ..., description="List of component metadata"
    )
    page: int = Field(1, description="Current page number")
    page_size: int = Field(50, description="Number of items per page")
