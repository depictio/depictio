from datetime import datetime

from pydantic import BaseModel, field_validator

from depictio.models.models.base import MongoModel, PyObjectId
from depictio.models.models.users import UserBase


class DeltaTableColumn(BaseModel):
    name: str
    type: str
    description: str | None = None  # Optional description
    specs: dict | None = None

    class Config:
        extra = "forbid"  # Reject unexpected fields

    @field_validator("type")
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


class Aggregation(MongoModel):
    aggregation_time: datetime = datetime.now()
    aggregation_by: UserBase
    aggregation_version: int = 1
    aggregation_hash: str
    aggregation_columns_specs: list[DeltaTableColumn] = []

    @field_validator("aggregation_version")
    def validate_version(cls, value):
        if not isinstance(value, int):
            raise ValueError("version must be an integer")
        return value


class FilterCondition(BaseModel):
    class Config:
        extra = "forbid"  # Reject unexpected fields

    above: int | float | str | None = None
    equal: int | float | str | None = None
    under: int | float | str | None = None


class DeltaTableQuery(MongoModel):
    columns: list[str]
    filters: dict[str, FilterCondition]
    sort: list[str] | None = []
    limit: int | None = None
    offset: int | None = None


class Test(BaseModel):
    test: str


class DeltaTableAggregated(MongoModel):
    data_collection_id: PyObjectId
    delta_table_location: str
    aggregation: list[Aggregation] = []


class UpsertDeltaTableAggregated(BaseModel):
    data_collection_id: PyObjectId
    delta_table_location: str
    update: bool = False
    deltatable_size_bytes: int | None = None
