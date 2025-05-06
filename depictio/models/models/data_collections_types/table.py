from typing import Any

from pydantic import BaseModel, field_validator


class DCTableConfig(BaseModel):
    format: str
    polars_kwargs: dict[str, Any] = {}
    keep_columns: list[str] | None = []
    columns_description: dict[str, str] | None = {}
    # TODO: validate than the columns are in the dataframe

    class Config:
        extra = "forbid"  # Reject unexpected fields

    @field_validator("format")
    def validate_format(cls, v):
        allowed_values = ["csv", "tsv", "parquet", "feather", "xls", "xlsx"]
        if v.lower() not in allowed_values:
            raise ValueError(f"format must be one of {allowed_values}")

        return v.lower()

    # TODO : check that the columns to keep are in the dataframe
    # @field_validator("keep_columns")
    # def validate_keep_fields(cls, v):
    #     if v is not None:
    #         if not isinstance(v, list):
    #             raise ValidationError("keep_columns must be a list")
    #     return v

    # # TODO: check polars different arguments
    # @field_validator("polars_kwargs")
    # def validate_pandas_kwargs(cls, v):
