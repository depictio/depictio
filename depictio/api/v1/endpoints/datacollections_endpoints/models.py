from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import bleach
import re
from bson import ObjectId
from pydantic import (
    BaseModel,
    Field,
    validator,
    root_validator,
)
from depictio.api.v1.endpoints.deltatables_endpoints.models import DeltaTableAggregated

from depictio.api.v1.models.base import HashModel, MongoModel, PyObjectId
from depictio.api.v1.models.data_collections_custom_models.jbrowse_models import DCJBrowse2Config
from depictio.api.v1.models.data_collections_custom_models.table_models import DCTableConfig


###################
# Data Collection #
###################




class DataCollectionConfig(BaseModel):
    type: str
    files_regex: str
    dc_specific_properties: Union[DCTableConfig, DCJBrowse2Config]


    @validator("files_regex")
    def validate_files_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")

    @validator("type")
    def validate_type(cls, v):
        allowed_values = ["table", "jbrowse2"]
        if v.lower() not in allowed_values:
            raise ValueError(f"type must be one of {allowed_values}")
        return v

    @validator("dc_specific_properties", pre=True)
    def set_correct_type(cls, v, values):
        if "type" in values:
            if values["type"].lower() == "table":
                return DCTableConfig(**v)
            elif values["type"].lower() == "jbrowse2":
                return DCJBrowse2Config(**v)
        raise ValueError("Unsupported type")


class DataCollectionColumn(MongoModel):
    name: str
    type: str
    description: Optional[str] = None  # Optional description
    specs: Optional[Dict] = None

    @validator("type")
    def validate_column_type(cls, v):
        allowed_values = [
            "string",
            "utf8",
            "object",
            "int64",
            "float64",
            "bool",
            "date",
            "datetime",
            "time",
            "category",
        ]
        if v.lower() not in allowed_values:
            raise ValueError(f"column_type must be one of {allowed_values}")
        return v


class DataCollection(MongoModel):
    # id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    id: Optional[PyObjectId] = None
    # id: Optional[PyObjectId] = Field(default=None, alias='_id')
    data_collection_tag: str
    description: str = None  # Optional description
    config: DataCollectionConfig
    # workflow_id: Optional[str]
    # gridfs_file_id: Optional[str] = Field(
    #     alias="gridfsId", default=None
    # )  # If the field is named differently in MongoDB
    deltaTable: Optional[DeltaTableAggregated] = None
    columns: Optional[List[DataCollectionColumn]] = None
    registration_time: datetime = datetime.now()

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: lambda oid: str(oid),  # or `str` for simplicity
        }

    # @root_validator(pre=True)
    # def set_default_id(cls, values):
    #     if values is None or "id" not in values or values["id"] is None:
    #         return values  # Ensure we don't proceed if values is None
    #     values["id"] = PyObjectId()
    #     return values

    @validator("description", pre=True, always=True)
    def sanitize_description(cls, value):
        # Strip any HTML tags and attributes
        sanitized = bleach.clean(value, tags=[], attributes={}, strip=True)
        return sanitized

    def __eq__(self, other):
        if isinstance(other, DataCollection):
            return all(
                getattr(self, field) == getattr(other, field)
                for field in self.__fields__.keys()
                if field not in ['id', 'registration_time']
            )
        return NotImplemented