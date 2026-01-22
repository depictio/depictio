import os
import re
from datetime import datetime
from typing import Literal

from beanie import Document
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.logging import logger
from depictio.models.models.base import MongoModel
from depictio.models.models.data_collections import DataCollection, DataCollectionResponse
from depictio.models.models.joins import JoinDefinition
from depictio.models.models.links import DCLink
from depictio.models.models.users import Permission
from depictio.models.models.workflows import Workflow, WorkflowResponse


class ProjectPermissionRequest(BaseModel):
    project_id: str
    permissions: dict
    model_config = ConfigDict(arbitrary_types_allowed=True)


class Project(MongoModel):
    name: str
    data_management_platform_project_url: str | None = None
    workflows: list[Workflow] = []  # Optional for basic projects
    data_collections: list[DataCollection] = []  # Direct data collections for basic projects
    joins: list[JoinDefinition] = []  # Top-level join definitions for client-side joining
    links: list[DCLink] = []  # Universal DC links for cross-DC filtering
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

    @model_validator(mode="after")
    def validate_data_collection_tag_uniqueness(self) -> "Project":
        """
        Warn if data collection tags are not unique across workflows.

        This helps prevent ambiguity when using unscoped tags in joins.
        """
        all_tags: dict[str, list[str]] = {}  # tag -> list of workflows using it

        for workflow in self.workflows:
            for dc in workflow.data_collections:
                tag = dc.data_collection_tag
                if tag not in all_tags:
                    all_tags[tag] = []
                all_tags[tag].append(workflow.name)

        # Check for duplicates
        duplicates = {tag: workflows for tag, workflows in all_tags.items() if len(workflows) > 1}

        if duplicates:
            duplicate_info = ", ".join(
                [f"'{tag}' in {workflows}" for tag, workflows in duplicates.items()]
            )
            logger.warning(
                f"⚠️  Duplicate DC tags found across workflows: {duplicate_info}. "
                "Consider using workflow-scoped references (e.g., 'workflow.tag') in joins "
                "to avoid ambiguity."
            )

        return self


class ProjectResponse(Project):
    """Permissive Project model for API responses.

    Extends Project with extra="allow" and uses WorkflowResponse for nested workflows
    to handle extra fields at all nesting levels.
    Inherits the from_mongo() method from MongoModel which handles _id → id conversion.
    """

    # Override to use permissive response models
    workflows: list[WorkflowResponse] = []
    data_collections: list[DataCollectionResponse] = []

    model_config = ConfigDict(extra="allow")


class ProjectBeanie(Project, Document):
    class Settings:
        name = "projects"
