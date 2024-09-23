from typing import Dict, List, Optional
from bson import ObjectId
from pydantic import Field

from depictio.api.v1.endpoints.user_endpoints.models import Permission
from depictio.api.v1.models.base import MongoModel, PyObjectId
# FIXME: Replace user with the real user model
# from depictio.api.v1.models.users_endpoints.models import User


class DashboardData(MongoModel):
    dashboard_id: str
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    version: int = 1
    tmp_children_data: Optional[List] = []
    stored_layout_data: Dict = {}
    stored_metadata: List = []
    stored_edit_dashboard_mode_button: List = []
    stored_add_button: Dict = {"count": 0}
    title: str
    permissions: Permission = {"owners": [], "viewers": []}
    last_saved_ts: str = ""
    # TODO: add permissions

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: lambda oid: str(oid),  # or `str` for simplicity
        }
