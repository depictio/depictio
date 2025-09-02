from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from depictio.models.models.base import MongoModel, PyObjectId, convert_objectid_to_str
from depictio.models.models.users import Permission


class BaseComponentMetadata(BaseModel):
    """Generic base model for all dashboard component metadata."""

    index: str = Field(..., description="Unique component identifier")
    component_type: Literal["card", "figure", "table", "interactive", "text", "jbrowse"] = Field(
        ..., description="Type of the component"
    )
    # Common fields across most component types
    wf_id: Optional[PyObjectId] = Field(None, description="Workflow ID")
    dc_id: Optional[PyObjectId] = Field(None, description="Data collection ID")
    dc_config: Optional[dict] = Field(None, description="Data collection configuration")

    model_config = ConfigDict(
        extra="allow",  # Allow additional fields for component-specific parameters
        arbitrary_types_allowed=True,
    )


class CardComponentMetadata(BaseComponentMetadata):
    """Metadata model for card components."""

    component_type: Literal["card"] = "card"
    title: Optional[str] = None
    column_name: Optional[str] = None
    column_type: Optional[str] = None
    aggregation: Optional[str] = None
    value: Optional[Any] = Field(None, alias="v")
    color: Optional[str] = None
    cols_json: Optional[dict] = Field(default_factory=dict)


class FigureComponentMetadata(BaseComponentMetadata):
    """Metadata model for figure components."""

    component_type: Literal["figure"] = "figure"
    visu_type: Optional[str] = None
    dict_kwargs: Optional[dict] = Field(default_factory=dict)
    query_params: Optional[dict] = Field(default_factory=dict)
    clustering: Optional[dict] = None
    theme: Optional[Union[str, dict]] = "light"


class TableComponentMetadata(BaseComponentMetadata):
    """Metadata model for table components."""

    component_type: Literal["table"] = "table"
    table_config: Optional[dict] = Field(default_factory=dict)
    query_params: Optional[dict] = Field(default_factory=dict)


class InteractiveComponentMetadata(BaseComponentMetadata):
    """Metadata model for interactive components."""

    component_type: Literal["interactive"] = "interactive"
    interactive_type: Optional[str] = None
    options: Optional[List[dict]] = Field(default_factory=list)
    default_value: Optional[Any] = None


class TextComponentMetadata(BaseComponentMetadata):
    """Metadata model for text components."""

    component_type: Literal["text"] = "text"
    content: Optional[str] = ""
    markdown: Optional[bool] = False
    style: Optional[dict] = Field(default_factory=dict)


class JBrowseComponentMetadata(BaseComponentMetadata):
    """Metadata model for JBrowse components."""

    component_type: Literal["jbrowse"] = "jbrowse"
    assembly_name: Optional[str] = None
    tracks: Optional[List[dict]] = Field(default_factory=list)


# Union type for all component metadata types
ComponentMetadata = Union[
    CardComponentMetadata,
    FigureComponentMetadata,
    TableComponentMetadata,
    InteractiveComponentMetadata,
    TextComponentMetadata,
    JBrowseComponentMetadata,
]


def validate_component_metadata(metadata_dict: dict) -> ComponentMetadata:
    """
    Validate and convert a metadata dictionary to the appropriate component metadata model.

    Args:
        metadata_dict: Raw metadata dictionary from database or session

    Returns:
        Validated component metadata instance

    Raises:
        ValueError: If component_type is unknown or validation fails
    """
    component_type = metadata_dict.get("component_type")

    if not component_type:
        raise ValueError("Missing component_type in metadata")

    metadata_classes = {
        "card": CardComponentMetadata,
        "figure": FigureComponentMetadata,
        "table": TableComponentMetadata,
        "interactive": InteractiveComponentMetadata,
        "text": TextComponentMetadata,
        "jbrowse": JBrowseComponentMetadata,
    }

    metadata_class = metadata_classes.get(component_type)
    if not metadata_class:
        raise ValueError(f"Unknown component_type: {component_type}")

    return metadata_class.model_validate(metadata_dict)


class DashboardData(MongoModel):
    dashboard_id: PyObjectId
    version: int = 1
    tmp_children_data: list | None = []
    stored_layout_data: list = []
    stored_children_data: list = []
    stored_metadata: List[BaseComponentMetadata] = Field(default_factory=list)
    stored_edit_dashboard_mode_button: list = []
    buttons_data: dict = {
        "unified_edit_mode": True,  # Unified edit mode replaces separate edit buttons
        "add_components_button": {"count": 0},
    }
    stored_add_button: dict = {"count": 0}
    title: str
    notes_content: str = ""
    permissions: Permission
    is_public: bool = False
    last_saved_ts: str = ""
    project_id: PyObjectId
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        # json_encoders={ObjectId: lambda oid: str(oid)},
    )

    @field_serializer("permissions")
    def serialize_permissions(self, permissions: Permission):
        # Convert any ObjectIds in the permissions object to strings
        # The exact implementation depends on what's in your Permission class
        return permissions.model_dump()

    @field_serializer("project_id")
    def serialize_project_id(self, project_id: PyObjectId) -> str:
        return str(project_id)

    @field_serializer("dashboard_id")
    def serialize_dashboard_id(self, dashboard_id: PyObjectId) -> str:
        return str(dashboard_id)

    @field_serializer("stored_metadata")
    def serialize_stored_metadata(self, stored_metadata: List[BaseComponentMetadata]) -> list:
        # Convert component metadata to dictionaries and handle ObjectIds
        metadata_dicts = []
        for metadata in stored_metadata:
            metadata_dict = (
                metadata.model_dump(by_alias=True)
                if hasattr(metadata, "model_dump")
                else dict(metadata)
            )
            metadata_dicts.append(metadata_dict)
        return convert_objectid_to_str(metadata_dicts)

    @field_validator("stored_metadata", mode="before")
    @classmethod
    def validate_stored_metadata(cls, v):
        """Validate and convert stored_metadata from various input formats."""
        if not v:
            return []

        validated_metadata = []
        for item in v:
            if isinstance(item, dict):
                # Try to convert dictionary to specific ComponentMetadata model, fallback to BaseComponentMetadata
                try:
                    specific_metadata = validate_component_metadata(item)
                    # Convert back to BaseComponentMetadata to ensure compatibility
                    validated_metadata.append(
                        BaseComponentMetadata.model_validate(specific_metadata.model_dump())
                    )
                except (ValueError, KeyError):
                    # If validation fails, use BaseComponentMetadata directly
                    validated_metadata.append(BaseComponentMetadata.model_validate(item))
            elif hasattr(item, "model_dump"):
                # Already a Pydantic model, convert to BaseComponentMetadata for consistency
                validated_metadata.append(BaseComponentMetadata.model_validate(item.model_dump()))
            else:
                # Unknown format, try to convert to BaseComponentMetadata
                validated_metadata.append(BaseComponentMetadata.model_validate(item))

        return validated_metadata
