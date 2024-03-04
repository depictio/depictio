from datetime import datetime
import os
from typing import Optional
from pydantic import (
    Field,
    FilePath,
    validator,
)
from depictio.api.v1.endpoints.datacollections_endpoints.models import DataCollection

from depictio.api.v1.models.base import MongoModel, PyObjectId


###################
# File management #
###################



def validate_datetime(value):
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("Invalid datetime format")



class File(MongoModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    file_location: FilePath
    S3_location: Optional[str] = None
    filename: str
    creation_time: datetime
    modification_time: datetime
    data_collection: DataCollection
    # file_hash: Optional[str] = None
    run_id: Optional[str] = None
    aggregated: Optional[bool] = False
    registration_time: datetime = datetime.now()

    @validator("S3_location")
    def validate_S3_location(cls, value):
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("S3_location must be a string")
            if not value.startswith("s3://"):
                raise ValueError("Invalid S3 location")
        return value

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

    # @validator("file_hash")
    # def validate_file_hash(cls, value):
    #     if value is not None:
    #         if not isinstance(value, str):
    #             raise ValueError("file_hash must be a string")
    #     return value