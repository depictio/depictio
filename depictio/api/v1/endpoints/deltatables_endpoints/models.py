from datetime import datetime
from typing import Dict, List, Optional, Union
from bson import ObjectId
from pydantic import (
    BaseModel,
    validator,
)
from depictio.api.v1.endpoints.user_endpoints.models import User

from depictio.api.v1.models.base import MongoModel, PyObjectId


class DeltaTableColumn(BaseModel):
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


class Aggregation(MongoModel):
    aggregation_time: datetime = datetime.now()
    aggregation_by: User
    aggregation_version: int = 1
    aggregation_hash: str
    aggregation_columns_specs: List[DeltaTableColumn] = []

    # @validator("aggregation_time", pre=True, always=True)
    # def validate_creation_time(cls, value):
    #     if type(value) is not datetime:
    #         try:
    #             dt = datetime.fromisoformat(value)
    #             return dt.strftime("%Y-%m-%d %H:%M:%S")
    #         except ValueError:
    #             raise ValueError("Invalid datetime format")
    #     else:
    #         return value.strftime("%Y-%m-%d %H:%M:%S")

    @validator("aggregation_version")
    def validate_version(cls, value):
        if not isinstance(value, int):
            raise ValueError("version must be an integer")
        return value


class FilterCondition(BaseModel):
    above: Optional[Union[int, float, str]] = None
    equal: Optional[Union[int, float, str]] = None
    under: Optional[Union[int, float, str]] = None


class DeltaTableQuery(MongoModel):
    columns: List[str]
    filters: Dict[str, FilterCondition]
    sort: Optional[List[str]] = []
    limit: Optional[int] = None
    offset: Optional[int] = None


class DeltaTableAggregated(MongoModel):
    id: Optional[PyObjectId] = None
    # id: Optional[PyObjectId] = None
    data_collection_id: PyObjectId
    delta_table_location: str
    aggregation: List[Aggregation] = []

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: lambda oid: str(oid),  # or `str` for simplicity
        }


    def __eq__(self, other):
        if isinstance(other, DeltaTableAggregated):
            return all(
                getattr(self, field) == getattr(other, field)
                for field in self.__fields__.keys()
                if field not in ['id']
            )
        return NotImplemented

    # @validator("aggregation")
    # def validate_aggregation(cls, value):
    #     if not isinstance(value, list):
    #         raise ValueError("aggregation must be a list")
    #     if len(value) > 0:
    #         for aggregation in value:
    #             if not isinstance(aggregation, Aggregation):
    #                 raise ValueError("aggregation Aggregation be a list of FilesAggregation")
    #     elif len(value) == 0:
    #         raise ValueError("No aggregation found")
    #     return value
