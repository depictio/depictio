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
    def serialize_stored_metadata(self, stored_metadata: list) -> list:
        # Convert any ObjectIds in the stored_metadata list to strings
        return convert_objectid_to_str(stored_metadata)
