from typing import Dict, List, Optional, Any
import re
import polars
from pydantic import (
    BaseModel,
    validator,
)
from depictio.api.v1.endpoints.deltatables_endpoints.models import DeltaTableAggregated, DeltaTableColumn


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


class DCTableConfig(BaseModel):
    format: str
    polars_kwargs: Optional[Dict[str, Any]] = {}
    keep_columns: Optional[List[str]] = []
    table_join: Optional[TableJoinConfig]

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
