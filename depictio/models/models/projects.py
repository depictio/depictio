import os
import re
from datetime import datetime
from typing import Literal

from beanie import Document
from pydantic import BaseModel, ConfigDict, field_validator

from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.models.base import MongoModel
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.users import Permission
from depictio.models.models.workflows import Workflow


class ProjectPermissionRequest(BaseModel):
    project_id: str
    permissions: dict
    model_config = ConfigDict(arbitrary_types_allowed=True)


class Project(MongoModel):
    name: str
    data_management_platform_project_url: str | None = None
    workflows: list[Workflow] = []  # Optional for basic projects
    data_collections: list[DataCollection] = []  # Direct data collections for basic projects
    yaml_config_path: str | None = None  # Optional for basic projects
    permissions: Permission
    is_public: bool = False
    hash: str | None = None
    registration_time: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    project_type: Literal["basic", "advanced"] = "basic"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v:
            raise ValueError("Project name cannot be empty")
        return v

    # @model_validator(mode="before")
    # def compute_hash(cls, values: dict) -> dict:
    #     """
    #     Compute the hash of the project configuration.
    #     """
    #     # Compute the hash of the project configuration after removing all the "registration_time" fields in project and nested objects
    #     values.pop("registration_time", None)
    #     for workflow in values["workflows"]:
    #         if workflow.get("registration_time"):
    #             # Remove registration_time from workflow and its data_collections
    #             workflow.pop("registration_time", None)
    #         for data_collection in workflow["data_collections"]:
    #             if data_collection.get("registration_time"):
    #                 # Remove registration_time from data_collection
    #                 data_collection.pop("registration_time", None)
    #             # data_collection.pop("registration_time", None)

    #     hash_str = hashlib.md5(
    #         json.dumps(convert_objectid_to_str(values), sort_keys=True).encode()
    #     ).hexdigest()
    #     values["hash"] = hash_str
    #     return values

    @field_validator("yaml_config_path")
    @classmethod
    def validate_yaml_config_path(cls, v, info):
        # Basic projects don't require yaml_config_path
        project_type = info.data.get("project_type", "basic") if info.data else "basic"
        if project_type == "basic" and not v:
            return None

        if DEPICTIO_CONTEXT.lower() == "cli":
            # Check if looks like a valid path but do not check if it exists
            if v and not os.path.isabs(v):
                raise ValueError("Path must be absolute")
            return v
        else:
            if not v and project_type == "advanced":
                raise ValueError("Path cannot be empty for advanced projects")
            return v

    @field_validator("data_management_platform_project_url")
    @classmethod
    def validate_data_management_platform_project_url(cls, v):
        # Check if looks like a valid URL
        if not v:
            return v
        if not re.match(r"https?://", v):
            raise ValueError("Invalid URL")
        return v


class ProjectBeanie(Project, Document):
    class Settings:
        name = "projects"
