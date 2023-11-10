from datetime import datetime
import os
from pathlib import Path
from typing import Type, Dict, List, Tuple, Optional, Any, Set
import bleach
from bson import ObjectId
import re
import yaml, json
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    FilePath,
    ValidationError,
    validator,
    root_validator,
)

from depictio.api.v1.models.base import DirectoryPath, PyObjectId

##################
# Authentication #
##################


class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: Optional[int] = None
    scope: Optional[str] = None
    user_id: PyObjectId

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class TokenData(BaseModel):
    user_id: PyObjectId
    exp: Optional[int] = None


###################
# User management #
###################


class User(BaseModel):
    user_id: PyObjectId = Field(default_factory=PyObjectId)
    username: str
    email: EmailStr

    class Config:
        json_encoders = {ObjectId: lambda v: str(v)}

    def __hash__(self):
        # Hash based on the unique user_id
        return hash(self.user_id)

    def __eq__(self, other):
        # Equality based on the unique user_id
        if isinstance(other, User):
            return self.user_id == other.user_id
        return False


class Group(BaseModel):
    user_id: PyObjectId = Field(default_factory=PyObjectId)
    name: str
    members: Set[User]  # Set of User objects instead of ObjectId

    @validator("members", each_item=True, pre=True)
    def ensure_unique_users(cls, user):
        if not isinstance(user, User):
            raise ValueError(
                f"Each member must be an instance of User, got {type(user)}"
            )
        return user

    # This function ensures there are no duplicate users in the group
    @root_validator(pre=True)
    def ensure_unique_member_ids(cls, values):
        members = values.get("members", [])
        unique_members = {member.user_id: member for member in members}.values()
        return {"members": set(unique_members)}

    # This function validates that each user_id in the members is unique
    @root_validator
    def check_user_ids_are_unique(cls, values):
        seen = set()
        members = values.get("members", [])
        for member in members:
            if member.user_id in seen:
                raise ValueError("Duplicate user_id found in group members.")
            seen.add(member.user_id)
        return values


class Permission(BaseModel):
    owners: List[User]
    viewers: Optional[List[User]] = set()  # Set default to empty set

    def dict(self, **kwargs):
        # Before converting to list, let's print the owners and viewers
        print("Converting to dict - Owners and Viewers as objects:")
        print("Owners:", self.owners)
        print("Viewers:", self.viewers)

        # Generate list of owner and viewer dictionaries
        owners_list = [owner.dict(**kwargs) for owner in self.owners]
        viewers_list = [viewer.dict(**kwargs) for viewer in self.viewers]

        print("Converting to dict - Owners and Viewers as lists of dicts:")
        print("Owners Dict List:", owners_list)
        print("Viewers Dict List:", viewers_list)

        return {"owners": owners_list, "viewers": viewers_list}

    @validator("owners", "viewers", pre=True, each_item=True)
    def convert_dict_to_user(cls, v):
        if isinstance(v, dict):
            return User(
                **v
            )  # Assuming `User` is a Pydantic model and can be instantiated like this
        elif not isinstance(v, User):
            raise ValueError("Permissions should be assigned to User instances.")
        return v

    @root_validator(pre=True)
    def validate_permissions(cls, values):
        print("Inside validate_permissions - Raw input values:")
        print(values)

        owners = values.get("owners", set())
        viewers = values.get("viewers", set())

        print("Inside validate_permissions - Parsed owners and viewers:")
        print("Owners:", owners)
        print("Viewers:", viewers)

        # Check if owners and viewers are sets and contain only User instances
        if not owners:
            raise ValueError("At least one owner is required.")

        # if not isinstance(owners, set) or any(not isinstance(owner, User) for owner in owners):
        #     raise ValueError("All owners must be User instances.")

        # if viewers and (not isinstance(viewers, set) or any(not isinstance(viewer, User) for viewer in viewers)):
        #     raise ValueError("All viewers must be User instances if provided.")

        return values

    # Here we ensure that there are no duplicate users across owners and viewers
    @root_validator
    def ensure_owners_and_viewers_are_unique(cls, values):
        owners = values.get("owners", set())
        viewers = values.get("viewers", set())
        owner_ids = {owner.user_id for owner in owners}
        viewer_ids = {viewer.user_id for viewer in viewers}

        # Check if there is any intersection between owners and viewers
        if not owner_ids.isdisjoint(viewer_ids):
            raise ValueError("A User cannot be both an owner and a viewer.")

        # You would add additional checks here to ensure all users exist in your database
        # If you're pulling from a real database, this would be the place to query it and validate

        return values


