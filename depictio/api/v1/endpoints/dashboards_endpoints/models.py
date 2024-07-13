from typing import Dict, List, Optional, Union
import bleach
import re
from bson import ObjectId
from pydantic import (
    BaseModel,
    Field,
    validator,
)

from depictio.api.v1.models.base import MongoModel, PyObjectId
# FIXME: Replace user with the real user model
# from depictio.api.v1.models.users_endpoints.models import User

class DashboardData(MongoModel):
    dashboard_id: str
    # id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    version: str
    tmp_children_data: Optional[List]
    stored_layout_data: Dict
    stored_metadata: List
    stored_edit_dashboard_mode_button: List
    stored_add_button: Dict
    title: str
    owner: str
    last_saved_ts: str

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: lambda oid: str(oid),  # or `str` for simplicity
        }