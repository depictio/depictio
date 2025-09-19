from typing import Any, Optional

from pydantic import ConfigDict, field_serializer, model_serializer

from depictio.models.dashboard_tab_structure import DashboardTabStructure
from depictio.models.models.base import MongoModel, PyObjectId, convert_objectid_to_str
from depictio.models.models.users import Permission


class DashboardData(MongoModel):
    dashboard_id: PyObjectId
    version: int = 1  # Dashboard version (user-facing version number)

    # Tab-based structure
    tab_structure: Optional[DashboardTabStructure] = None

    # Dashboard metadata
    title: str
    notes_content: str = ""
    permissions: Permission
    is_public: bool = False
    last_saved_ts: str = ""
    project_id: PyObjectId
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="allow",  # Allow legacy fields during transition period
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

    @field_serializer("tab_structure")
    def serialize_tab_structure(
        self, tab_structure: Optional[DashboardTabStructure]
    ) -> Optional[dict]:
        # Serialize the tab structure to dict for MongoDB storage
        return tab_structure.model_dump() if tab_structure else None

    def has_tab_structure(self) -> bool:
        """Check if this dashboard uses the tab-based structure."""
        return self.tab_structure is not None

    def get_active_structure(self) -> Optional[DashboardTabStructure]:
        """Get the active dashboard structure."""
        return self.tab_structure

    @model_serializer(mode="wrap")
    def serialize_model(self, serializer, info) -> dict[str, Any]:
        """
        Custom model serializer that converts all ObjectIds to strings,
        including those in legacy fields allowed by extra="allow".
        """
        # Get the default serialization using the wrapped serializer
        data = serializer(self)

        # Convert all ObjectIds to strings recursively
        return convert_objectid_to_str(data)
