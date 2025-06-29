import re
from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator

from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.logging import logger
from depictio.models.models.base import MongoModel
from depictio.models.models.data_collections_types.jbrowse import DCJBrowse2Config
from depictio.models.models.data_collections_types.table import DCTableConfig


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
    wildcards: list[WildcardRegexBase] | None = None

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
    max_depth: int | None = None
    ignore: list[str] | None = None

    class Config:
        extra = "forbid"


class ScanSingle(BaseModel):
    filename: str

    class Config:
        extra = "forbid"

    @field_validator("filename")
    def validate_filename(cls, v):
        if DEPICTIO_CONTEXT.lower() == "cli":
            # Add debugging
            import os

            current_dir = os.getcwd()
            abs_path = os.path.abspath(v)
            normalized_path = os.path.normpath(v)

            # Log the paths for debugging
            logger.debug(f"Current working directory: {current_dir}")
            logger.debug(f"Relative path: {v}")
            logger.debug(f"Absolute path: {abs_path}")
            logger.debug(f"Normalized path: {normalized_path}")
            logger.debug(f"Path exists check: {Path(v).exists()}")

            # Try to see if the file exists with different path resolutions
            resolved_path = Path(v).resolve()
            logger.debug(f"Resolved path: {resolved_path}")
            logger.debug(f"Resolved path exists: {resolved_path.exists()}")

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
    scan_parameters: ScanRecursive | ScanSingle

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
                if isinstance(scan_parameters, dict) and "regex_config" in scan_parameters:
                    try:
                        values["scan_parameters"] = ScanRecursive(**scan_parameters)  # type: ignore[missing-argument]
                    except Exception:
                        # Keep original if conversion fails
                        pass
        elif type_value == "single":
            if not isinstance(scan_parameters, ScanSingle):
                if isinstance(scan_parameters, dict) and "filename" in scan_parameters:
                    try:
                        values["scan_parameters"] = ScanSingle(**scan_parameters)  # type: ignore[missing-argument]
                    except Exception:
                        # Keep original if conversion fails
                        pass
        return values


class TableJoinConfig(BaseModel):
    on_columns: list[str]
    how: str = "inner"
    with_dc: list[str]

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
    metatype: str | None = None
    scan: Scan
    dc_specific_properties: DCTableConfig | DCJBrowse2Config
    join: TableJoinConfig | None = None

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
        # logger.debug(f"Validating join for type: {type_value}")

        # Get the dc_specific_properties
        dc_specific_properties = values.get("dc_specific_properties")

        if type_value == "table":
            # Check if it's already a DCTableConfig instance
            if not isinstance(dc_specific_properties, DCTableConfig):
                if isinstance(dc_specific_properties, dict) and "format" in dc_specific_properties:
                    try:
                        values["dc_specific_properties"] = DCTableConfig(**dc_specific_properties)  # type: ignore[missing-argument]
                    except Exception:
                        # Keep original if conversion fails
                        pass
        elif type_value == "jbrowse2":
            # Check if it's already a DCJBrowse2Config instance
            if not isinstance(dc_specific_properties, DCJBrowse2Config):
                if isinstance(dc_specific_properties, dict):
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
