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
        print("Validator called")  # Debug print
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")



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
