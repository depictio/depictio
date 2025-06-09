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
    return convert_objectid_to_str(model.model_dump(exclude_none=exclude_none))  # type: ignore[no-any-return]


@validate_call
def get_config(filename: str) -> dict:
    """
    Get the config file.
    """
    if not filename.endswith(".yaml"):
        raise ValueError("Invalid config file. Must be a YAML file.")
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
            logger.info(f"Processing string with env vars: '{config}'")

            # Handle variables with curly braces: {$VAR} -> $VAR
            processed = re.sub(r"\{\$([A-Za-z_][A-Za-z0-9_]*)\}", r"$\1", config)
            logger.info(f"After brace removal: '{processed}'")

            # Now substitute environment variables
            result = os.path.expandvars(processed)
            logger.info(f"After expandvars: '{result}'")

            # Special handling for $PWD if it wasn't expanded
            if "$PWD" in result:
                current_dir = os.getcwd()
                result = result.replace("$PWD", current_dir)
                logger.info(f"After PWD replacement: '{result}'")

            # Special handling for $GITHUB_WORKSPACE
            if "$GITHUB_WORKSPACE" in result:
                if "GITHUB_WORKSPACE" in os.environ:
                    workspace = os.environ["GITHUB_WORKSPACE"]
                    result = result.replace("$GITHUB_WORKSPACE", workspace)
                    logger.info(f"After GITHUB_WORKSPACE replacement: '{result}'")
                else:
                    logger.warning("GITHUB_WORKSPACE not found in environment")
                    logger.info(f"Current environment variables: {os.environ}")

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
