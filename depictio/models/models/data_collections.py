from pathlib import Path
from typing import List, Optional, Union
import re
from pydantic import BaseModel, field_validator, model_validator

from depictio.models.models.base import MongoModel
from depictio.models.models.data_collections_types.jbrowse import DCJBrowse2Config
from depictio.models.models.data_collections_types.table import DCTableConfig
from depictio.models.utils import get_depictio_context
from depictio.models.logging import logger


class WildcardRegexBase(BaseModel):
    name: str
    wildcard_regex: str

    class Config:
        extra = "forbid"  # Reject unexpected fields

    @field_validator("wildcard_regex")
    def validate_files_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")


class Regex(BaseModel):
    pattern: str
    wildcards: Optional[List[WildcardRegexBase]] = None

    class Config:
        extra = "forbid"  # Reject unexpected fields

    @field_validator("pattern")
    def validate_files_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")


class ScanRecursive(BaseModel):
    regex_config: Regex
    max_depth: Optional[int] = None
    ignore: Optional[List[str]] = None

    class Config:
        extra = "forbid"


class ScanSingle(BaseModel):
    filename: str

    class Config:
        extra = "forbid"

    @field_validator("filename")
    def validate_filename(cls, v):
        DEPICTIO_CONTEXT = get_depictio_context()

        if DEPICTIO_CONTEXT.lower() == "cli":
            # validate filename & check if it exists
            if not Path(v).exists():
                raise ValueError(f"File {v} does not exist")
            return v
        else:
            if not v:
                raise ValueError("Filename cannot be empty")
            return v


class Scan(BaseModel):
    mode: str
    scan_parameters: Union[ScanRecursive, ScanSingle]

    @field_validator("mode")
    def validate_mode(cls, v):
        allowed_values = ["recursive", "single"]
        if v.lower() not in allowed_values:
            raise ValueError(f"mode must be one of {allowed_values}")
        return v

    @model_validator(mode="before")
    def validate_join(cls, values):
        type_value = values.get("mode").lower()  # normalize to lowercase for comparison
        scan_parameters = values.get("scan_parameters")
        if type_value == "recursive":
            if not isinstance(scan_parameters, ScanRecursive):
                values["scan_parameters"] = ScanRecursive(**values["scan_parameters"])
        elif type_value == "single":
            if not isinstance(scan_parameters, ScanSingle):
                values["scan_parameters"] = ScanSingle(**values["scan_parameters"])
        return values


class TableJoinConfig(BaseModel):
    on_columns: List[str]
    how: Optional[str]
    with_dc: List[str]

    class Config:
        extra = "forbid"  # Reject unexpected fields

    @field_validator("how")
    def validate_join_how(cls, v):
        allowed_values = ["inner", "outer", "left", "right"]
        if v.lower() not in allowed_values:
            raise ValueError(f"join_how must be one of {allowed_values}")
        return v


class DataCollectionConfig(MongoModel):
    type: str
    metatype: Optional[str] = None
    scan: Scan
    dc_specific_properties: Union[DCTableConfig, DCJBrowse2Config]
    join: Optional[TableJoinConfig] = None

    @field_validator("type", mode="before")
    def validate_type(cls, v):
        allowed_values = ["table", "jbrowse2"]
        lower_v = v.lower()
        if lower_v not in allowed_values:
            raise ValueError(f"type must be one of {allowed_values}")
        return lower_v  # return the normalized lowercase value

    @model_validator(mode="before")
    def validate_join(cls, values):
        type_value = values.get("type").lower()  # normalize to lowercase for comparison
        logger.debug(f"Validating join for type: {type_value}")

        # Get the dc_specific_properties
        dc_specific_properties = values.get("dc_specific_properties")

        if type_value == "table":
            # Check if it's already a DCTableConfig instance
            if not isinstance(dc_specific_properties, DCTableConfig):
                values["dc_specific_properties"] = DCTableConfig(**dc_specific_properties)
        elif type_value == "jbrowse2":
            # Check if it's already a DCJBrowse2Config instance
            if not isinstance(dc_specific_properties, DCJBrowse2Config):
                values["dc_specific_properties"] = DCJBrowse2Config(**dc_specific_properties)
        return values


class DataCollection(MongoModel):
    data_collection_tag: str
    config: DataCollectionConfig

    def __eq__(self, other):
        if isinstance(other, DataCollection):
            return all(
                getattr(self, field) == getattr(other, field)
                for field in self.model_fields.keys()
                if field not in ["id", "registration_time"]
            )
        return NotImplemented
