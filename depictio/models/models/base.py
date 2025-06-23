import hashlib
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import bleach
from bson import ObjectId
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_core import CoreSchema, core_schema


def convert_objectid_to_str(item):
    if isinstance(item, dict):
        return {key: convert_objectid_to_str(value) for key, value in item.items()}
    elif isinstance(item, list):
        return [convert_objectid_to_str(elem) for elem in item]
    elif isinstance(item, ObjectId):
        return str(item)
    elif isinstance(item, datetime):
        return item.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(item, Path):
        return str(item)
    else:
        return item


class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """
        Defines the core schema for PyObjectId.
        """
        return core_schema.no_info_plain_validator_function(
            cls.validate,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> dict[str, Any]:
        return {"type": "string", "format": "objectid"}

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if isinstance(v, str) and ObjectId.is_valid(v):
            return ObjectId(v)
        if isinstance(v, PyObjectId):
            return ObjectId(str(v))
        raise ValueError(f"Invalid ObjectId: {v}")


class MongoModel(BaseModel):
    id: PyObjectId = Field(default=PyObjectId())
    description: str | None = None
    flexible_metadata: dict | None = None
    hash: str | None = None
    model_config = ConfigDict(
        extra="forbid",
        # allow_population_by_field_name=True,
    )

    # Customize serialization of ObjectId
    @field_serializer("id")
    def serialize_id(self, id: PyObjectId):
        return str(id)

    @model_validator(mode="before")
    @classmethod
    def ensure_id(cls, values: dict) -> dict:
        """
        Ensures the `_id` field uses the provided value or generates a new ObjectId.
        """

        # If values is not a dict, skip processing and return as-is
        if not isinstance(values, dict):
            return values

        # If '_id' is provided, move it to 'id' and remove '_id'
        if "_id" in values:
            values["id"] = values.pop("_id")
        if "id" in values and values["id"] is not None:
            # If `id` is provided, validate and retain it
            values["id"] = PyObjectId.validate(values["id"])
        else:
            # Generate a new ObjectId if no valid ID is provided
            values["id"] = PyObjectId()
        return values

    @field_validator("description")
    def sanitize_description(cls, value):
        """
        Sanitizes the input to ensure it is plain text and neutralizes any code.
        Converts special characters to their HTML-safe equivalents to neutralize code execution.
        Ensures no HTML tags or JavaScript can persist in the sanitized description.
        """
        # If value is a Description instance, extract the string
        # if isinstance(value, Description):
        #     value = value.description

        if not value:
            return None

        # Step 1: Convert special characters to their HTML-safe equivalents
        neutralized = html.escape(value)

        # Step 2: Use bleach to remove all HTML tags and attributes
        sanitized = bleach.clean(neutralized, tags=[], attributes={}, strip=True)

        # Step 3: Check if HTML tags were successfully removed
        if any(char in sanitized for char in ("<", ">", "&lt;", "&gt;")):
            raise ValueError("Description contains disallowed HTML content.")

        # Step 4: Enforce a maximum character length
        if len(sanitized) > 1000:
            raise ValueError("Description must be less than 1000 characters.")

        return sanitized

    @classmethod
    def from_mongo(cls, data: dict):
        """We must convert _id into "id"."""
        if not data:
            return cls(**data)

        # Helper function to convert nested documents
        def convert_ids(document):
            if isinstance(document, list):
                return [convert_ids(item) for item in document]
            if isinstance(document, dict):
                document = {key: convert_ids(value) for key, value in document.items()}
                id = document.pop("_id", None)
                if id:
                    document["id"] = id
            if isinstance(document, str):
                return str(document)
            return document

        data = convert_ids(data)
        # Ensure 'hash' is explicitly retained
        hash_value = data.pop("hash", None)
        instance = cls(**data)
        if hash_value is not None:
            setattr(instance, "hash", hash_value)
        # else:
        # Compute hash if not present
        # setattr(instance, "hash", HashModel.compute_hash(data))
        return instance

    def mongo(self, **kwargs):
        exclude_unset = kwargs.pop("exclude_unset", False)
        by_alias = kwargs.pop("by_alias", True)

        parsed = self.model_dump(
            exclude_unset=exclude_unset,
            by_alias=by_alias,
            **kwargs,
        )

        # This function already correctly converts 'id' to '_id' recursively
        # for all nested objects and arrays
        def convert_ids(obj):
            if isinstance(obj, dict):
                new_dict = {}
                for key, value in obj.items():
                    # Rename 'id' keys to '_id'
                    if key == "id":
                        new_key = "_id"
                        # Ensure value is converted to ObjectId
                        if isinstance(value, str) and ObjectId.is_valid(value):
                            new_dict[new_key] = ObjectId(value)
                        elif isinstance(value, PyObjectId) or isinstance(value, ObjectId):
                            new_dict[new_key] = ObjectId(str(value))
                        else:
                            # If it's not a valid ObjectId, keep it as is
                            new_dict[new_key] = value
                    elif isinstance(value, str) and ObjectId.is_valid(value):
                        # If the value is a valid ObjectId string, convert it
                        new_dict[key] = ObjectId(value)
                    else:
                        new_key = key
                        # Recursively convert nested structures
                        new_dict[new_key] = convert_ids(value)

                return new_dict
            elif isinstance(obj, list):
                return [convert_ids(item) for item in obj]
            else:
                return obj

        parsed = convert_ids(parsed)

        # Double-check the top-level _id to ensure it's an ObjectId
        if "_id" in parsed and isinstance(parsed["_id"], str) and ObjectId.is_valid(parsed["_id"]):
            parsed["_id"] = ObjectId(parsed["_id"])

        # Convert PosixPath to str
        for key, value in parsed.items():
            if isinstance(value, Path):
                parsed[key] = str(value)

        return parsed


# TODO: move to pydantic DirectoryPath (https://docs.pydantic.dev/latest/api/types/#pydantic.types.DirectoryPath)


class DirectoryPath(BaseModel):
    path: str

    @field_validator("path", mode="before")
    def validate_path(cls, v):
        # Ensure the path is valid
        if not isinstance(v, str | Path):
            raise ValueError(f"Invalid type for path: {type(v)}. Must be a string or Path.")
        v = Path(v)  # Ensure it's a Path object
        if not v.exists():
            raise ValueError(f"The directory '{v}' does not exist.")
        if not v.is_dir():
            raise ValueError(f"'{v}' is not a directory.")
        if not os.access(v, os.R_OK):
            raise ValueError(f"'{v}' is not readable.")
        return str(v)  # Return validated Path object


class HashModel(BaseModel):
    value: str  # Store the hash string

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: str):
        if not re.match(r"^[a-fA-F0-9]{64}$", value):
            raise ValueError("Invalid hash")
        # Return an instance of HashModel
        hash_str = json.dumps(value, sort_keys=True).encode("utf-8")
        return hashlib.sha256(hash_str).hexdigest()
