from pydantic import ConfigDict, Field, field_serializer, model_validator

from depictio.models.models.base import MongoModel, PyObjectId
from depictio.models.models.dashboard_structure import DashboardTabStructure
from depictio.models.models.users import Permission


class DashboardData(MongoModel):
    dashboard_id: PyObjectId
    version: int = 2  # Increment version for new structure

    # New hierarchical dashboard structure
    dashboard_structure: DashboardTabStructure = Field(
        default_factory=DashboardTabStructure,
        description="Hierarchical structure containing tabs, sections, and components",
    )

    # Keep legacy fields for backward compatibility (deprecated)
    buttons_data: dict = {
        "unified_edit_mode": False,  # Default edit mode OFF for new dashboards
        "add_components_button": {"count": 0},
    }
    stored_add_button: dict = {"count": 0}
    title: str
    icon: str = "mdi:view-dashboard-outline"  # Default dashboard icon
    notes_content: str = ""
    permissions: Permission
    is_public: bool = False
    last_saved_ts: str = ""
    project_id: PyObjectId
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        # json_encoders={ObjectId: lambda oid: str(oid)},
    )

    @model_validator(mode="before")
    @classmethod
    def ensure_icon_field(cls, data):
        """Ensure icon field exists for database migration compatibility."""
        if isinstance(data, dict) and "icon" not in data:
            data["icon"] = "mdi:view-dashboard-outline"
        return data

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

    @field_serializer("dashboard_structure")
    def serialize_dashboard_structure(self, dashboard_structure: DashboardTabStructure) -> dict:
        """Serialize dashboard structure to dict."""
        return dashboard_structure.model_dump()

    def ensure_default_tab(self) -> None:
        """Ensure dashboard has at least one default tab with proper structure."""
        # Initialize dashboard structure if empty
        if not self.dashboard_structure.tabs:
            default_tab = self.dashboard_structure.ensure_default_tab(str(self.dashboard_id))

        # Ensure default tab ID is set
        if not self.dashboard_structure.default_tab_id:
            default_tab = self.dashboard_structure.get_default_tab()
            if default_tab:
                self.dashboard_structure.default_tab_id = default_tab.id

    def get_current_tab(self):
        """Get the current active tab (default tab for now)."""
        self.ensure_default_tab()
        return self.dashboard_structure.get_default_tab()
