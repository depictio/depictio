import os
import re
from pydantic import BaseModel, DirectoryPath, FilePath, validator
from typing import Dict, Optional, List, Any
import bleach
import yaml


class FileConfig(BaseModel):
    regex: str
    format: str
    pandas_kwargs: Optional[Dict[str, Any]] = {}
    keep_columns: Optional[List[str]] = []

    @validator("regex")
    def validate_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")


class WorkflowConfig(BaseModel):
    location: str
    files: Dict[
        str, FileConfig
    ]  # Dictionary of FileConfigs indexed by file type name (e.g., "mosaicatcher_stats")


class Config(BaseModel):
    workflows: Dict[
        str, WorkflowConfig
    ]  # Dictionary of WorkflowConfigs indexed by workflow name (e.g., "snakemake--mosaicatcher-pipeline")



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
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return cls(**data)



from pathlib import Path
from pydantic import BaseModel, validator, ValidationError
import os

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



class Workflow(BaseModel):
    workflow_name: str
    description: str = None  # Optional description
    workflow_engine: str
    workflow_location: DirectoryPath

    @validator("workflow_engine")
    def validate_workflow_engine(cls, value):
        allowed_values = [
            "snakemake",
            "nextflow",
            "CWL",
            "galaxy",
            "smk",
            "nf",
            "nf-core",
        ]
        if value not in allowed_values:
            raise ValueError(f"workflow_engine must be one of {allowed_values}")
        return value

    @validator("description", pre=True, always=True)
    def sanitize_description(cls, value):
        # Strip any HTML tags and attributes
        sanitized = bleach.clean(value, tags=[], attributes={}, strip=True)
        # Ensure it's not overly long
        max_length = 500  # Set as per your needs
        return sanitized[:max_length]

    @validator("workflow_location", pre=True, always=True)
    def validate_location_name(cls, value, values):
        workflow_engine = values.get('workflow_engine')
        workflow_name = values.get('workflow_name')
        expected_name = f"{workflow_engine}--{workflow_name}"
        actual_name = os.path.basename(value)

        if actual_name != expected_name:
            raise ValueError(f"Directory name should be in format '{expected_name}' but got '{actual_name}'.")

        return value