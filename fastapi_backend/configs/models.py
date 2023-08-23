from datetime import datetime
import os
from pathlib import Path
from typing import Type, Dict, List, Tuple, Optional, Any
import bleach
from bson import ObjectId
from pydantic import BaseModel, FilePath, ValidationError, validator, root_validator
import re

import yaml


class DirectoryPath(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: str) -> str:
        path = Path(value)
        if not path.exists():
            raise ValueError(f"The directory '{value}' does not exist.")
        if not path.is_dir():
            raise ValueError(f"'{value}' is not a directory.")
        return value


class ObjectIdStr(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: str) -> str:
        if not ObjectId.is_valid(value):
            raise ValueError(f"'{value}' is not a valid ObjectId.")
        return str(value)


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

    @validator("creation_time", pre=True, always=True)
    def validate_creation_time(cls, value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("Invalid datetime format")

    @validator("modification_time", pre=True, always=True)
    def validate_modification_time(cls, value):
        try:
            return datetime.fromisoformat(value)
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
    data_collection_id: str = None
    description: str = None  # Optional description
    config: DataCollectionConfig

    # @validator("data_collection_id", pre=True, always=True)
    # def extract_data_collection_id(cls, value):
    #     return value.split("/")[-1]

    @validator("description", pre=True, always=True)
    def sanitize_description(cls, value):
        # Strip any HTML tags and attributes
        sanitized = bleach.clean(value, tags=[], attributes={}, strip=True)
        return sanitized


class WorkflowConfig(BaseModel):
    # workflow_id: Optional[str]
    parent_runs_location: str
    workflow_version: Optional[str]
    config: Optional[Dict]
    runs_regex: Optional[str]


    @validator("runs_regex")
    def validate_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")


class WorkflowRun(BaseModel):
    run_id: Optional[str]
    files: List[File] = []
    workflow_config: WorkflowConfig
    run_location: DirectoryPath
    execution_time: datetime
    execution_profile: Optional[Dict]

    @validator("run_location", pre=True, always=True)
    def validate_location_name(cls, value, values):
        if not os.path.exists(value):
            raise ValueError(f"The directory '{value}' does not exist.")
        if not os.path.isdir(value):
            raise ValueError(f"'{value}' is not a directory.")
        return value

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
    workflow_name: str = None
    workflow_engine: str = None
    workflow_id: str
    # workflow_engine: WorkflowSystem
    workflow_description: str
    data_collections: Optional[Dict[str, DataCollection]]
    runs: Optional[Dict[str, WorkflowRun]]
    workflow_config: Optional[WorkflowConfig]

    @root_validator(pre=True)
    def set_workflow_name(cls, values):
        workflow_engine = values.get("workflow_id").split("/")[0]
        workflow_name = values.get("workflow_id").split("/")[1]
        values["workflow_name"] = f"{workflow_name}"
        values["workflow_engine"] = f"{workflow_engine}"
        return values

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


class RootConfig(BaseModel):
    workflows: List[Workflow]


########


class Collections(BaseModel):
    data_collection: str
    workflow_collection: str


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
