import os
import re
from datetime import datetime
from typing import Any

import yaml
from beanie import PydanticObjectId
from bson import ObjectId

# from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError, validate_call

from depictio.models.logging import logger
from depictio.models.models.base import convert_objectid_to_str


def get_depictio_context():
    # Ensure environment variables are loaded before accessing
    context = os.getenv("DEPICTIO_CONTEXT", "server")
    return context


@validate_call
def convert_model_to_dict(model: BaseModel, exclude_none: bool = False) -> dict:
    """
    Convert a Pydantic model to a dictionary.

    Args:
        model: The Pydantic model to convert
        exclude_none: If True, fields with None values will be excluded
    """
    return convert_objectid_to_str(model.model_dump(exclude_none=exclude_none))


@validate_call
def get_config(filename: str) -> dict:
    """
    Get the config file.
    """
    if not filename.endswith((".yaml", ".yml")):
        raise ValueError(f"Invalid config file '{filename}': it must be a .yaml or .yml file.")
    if not os.path.exists(filename):
        raise ValueError(f"The file '{filename}' does not exist.")
    if not os.path.isfile(filename):
        raise ValueError(f"'{filename}' is not a file.")
    with open(filename) as f:
        yaml_data = yaml.safe_load(f)
    if not isinstance(yaml_data, dict):
        raise ValueError("Invalid config file: expected a dictionary.")
    return yaml_data


def substitute_env_vars(config: Any) -> Any:
    """
    Recursively substitute environment variables in the configuration dictionary.
    Handles environment variables with or without curly braces.
    """
    if isinstance(config, dict):
        return {k: substitute_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [substitute_env_vars(item) for item in config]
    elif isinstance(config, str):
        # Check if string contains environment variables
        if re.search(r"\$|{\$", config):
            # Handle variables with curly braces: {$VAR} -> $VAR
            processed = re.sub(r"\{\$([A-Za-z_][A-Za-z0-9_]*)\}", r"$\1", config)
            # The names only, at DEBUG: the values, and the strings that hold them, can
            # be tokens and passwords, and `depictio -v` logs this module at INFO.
            names = sorted(set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", processed)))
            logger.debug(f"Environment variables in a configuration value: {', '.join(names)}")

            # Now substitute environment variables
            result = os.path.expandvars(processed)

            # Special handling for $PWD if it wasn't expanded
            if "$PWD" in result:
                current_dir = os.getcwd()
                result = result.replace("$PWD", current_dir)

            # Special handling for $GITHUB_WORKSPACE
            if "$GITHUB_WORKSPACE" in result:
                if "GITHUB_WORKSPACE" in os.environ:
                    workspace = os.environ["GITHUB_WORKSPACE"]
                    result = result.replace("$GITHUB_WORKSPACE", workspace)
                else:
                    logger.warning("GITHUB_WORKSPACE not found in environment")

            return result
        else:
            # No environment variables, return as-is
            return config
    else:
        return config


# def substitute_env_vars(config: Any) -> Any:
#     """
#     Recursively substitute environment variables in the configuration dictionary.
#     """
#     if isinstance(config, dict):
#         return {k: substitute_env_vars(v) for k, v in config.items()}
#     elif isinstance(config, list):
#         return [substitute_env_vars(item) for item in config]
#     elif isinstance(config, str):
#         # Substitute environment variables in string values
#         return os.path.expandvars(config)
#     else:
#         return config


@validate_call
def validate_model_config(config: dict, pydantic_model: type[BaseModel]) -> BaseModel:
    """
    Load and validate the YAML configuration
    """
    if not isinstance(config, dict):
        raise ValueError("Invalid config. Must be a dictionary.")
    try:
        # Substitute environment variables within the config. Neither the environment
        # nor the substituted config is logged: both can hold tokens and passwords.
        substituted_config = substitute_env_vars(config)

        # Load the config into a Pydantic model
        data = pydantic_model(**substituted_config)
        logger.debug(f"Validated {pydantic_model.__name__} configuration")
    except ValidationError as e:
        raise ValueError(f"Invalid config: {e}")
    return data


# Helper function to make data JSON serializable
@validate_call
def make_json_serializable(data):
    """Convert any non-JSON serializable objects (like ObjectId) to strings."""
    result = {}
    for key, value in data.items():
        if isinstance(value, PydanticObjectId | ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, BaseModel):
            result[key] = make_json_serializable(value.model_dump())
        elif isinstance(value, dict):
            result[key] = make_json_serializable(value)
        elif isinstance(value, list):
            result[key] = [
                (
                    make_json_serializable(item)
                    if isinstance(item, dict)
                    else (str(item) if isinstance(item, PydanticObjectId | ObjectId) else item)
                )
                for item in value
            ]
        else:
            result[key] = value
    return result
