from typing import Optional

from pydantic import ConfigDict, field_serializer

from depictio.models.models.base import MongoModel, PyObjectId, convert_objectid_to_str
from depictio.models.models.users import Permission


class DashboardData(MongoModel):
    dashboard_id: PyObjectId
    version: int = 1
    tmp_children_data: list | None = []
    stored_layout_data: list = []
    stored_children_data: list = []
    stored_metadata: list = []
    stored_edit_dashboard_mode_button: list = []
    # Dual-panel layout storage (for left/right grid layouts)
    left_panel_layout_data: list = []
    right_panel_layout_data: list = []
    buttons_data: dict = {
        "unified_edit_mode": True,  # Default edit mode ON for dashboard owners
        "add_components_button": {"count": 0},
    }
    stored_add_button: dict = {"count": 0}
    title: str
    subtitle: str = ""
    icon: str = "mdi:view-dashboard"
    icon_color: str = "orange"
    icon_variant: str = "filled"
    workflow_system: str = "none"
    notes_content: str = ""
    permissions: Permission
    is_public: bool = False
    last_saved_ts: str = ""
    project_id: PyObjectId

    # Tab support (backward compatible)
    is_main_tab: bool = True
    parent_dashboard_id: Optional[PyObjectId] = None
    tab_order: int = 0

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

    @field_serializer("parent_dashboard_id")
    def serialize_parent_dashboard_id(
        self, parent_dashboard_id: Optional[PyObjectId]
    ) -> Optional[str]:
        return str(parent_dashboard_id) if parent_dashboard_id else None

    @field_serializer("stored_metadata")
    def serialize_stored_metadata(self, stored_metadata: list) -> list:
        # Convert any ObjectIds in the stored_metadata list to strings
        return convert_objectid_to_str(stored_metadata)
