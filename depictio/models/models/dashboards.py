from typing import Dict, List, Optional
from bson import ObjectId
from pydantic import ConfigDict

from depictio.models.models.users import Permission
from depictio.models.models.base import MongoModel, PyObjectId


class DashboardData(MongoModel):
    dashboard_id: str
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
        json_encoders={ObjectId: lambda oid: str(oid)},
    )
