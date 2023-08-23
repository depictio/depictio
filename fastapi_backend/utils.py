import sys
sys.path.append("/Users/tweber/Gits/depictio")

import os
import re
from typing import Dict, Type, List, Tuple, Optional, Any
from pydantic import BaseModel, ValidationError
import yaml
from fastapi_backend.configs.models import DataCollection, Workflow, DataCollectionConfig, WorkflowConfig, RootConfig


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


def validate_config(config: Dict, pydantic_model: Type[BaseModel]) -> BaseModel:
    """
    Load and validate the YAML configuration
    """
    if not isinstance(config, dict):
        raise ValueError("Invalid config. Must be a dictionary.")
    try:
        data = pydantic_model(**config)
    except ValidationError as e:
        raise ValueError(f"Invalid config: {e}")
    return data


def populate_file_models(workflow: Workflow) -> List[DataCollection]:
    """
    Returns a list of DataCollection models for a given workflow.
    """

    datacollections_models = []
    # print(workflow)
    for datacollection_id, metadata in workflow.data_collections.items():
        datacollection_instance = DataCollection(
            datacollection_id=datacollection_id,
            description=metadata.description,
            config=metadata.config,
        )
        datacollections_models.append(datacollection_instance)

    return datacollections_models


def validate_worfklow(workflow: Workflow, config: RootConfig) -> dict:
    """
    Validate the workflow.
    """
    # workflow_config = config.workflows[workflow_name]
    # print(workflow_config)
    datacollection_models = populate_file_models(workflow)
    
    # Create a dictionary of validated datacollections with datacollection_id as the key
    validated_datacollections = {datacollection.data_collection_id: datacollection for datacollection in datacollection_models}
    
    # Update the workflow's files attribute in the main config
    workflow.data_collections = validated_datacollections
    
    return workflow

def validate_all_workflows(config: RootConfig) -> RootConfig:
    """
    Validate all workflows in the config.
    """
    for workflow in config.workflows:
        validate_worfklow(workflow, config)
    
    return config