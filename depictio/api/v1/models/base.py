from datetime import datetime
import hashlib
from pathlib import Path, PosixPath
from bson import ObjectId
from pydantic import BaseModel
import re

import json


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
    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
            ObjectId: lambda oid: str(oid),
            PosixPath: lambda path: str(path),
        }

    @classmethod
    def from_mongo(cls, data: dict):
        """We must convert _id into "id"."""
        if not data:
            return data

        # Helper function to convert nested documents
        def convert_ids(document):
            if isinstance(document, list):
                return [convert_ids(item) for item in document]
            if isinstance(document, dict):
                document = {key: convert_ids(value) for key, value in document.items()}
                id = document.pop("_id", None)
                if id:
                    document["id"] = id
            return document

        data = convert_ids(data)
        return cls(**data)

    def mongo(self, **kwargs):
        exclude_unset = kwargs.pop("exclude_unset", False)
        by_alias = kwargs.pop("by_alias", True)

        parsed = self.dict(
            exclude_unset=exclude_unset,
            by_alias=by_alias,
            **kwargs,
        )

        # Mongo uses `_id` as default key. We should stick to that as well.
        if "_id" not in parsed and "id" in parsed:
            parsed["_id"] = parsed.pop("id")

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


class HashModel(BaseModel):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: str) -> str:
        if not re.match(r"^[a-fA-F0-9]{64}$", value):
            raise ValueError("Invalid hash")
        return value

    @classmethod
    def compute_hash(cls, value: dict) -> str:
        hash_str = json.dumps(value, sort_keys=True).encode("utf-8")
        return hashlib.sha256(hash_str).hexdigest()
