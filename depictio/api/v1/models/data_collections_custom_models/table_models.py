from typing import Dict, List, Optional, Any
from pydantic import (
    BaseModel,
    validator,
)




class DCTableConfig(BaseModel):
    format: str
    polars_kwargs: Optional[Dict[str, Any]] = {}
    keep_columns: Optional[List[str]] = []
    columns_description: Optional[Dict[str, str]] = {}
    # TODO: validate than the columns are in the dataframe

    @validator("format")
    def validate_format(cls, v):
        allowed_values = ["csv", "tsv", "parquet", "feather", "xls", "xlsx"]
        if v.lower() not in allowed_values:
            raise ValueError(f"format must be one of {allowed_values}")
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