###################
# File management #
###################


def validate_datetime(value):
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("Invalid datetime format")


class File(BaseModel):
    file_location: FilePath
    filename: str
    creation_time: datetime
    modification_time: datetime
    data_collection_id: str
    file_hash: Optional[str] = None
    run_id: Optional[str] = None

    @validator("creation_time", pre=True, always=True)
    def validate_creation_time(cls, value):
        try:
            dt = datetime.fromisoformat(value)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError("Invalid datetime format")

    @validator("modification_time", pre=True, always=True)
    def validate_modification_time(cls, value):
        try:
            dt = datetime.fromisoformat(value)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError("Invalid datetime format")

    @validator("file_location")
    def validate_location(cls, value):
        if not os.path.exists(value):
            raise ValueError(f"The file '{value}' does not exist.")
        if not os.path.isfile(value):
            raise ValueError(f"'{value}' is not a file.")
        if not os.access(value, os.R_OK):
            raise ValueError(f"'{value}' is not readable.")
        return value

    @validator("file_hash")
    def validate_file_hash(cls, value):
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("file_hash must be a string")
        return value


###################
# Data Collection #
###################


class DataCollectionConfig(BaseModel):
    regex: str
    format: str
    pandas_kwargs: Optional[Dict[str, Any]] = {}
    keep_fields: Optional[List[str]] = []

    @validator("regex")
    def validate_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")

    @validator("keep_fields")
    def validate_keep_fields(cls, v):
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("keep_fields must be a list")
        return v

    @validator("pandas_kwargs")
    def validate_pandas_kwargs(cls, v):
        if v is not None:
            if not isinstance(v, dict):
                raise ValueError("pandas_kwargs must be a dictionary")
        return v


class DataCollection(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId)
    data_collection_id: Optional[str]
    description: str = None  # Optional description
    config: DataCollectionConfig
    workflow_id: Optional[str]
    gridfs_file_id: Optional[str] = Field(
        alias="gridfsId", default=None
    )  # If the field is named differently in MongoDB

    # @validator("data_collection_id", pre=True, always=True)
    # def extract_data_collection_id(cls, value):
    #     return value.split("/")[-1]

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: str  # Convert ObjectId instances to strings in JSON output
        }

    @validator("description", pre=True, always=True)
    def sanitize_description(cls, value):
        # Strip any HTML tags and attributes
        sanitized = bleach.clean(value, tags=[], attributes={}, strip=True)
        return sanitized


###################
# Workflows #
###################


class WorkflowConfig(BaseModel):
    # workflow_id: Optional[str]
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId)
    parent_runs_location:  List[DirectoryPath]
    workflow_version: Optional[str]
    config: Optional[Dict]
    runs_regex: Optional[str]

    # Update below to allow for multiple run locations and check that they exist
    @validator("parent_runs_location")
    def validate_run_location(cls, value):
        if not isinstance(value, list):
            raise ValueError("run_location must be a list")
        for location in value:
            if not os.path.exists(location):
                raise ValueError(f"The directory '{location}' does not exist.")
            if not os.path.isdir(location):
                raise ValueError(f"'{location}' is not a directory.")
            if not os.access(location, os.R_OK):
                raise ValueError(f"'{location}' is not readable.")
        return value
    
   

    @validator("runs_regex")
    def validate_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")
    # Generate version validator - if no version specified, set to 1.0.0
    @validator("workflow_version", pre=True, always=True)
    def set_version(cls, value):
        if value is None:
            return "1.0.0"
        return value


class WorkflowRun(BaseModel):
    run_id: Optional[str]
    files: List[File] = []
    workflow_config: WorkflowConfig
    run_location: List[DirectoryPath]
    execution_time: datetime
    execution_profile: Optional[Dict]



    @validator("files")
    def validate_files(cls, value):
        if not isinstance(value, list):
            raise ValueError("files must be a list")
        return value

    @validator("workflow_config")
    def validate_workflow_config(cls, value):
        if not isinstance(value, WorkflowConfig):
            raise ValueError("workflow_config must be a WorkflowConfig")
        return value

    @validator("execution_time", pre=True, always=True)
    def validate_execution_time(cls, value):
        return validate_datetime(value)


