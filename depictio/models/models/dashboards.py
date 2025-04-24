from typing import Dict, List, Optional
from bson import ObjectId
from pydantic import ConfigDict, field_serializer

from depictio.models.models.users import Permission
from depictio.models.models.base import MongoModel, PyObjectId, convert_objectid_to_str


class DashboardData(MongoModel):
    dashboard_id: PyObjectId
    version: int = 1
    tmp_children_data: Optional[List] = []
    stored_layout_data: Dict = {}
    stored_children_data: List = []
    stored_metadata: List = []
    stored_edit_dashboard_mode_button: List = []
    buttons_data: Dict = {
        "edit_components_button": True,
        "add_components_button": {"count": 0},
        "edit_dashboard_mode_button": True,
    }
    stored_add_button: Dict = {"count": 0}
    title: str
    permissions: Permission
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
    def serialize_stored_metadata(self, stored_metadata: List) -> List:
        # Convert any ObjectIds in the stored_metadata list to strings
        return convert_objectid_to_str(stored_metadata)