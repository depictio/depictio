from datetime import datetime
import re
from typing import List, Optional
from bson import ObjectId
from pydantic import Field, validator
from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow
from depictio.api.v1.models.base import MongoModel, PyObjectId


class Project(MongoModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    depictio_version: str
    name: str
    description: Optional[str]
    data_management_platform_project_url: Optional[str]
    workflows: List[Workflow]

    @validator("depictio_version")
    def validate_version(cls, v):
        # Using a simple regex pattern to validate semantic versioning
        pattern = r"^\d+\.\d+\.\d+$"
        if not re.match(pattern, v):
            raise ValueError("Invalid version number, must be in format X.Y.Z where X, Y, Z are integers")
        return v

    class Config:
        json_encoders = {
            ObjectId: str,  # Convert ObjectId to string
            datetime: lambda dt: dt.isoformat(),  # Convert datetime to ISO format
        }