class WorkflowSystem(BaseModel):
    workflow_language: str
    engine_version: Optional[str]
    workflow_engine: Optional[str]

    @validator("workflow_engine")
    def validate_workflow_engine_value(cls, value):
        allowed_values = [
            "snakemake",
            "nextflow",
            "toil",
            "cwltool",
            "arvados",
            "streamflow",
        ]
        if value not in allowed_values:
            raise ValueError(f"workflow_engine must be one of {allowed_values}")
        return value

    @validator("workflow_language")
    def validate_workflow_language_value(cls, value):
        allowed_values = [
            "snakemake",
            "nextflow",
            "CWL",
            "galaxy",
            "smk",
            "nf",
        ]
        if value not in allowed_values:
            raise ValueError(f"workflow_language must be one of {allowed_values}")
        return value


class Workflow(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    workflow_name: str = None
    workflow_engine: str = None
    workflow_id: str
    # workflow_engine: WorkflowSystem
    workflow_description: str
    data_collections: Optional[Dict[str, DataCollection]]
    runs: Optional[Dict[str, WorkflowRun]]
    workflow_config: Optional[WorkflowConfig]
    # data_collection_ids: Optional[List[str]] = []
    permissions: Optional[
        Permission
    ]  # Add this field to capture ownership and viewing permissions

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: str  # Convert ObjectId instances to strings in JSON output
        }


    @root_validator(pre=True)
    def set_workflow_id(cls, values):
        workflow_engine = values.get("workflow_engine")
        workflow_name = values.get("workflow_name")
        if workflow_engine and workflow_name:
            values["workflow_id"] = f"{workflow_engine}/{workflow_name}"
        return values

    # Example usage
    # @classmethod
    # def from_mongo(cls, data: dict):
    #     # Convert the _id from ObjectId to str
    #     data["id"] = str(data["_id"])
    #     del data["_id"]  # Optional: remove the original _id if not needed
    #     return cls(**data)

    @root_validator(pre=True)
    def populate_data_collection_ids(cls, values):
        workflow_id = values.get("workflow_id")
        data_collections = values.get("data_collections", {})
        for collection in data_collections.values():
            collection["workflow_id"] = workflow_id
        return values

    # @root_validator(pre=True)
    # def set_workflow_name(cls, values):
    #     workflow_engine = values.get("workflow_id").split("/")[0]
    #     workflow_name = values.get("workflow_id").split("/")[1]
    #     values["workflow_name"] = f"{workflow_name}"
    #     values["workflow_engine"] = f"{workflow_engine}"
    #     return values

    @validator("workflow_description", pre=True, always=True)
    def sanitize_description(cls, value):
        # Strip any HTML tags and attributes
        sanitized = bleach.clean(value, tags=[], attributes={}, strip=True)
        # Ensure it's not overly long
        max_length = 500  # Set as per your needs
        return sanitized[:max_length]

    @validator("data_collections")
    def validate_data_collections(cls, value):
        if not isinstance(value, dict):
            raise ValueError("data_collections must be a dictionary")
        return value

    @validator("runs")
    def validate_runs(cls, value):
        if not isinstance(value, dict):
            raise ValueError("runs must be a dictionary")
        return value

    @validator("permissions", always=True)
    def set_default_permissions(cls, value, values):
        if not value:
            # Here we initialize the owners to include the creator by default.
            # This assumes that `creator_id` or a similar field exists in the `Workflow` model.
            workflow_creator = values.get("creator_id")
            if workflow_creator:
                return Permission(owners={workflow_creator}, viewers=set())
        return value


class RootConfig(BaseModel):
    workflows: List[Workflow]


###################
# GridFS #
###################


class GridFSFileInfo(BaseModel):
    filename: str
    file_id: str
    length: int


class GridFSAggregatedFile(BaseModel):
    id: PyObjectId = Field(alias="_id")
    filename: str
    chunkSize: int
    length: int
    uploadDate: datetime = Field(alias="uploadDate")

    class Config:
        json_encoders = {ObjectId: str}
        allow_population_by_field_name = True


########


class Collections(BaseModel):
    data_collection: str
    workflow_collection: str
    runs_collection: str
    files_collection: str


class Settings(BaseModel):
    mongo_url: str
    mongo_db: str
    collections: Collections
    redis_host: str
    redis_port: int
    redis_db: int
    redis_cache_ttl: int
    user_secret_key: str

    @classmethod
    def from_yaml(cls, path: str):
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return cls(**data)
