
import hashlib
import os
from typing import Dict, List, Type

from pydantic import BaseModel, ValidationError
import yaml

from depictio.api.v1.endpoints.datacollections_endpoints.models import DataCollection
from depictio.api.v1.endpoints.user_endpoints.models import Permission, User
from depictio.api.v1.endpoints.workflow_endpoints.models import Workflow
from depictio.api.v1.models.top_structure import RootConfig
from depictio.api.v1.configs.logging import logger

def get_config(filename: str):
    """
    Get the config file.
    """
    if not filename.endswith(".yaml"):
        raise ValueError("Invalid config file. Must be a YAML file.")
    if not os.path.exists(filename):
        raise ValueError(f"The file '{filename}' does not exist.")
    if not os.path.isfile(filename):
        raise ValueError(f"'{filename}' is not a file.")
    else:
        with open(filename, "r") as f:
            yaml_data = yaml.safe_load(f)
        return yaml_data
    

def substitute_env_vars(config: Dict) -> Dict:
    """
    Recursively substitute environment variables in the configuration dictionary.
    
    Args:
        config (Dict): Configuration dictionary with potential environment variable placeholders.

    Returns:
        Dict: Configuration dictionary with substituted environment variables.
    """
    # Recursively handle environment variables substitution in nested dictionaries and lists
    if isinstance(config, dict):
        return {k: substitute_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [substitute_env_vars(item) for item in config]
    elif isinstance(config, str):
        # Substitute environment variables in string values
        return os.path.expandvars(config)
    else:
        return config


def validate_config(config: Dict, pydantic_model: Type[BaseModel]) -> BaseModel:
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
        data = pydantic_model(**config)
    except ValidationError as e:
        raise ValueError(f"Invalid config: {e}")
    return data


def populate_file_models(workflow: Workflow) -> List[DataCollection]:
    """
    Returns a list of DataCollection models for a given workflow.
    """

    datacollections_models = []
    for metadata in workflow.data_collections:
        data_collection_tag = metadata.data_collection_tag
        datacollection_instance = DataCollection(
            data_collection_tag=data_collection_tag,
            description=metadata.description,
            config=metadata.config,
            workflow_tag=workflow.workflow_tag,
        )
        # datacollection_instance.config.data_collection_id = datacollection_id
        # datacollection_instance.config.workflow_id = workflow.workflow_id
        datacollections_models.append(datacollection_instance)

    return datacollections_models


def validate_worfklow(workflow: Workflow, config: RootConfig, user: User) -> dict:
    """
    Validate the workflow.
    """
    # workflow_config = config.workflows[workflow_name]
    # print(workflow_config)

    # datacollection_models = populate_file_models(workflow)

    # Create a dictionary of validated datacollections with datacollection_id as the key
    # validated_datacollections = {
    #     datacollection.data_collection_tag: datacollection
    #     for datacollection in datacollection_models
    # }

    # # print(validated_datacollections)
    # # Update the workflow's files attribute in the main config
    # workflow.data_collections = validated_datacollections
    # workflow.runs = {}

    # Create the permissions using the decoded user
    permissions = Permission(owners=[user])
    workflow.permissions = permissions

    return workflow


def validate_all_workflows(config: RootConfig, user: User) -> RootConfig:
    """
    Validate all workflows in the config.
    """
    for workflow in config.workflows:
        validate_worfklow(workflow, config, user)

    return config


def calculate_file_hash(file_path: str) -> str:
    """Calculate a unique hash for a file based on its content."""
    # Implementation of hashing function
    with open(file_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

