from datetime import datetime
import os
from pathlib import Path
from typing import Type, Dict, List, Tuple, Optional, Any, Set
import bleach
from bson import ObjectId
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    FilePath,
    ValidationError,
    validator,
    root_validator,
)
import re

import yaml, json

from depictio.api.v1.models.base import DirectoryPath, PyObjectId

###################
# User management #
###################


class UserORM(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    username: str
    email: EmailStr

    class Config:
        allow_population_by_field_name = True
        json_encoders = {ObjectId: str}
        orm_mode = True


class PermissionORM(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    owners: List[PyObjectId]
    viewers: Optional[List[PyObjectId]] = set()  # Set default to empty set

    class Config:
        allow_population_by_field_name = True
        json_encoders = {ObjectId: str}
        orm_mode = True


###################
# File management #
###################


class FileORM(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    file_location: FilePath
    filename: str
    creation_time: datetime
    modification_time: datetime
    data_collection_id: PyObjectId
    file_hash: Optional[str] = None
    run_id: Optional[str] = None

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: str  # Convert ObjectId instances to strings in JSON output
        }
        orm_mode = True


###################
# Data Collection #
###################


class DataCollectionConfigORM(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    regex: str
    format: str
    pandas_kwargs: Optional[Dict[str, Any]] = {}
    keep_fields: Optional[List[str]] = []

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: str  # Convert ObjectId instances to strings in JSON output
        }
        orm_mode = True


class DataCollectionORM(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    data_collection_id: str
    description: str = None  # Optional description
    config: PyObjectId
    workflow_id: PyObjectId
    gridfs_file_id: Optional[str] = Field(alias="gridfsId", default=None)

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: str  # Convert ObjectId instances to strings in JSON output
        }
        orm_mode = True


###################
# Workflows #
###################


class WorkflowConfigORM(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    workflow_id: PyObjectId
    parent_runs_location: str
    workflow_version: Optional[str]
    config: Optional[Dict]
    runs_regex: Optional[str]

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: str  # Convert ObjectId instances to strings in JSON output
        }
        orm_mode = True


class WorkflowRunORM(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    run_id: str
    files: List[PyObjectId] = []
    workflow_config: PyObjectId
    run_location: DirectoryPath
    execution_time: datetime
    execution_profile: Optional[Dict]

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: str  # Convert ObjectId instances to strings in JSON output
        }
        orm_mode = True


class WorkflowORM(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    workflow_id: str
    workflow_name: str
    workflow_engine: str
    workflow_description: str
    data_collections_ids: Optional[List[PyObjectId]]
    runs_ids: Optional[List[PyObjectId]]
    workflow_config: Optional[PyObjectId]
    permissions: Optional[List[PyObjectId]]

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: str  # Convert ObjectId instances to strings in JSON output
        }
        orm_mode = True
