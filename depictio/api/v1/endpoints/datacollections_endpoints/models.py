from typing import Dict, List, Optional, Union
import bleach
import re
from bson import ObjectId
from pydantic import (
    BaseModel,
    Field,
    validator,
)

from depictio.api.v1.models.base import MongoModel, PyObjectId
from depictio.api.v1.models.data_collections_custom_models.jbrowse_models import DCJBrowse2Config
from depictio.api.v1.models.data_collections_custom_models.table_models import DCTableConfig

class DataCollectionConfig(MongoModel):
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



class DataCollection(MongoModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    # _id: Optional[PyObjectId] = None
    # id: Optional[PyObjectId] = Field(default=None, alias='_id')
    data_collection_tag: str
    description: str = None  # Optional description
    config: DataCollectionConfig
    # workflow_id: Optional[str]

    # registration_time: datetime = datetime.now()

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: lambda oid: str(oid),  # or `str` for simplicity
        }

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