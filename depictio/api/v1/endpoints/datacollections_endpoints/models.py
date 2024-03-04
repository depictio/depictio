
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import bleach
import re
from pydantic import (
    BaseModel,
    Field,
    validator,
    root_validator,
)
from depictio.api.v1.endpoints.deltatables_endpoints.models import DeltaTableAggregated

from depictio.api.v1.models.base import MongoModel, PyObjectId


###################
# Data Collection #
###################


class TableJoinConfig(BaseModel):
    on_columns: List[str]
    how: Optional[str]
    with_dc: List[str]
    # lsuffix: str
    # rsuffix: str


    @validator("how")
    def validate_join_how(cls, v):
        allowed_values = ["inner", "outer", "left", "right"]
        if v.lower() not in allowed_values:
            raise ValueError(f"join_how must be one of {allowed_values}")
        return v



class Wildcard(BaseModel):
    name: str
    regex: str
    join_with: Optional[str] = None

    @validator("regex")
    def validate_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")

    @validator("join_with")
    def validate_join_with(cls, v):
        if v is not None:
            if not isinstance(v, str):
                raise ValueError("join_with must be a string")
        return v


    

class DataCollectionConfig(BaseModel):
    type: str
    files_regex: str
    format: str
    polars_kwargs: Optional[Dict[str, Any]] = {}
    keep_columns: Optional[List[str]] = []
    table_join: Optional[TableJoinConfig]
    # jbrowse_params: Optional[Dict[str, Any]] = {}
    index_extension: Optional[str] = None
    regex_wildcards: Optional[List[Wildcard]] = []
    jbrowse_template_location: Optional[str] = None


    @root_validator
    def check_wildcards_defined(cls, values):
        files_regex = values.get('files_regex')
        regex_wildcards = values.get('regex_wildcards', [])
        
        if files_regex:
            wildcards = re.findall(r"\{(\w+)\}", files_regex)
            defined_wildcards = {wc.name for wc in regex_wildcards}
            
            undefined_wildcards = set(wildcards) - defined_wildcards
            if undefined_wildcards:
                raise ValueError(f"Undefined wildcards in files_regex: {', '.join(undefined_wildcards)}")
        
        return values


    # @validator("jbrowse_params")
    # def validate_jbrowse_params(cls, v):
    #     if v is not None:
    #         if not isinstance(v, dict):
    #             raise ValueError("jbrowse_params must be a dictionary")
    #     # allowed values
    #     allowed_values = ["category", "assemblyName"]
    #     for key in v:
    #         if key not in allowed_values:
    #             raise ValueError(f"jbrowse_params key must be one of {allowed_values}")
    #     return v
    


    @validator("type")
    def validate_type(cls, v):
        allowed_values = ["table", "genome browser"]
        if v.lower() not in allowed_values:
            raise ValueError(f"type must be one of {allowed_values}")
        return v

    @validator("format")
    def validate_format(cls, v, values, **kwargs):
        allowed_values_for_table = ["csv", "tsv", "parquet", "feather", "xls", "xlsx"]
        allowed_values_for_genome_browser = ["gff3", "gff", "gtf", "bed", "bigbed", "vcf", "bigwig", "bw", "bam", "cram", "bai", "crai", "fai", "tbi", "csi", "gzi", "2bit", "sizes", "chrom.sizes", "chromSizes", "fasta", "fa", "fna", "fasta.gz"]
        
        # Use the 'type' to determine allowed formats
        data_type = values.get('type', '').lower()  # Ensuring type is accessed in lowercase
        if data_type:  # Check if 'type' is available
            allowed_values = {
                "table": allowed_values_for_table,
                "genome browser": allowed_values_for_genome_browser
            }.get(data_type, [])  # Default to empty list if type is not recognized
            
            if v.lower() not in allowed_values:
                allowed_formats_str = ", ".join(allowed_values)
                raise ValueError(f"Invalid format '{v}' for type '{data_type}'. Allowed formats for this type are: {allowed_formats_str}")
        else:
            # Handle case where 'type' is not yet validated or missing
            raise ValueError("Type must be validated before format.")

        return v

 

    # TODO : check that the columns to keep are in the dataframe
    @validator("keep_columns")
    def validate_keep_fields(cls, v):
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("keep_columns must be a list")
        return v

    # TODO: check polars different arguments
    @validator("polars_kwargs")
    def validate_pandas_kwargs(cls, v):
        if v is not None:
            if not isinstance(v, dict):
                raise ValueError("polars_kwargs must be a dictionary")
        return v


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
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
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
    
    # @validator("data_collection_id", pre=True, always=True)
    # def extract_data_collection_id(cls, value):
    #     return value.split("/")[-1]

    @validator("description", pre=True, always=True)
    def sanitize_description(cls, value):
        # Strip any HTML tags and attributes
        sanitized = bleach.clean(value, tags=[], attributes={}, strip=True)
        return sanitized
