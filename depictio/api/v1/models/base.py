from datetime import datetime
import os
from pathlib import Path
from typing import Type, Dict, List, Tuple, Optional, Any, Set
import bleach
from bson import ObjectId
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    FilePath,
    ValidationError,
    validator,
    root_validator,
)
import re

import yaml, json


def convert_objectid_to_str(item):
    if isinstance(item, dict):
        return {key: convert_objectid_to_str(value) for key, value in item.items()}
    elif isinstance(item, list):
        return [convert_objectid_to_str(elem) for elem in item]
    elif isinstance(item, ObjectId):
        return str(item)
    elif isinstance(item, datetime):
        return item.strftime("%Y-%m-%d %H:%M:%S")
    else:
        return item


# Custom JSON encoder
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, PyObjectId):
            return str(obj)
        return super().default(obj)


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")


class MongoModel(BaseModel):

    class Config():
        allow_population_by_field_name = True
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
            ObjectId: lambda oid: str(oid),
        }

    @classmethod
    def from_mongo(cls, data: dict):
        """We must convert _id into "id". """
        if not data:
            return data
        id = data.pop('_id', None)
        return cls(**dict(data, id=id))

    def mongo(self, **kwargs):
        exclude_unset = kwargs.pop('exclude_unset', True)
        by_alias = kwargs.pop('by_alias', True)

        parsed = self.dict(
            exclude_unset=exclude_unset,
            by_alias=by_alias,
            **kwargs,
        )

        # Mongo uses `_id` as default key. We should stick to that as well.
        if '_id' not in parsed and 'id' in parsed:
            parsed['_id'] = parsed.pop('id')
        
        # Convert PosixPath to str
        for key, value in parsed.items():
            if isinstance(value, Path):
                parsed[key] = str(value)

        return parsed

class DirectoryPath(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: str) -> str:
        path = Path(value)
        if not path.exists():
            raise ValueError(f"The directory '{value}' does not exist.")
        if not path.is_dir():
            raise ValueError(f"'{value}' is not a directory.")
        return value

class HashModel(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: str) -> str:
        if not re.match(r"^[a-fA-F0-9]{64}$", value):
            raise ValueError("Invalid hash")
        return value