from datetime import datetime
import os
from beanie import PydanticObjectId
import yaml
from typing import Any, Dict, Type
from pydantic import BaseModel, ValidationError, validate_call
from bson import ObjectId

from depictio.models.logging import logger
from depictio.models.models.base import convert_objectid_to_str


def get_depictio_context():
    return os.getenv("DEPICTIO_CONTEXT")


@validate_call
def convert_model_to_dict(model: BaseModel, exclude_none: bool = False) -> Dict:
    """
    Convert a Pydantic model to a dictionary.

    Args:
        model: The Pydantic model to convert
        exclude_none: If True, fields with None values will be excluded
    """
    return convert_objectid_to_str(model.model_dump(exclude_none=exclude_none))  # type: ignore[no-any-return]


@validate_call
def get_config(filename: str) -> Dict:
    """
    Get the config file.
    """
    if not filename.endswith(".yaml"):
        raise ValueError("Invalid config file. Must be a YAML file.")
    if not os.path.exists(filename):
        raise ValueError(f"The file '{filename}' does not exist.")
    if not os.path.isfile(filename):
        raise ValueError(f"'{filename}' is not a file.")
    with open(filename, "r") as f:
        yaml_data = yaml.safe_load(f)
    if not isinstance(yaml_data, dict):
        raise ValueError("Invalid config file: expected a dictionary.")
    return yaml_data


def substitute_env_vars(config: Any) -> Any:
    """
    Recursively substitute environment variables in the configuration dictionary.
    """
    if isinstance(config, dict):
        return {k: substitute_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [substitute_env_vars(item) for item in config]
    elif isinstance(config, str):
        # Substitute environment variables in string values
        return os.path.expandvars(config)
    else:
        return config


@validate_call
def validate_model_config(config: dict, pydantic_model: Type[BaseModel]) -> BaseModel:
    """
    Load and validate the YAML configuration
    """
    if not isinstance(config, dict):
        raise ValueError("Invalid config. Must be a dictionary.")
    try:
        # List environment variables
        logger.info(f"Env args: {os.environ}")

        # Substitute environment variables within the config
        substituted_config = substitute_env_vars(config)
        logger.info(f"Substituted Config: {substituted_config}")

        # Load the config into a Pydantic model
        data = pydantic_model(**substituted_config)
        logger.info(f"Resulting object model: {data}")
    except ValidationError as e:
        raise ValueError(f"Invalid config: {e}")
    return data


# Helper function to make data JSON serializable
@validate_call
def make_json_serializable(data):
    """Convert any non-JSON serializable objects (like ObjectId) to strings."""
    result = {}
    for key, value in data.items():
        if isinstance(value, (PydanticObjectId, ObjectId)):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, BaseModel):
            result[key] = make_json_serializable(value.model_dump())
        elif isinstance(value, dict):
            result[key] = make_json_serializable(value)
        elif isinstance(value, list):
            result[key] = [
                make_json_serializable(item)
                if isinstance(item, dict)
                else str(item)
                if isinstance(item, (PydanticObjectId, ObjectId))
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result
