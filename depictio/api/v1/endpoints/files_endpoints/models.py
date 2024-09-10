from datetime import datetime
import os
from typing import List, Optional
from pydantic import (
    Field,
    FilePath,
    root_validator,
    validator,
)
from depictio.api.v1.endpoints.datacollections_endpoints.models import DataCollection, WildcardRegexBase
from depictio.api.v1.endpoints.user_endpoints.models import Permission
from depictio.api.v1.models.base import MongoModel, PyObjectId


class WildcardRegex(WildcardRegexBase):
    value: str


class File(MongoModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    # id: Optional[PyObjectId] = None
    file_location: FilePath
    S3_location: Optional[str] = None
    S3_key_hash: Optional[str] = None
    trackId: Optional[str] = None
    filename: str
    creation_time: datetime
    modification_time: datetime
    data_collection: DataCollection
    # file_hash: Optional[str] = None
    run_id: Optional[str] = None
    registration_time: datetime = datetime.now()
    wildcards: Optional[List[WildcardRegex]]
    permissions: Optional[Permission] = {"owners": [], "viewers": []}

    @root_validator(pre=True)
    def set_default_id(cls, values):
        if values is None or "id" not in values or values["id"] is None:
            return values  # Ensure we don't proceed if values is None
        values["id"] = PyObjectId()
        return values

    @validator("creation_time", pre=True, always=True)
    def validate_creation_time(cls, value):
        if type(value) is not datetime:
            try:
                dt = datetime.fromisoformat(value)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("Invalid datetime format")
        else:
            return value.strftime("%Y-%m-%d %H:%M:%S")

    @validator("modification_time", pre=True, always=True)
    def validate_modification_time(cls, value):
        if type(value) is not datetime:
            try:
                dt = datetime.fromisoformat(value)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("Invalid datetime format")
        else:
            return value.strftime("%Y-%m-%d %H:%M:%S")

    @validator("file_location")
    def validate_location(cls, value):
        if not os.path.exists(value):
            raise ValueError(f"The file '{value}' does not exist.")
        if not os.path.isfile(value):
            raise ValueError(f"'{value}' is not a file.")
        if not os.access(value, os.R_OK):
            raise ValueError(f"'{value}' is not readable.")
        return value

    # TODO: Implement file hashing to ensure file integrity
    # @validator("file_hash")
    # def validate_file_hash(cls, value):
    #     if value is not None:
    #         if not isinstance(value, str):
    #             raise ValueError("file_hash must be a string")
    #     return value
