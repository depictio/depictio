import hashlib
import json
import os
from typing import Any, Dict, cast
from pydantic import validate_call
import typer

# depictio-cli imports
from depictio.cli.cli.utils.api_calls import api_get_project_from_name, api_login
from depictio.cli.logging import logger

# depictio-models imports
from depictio.models.utils import get_config
from depictio.models.models.users import CLIConfig
from depictio.models.utils import validate_model_config
from depictio.models.models.projects import Project
from depictio.models.models.base import convert_objectid_to_str


KEYS_TO_SAVE = {
    "id": None,
    "name": None,
    "hash": None,
    "yaml_config_path": None,
    "permissions": {
        "owners": [{"id": None}],
        "editors": [{"id": None}],
        "viewers": [{"id": None}],
    },
    "workflows": [
        {
            "id": None,
            "name": None,
            "workflow_tag": None,
            "data_collections": [{"id": None, "data_collection_tag": None}],
        }
    ],
}


@validate_call
def validate_project_config_and_check_S3_storage(
    CLI_config_path: str, project_config_path: str
):
    """
    Validate the project configuration and check S3 storage.
    """
    logger.info(f"Creating workflow from {CLI_config_path}...")
    logger.info(f"Validating pipeline configuration from {project_config_path}...")

    response = api_login(CLI_config_path)
    logger.info(response)

    if response["success"]:
        CLI_config = response["CLI_config"]
        # Check S3 accessibility
        # S3_storage_checks(CLI_config.s3)

        CLI_config = CLIConfig(**CLI_config)
        # Validate the project configuration
        response_validation = local_validate_project_config(
            CLI_config, project_config_path
        )
        return CLI_config, response_validation
    else:
        raise typer.Exit(code=1)


def find_by_name(collection, name):
    """
    Search a list of dicts for an item with a matching 'name'.
    Returns the dict if found, otherwise None.
    """
    for item in collection:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def find_matching_entry(collection, new_item):
    """
    Search a list of dicts for an item that matches new_item based on certain keys.
    Keys checked (in order): 'name', 'workflow_tag', 'data_collection_tag'.
    Returns the dict if a match is found, otherwise None.
    """
    for item in collection:
        if not isinstance(item, dict):
            continue
        # Check for match on 'name'
        logger.debug(f"Item: {item}")
        if "name" in new_item and new_item["name"] == item.get("name"):
            return item
        # Check for match on 'workflow_tag'
        if "workflow_tag" in new_item and new_item["workflow_tag"] == item.get(
            "workflow_tag"
        ):
            return item
        # Check for match on 'data_collection_tag'
        if "data_collection_tag" in new_item and new_item[
            "data_collection_tag"
        ] == item.get("data_collection_tag"):
            return item
    return None


def assign_ids_by_keys(existing_meta, new_structure):
    """
    Recursively traverses new_structure. For each dict with identifying keys,
    attempts to find a matching dict in existing_meta to copy its 'id'.
    """
    logger.debug(f"Assigning IDs by keys for {new_structure}")
    logger.debug(f"Existing metadata: {existing_meta}")
    if isinstance(new_structure, dict):
        match = find_matching_entry(existing_meta, new_structure)
        if match and "id" in match:
            logger.debug(
                f"Match found for {new_structure}: {match} ; ID: {match['id']}"
            )
            new_structure["id"] = str(match["id"])

        # Recurse into nested dictionaries or lists
        for key, value in new_structure.items():
            if isinstance(value, (dict, list)):
                # Determine context for nested lists like workflows or data_collections
                if key in ["workflows", "data_collections"] and match:
                    nested_context = match.get(key, [])
                    new_structure[key] = assign_ids_by_keys(nested_context, value)
                else:
                    new_structure[key] = assign_ids_by_keys(existing_meta, value)

    elif isinstance(new_structure, list):
        for idx, item in enumerate(new_structure):
            new_structure[idx] = assign_ids_by_keys(existing_meta, item)

    return new_structure


@validate_call
def load_and_prepare_config(
    CLI_config: CLIConfig, project_yaml_config_path: str
) -> Dict[str, Any]:
    """
    Load the pipeline configuration, set the YAML config path, and add permissions.
    """
    # Load the pipeline configuration
    project_config = get_config(project_yaml_config_path)
    full_path = os.path.abspath(project_yaml_config_path)
    project_config["yaml_config_path"] = full_path

    # Add permissions based on the CLI user, removing 'token'
    # user_light = CLI_config["user"].copy()
    # user_light.pop("token", None)
    user_light = CLI_config.user.model_copy()
    user_light.token = None
    user_light = user_light.model_dump()

    project_config["permissions"] = {
        "owners": [user_light],
        "editors": [],
        "viewers": [],
    }
    # project_config["permissions"] = {"owners": [user_light], "editors": [], "viewers": []}

    logger.debug(f"Pipeline config after adding permissions: {project_config}")
    return cast(Dict[str, Any], project_config)


@validate_call
def merge_existing_ids(existing_entry: dict, project_config: dict) -> dict:
    """
    If a project with the same name exists, checks ownership and merges existing IDs.
    """

    logger.info(f"Merge existing IDs for project: {project_config['name']}")
    # Assuming local_metadata is a list of project dicts
    project_name = project_config["name"]
    # existing_entry = next((entry for entry in local_metadata if entry["name"] == project_name), None)

    # Check if the project exists and is owned by the same user
    if existing_entry:
        logger.info(f"Project : {project_config}")
        user_id = project_config["permissions"]["owners"][0]["id"]
        logger.info(
            f"Existing entry user ID: {existing_entry['permissions']['owners'][0]['id']}"
        )
        if existing_entry["permissions"]["owners"][0]["id"] != user_id:
            raise ValueError(
                f"Project '{project_name}' exists but is owned by a different user."
            )

        logger.info(
            f"Project owner is the same for '{project_name}' - Owner ID: {user_id}"
        )
        logger.info(f"Project '{project_name}' exists with ID: {existing_entry['id']}")
        # Merge existing IDs using the provided function
        project_config = assign_ids_by_keys([existing_entry], project_config)
        logger.debug(f"Project config after merging IDs: {project_config}")

    return project_config


# Define nested keys to save
def extract_metadata(data, keys_structure):
    """
    Recursively extract metadata based on a keys structure.
    """
    if isinstance(keys_structure, dict):
        return {
            key: extract_metadata(data.get(key, {}), sub_keys)
            for key, sub_keys in keys_structure.items()
        }
    elif isinstance(keys_structure, list):
        return (
            [extract_metadata(item, keys_structure[0]) for item in data]
            if isinstance(data, list)
            else []
        )
    else:
        return data


@validate_call
def create_metadata_entry(
    validated_config: Project, keys_to_save: dict
) -> Dict[str, Any]:
    """
    Convert validated configuration to a metadata entry, compute hash, and return the entry.
    """
    # Convert ObjectId to str if necessary and extract metadata
    config_dict = convert_objectid_to_str(validated_config.model_dump())
    metadata_entry = extract_metadata(config_dict, keys_to_save)

    # Compute hash for the metadata entry
    hash_value = hashlib.md5(
        json.dumps(metadata_entry, sort_keys=True).encode()
    ).hexdigest()
    metadata_entry["hash"] = hash_value
    logger.debug(f"Metadata entry: {metadata_entry}")
    return cast(Dict[str, Any], metadata_entry)


@validate_call
def local_validate_project_config(
    CLI_config: CLIConfig, project_yaml_config_path: str
) -> dict:
    """
    Validate the pipeline configuration locally and update the metadata.
    """
    try:
        logger.info("Validating pipeline configuration...")
        # Load and prepare the pipeline configuration
        project_config = load_and_prepare_config(CLI_config, project_yaml_config_path)
        logger.debug(f"CLI config: {CLI_config}")
        logger.debug(f"Project config: {project_config}")

        # Validate configuration against the Project model
        validated_config = validate_model_config(project_config, Project)

        # Load existing metadata and merge IDs if necessary
        # local_metadata = load_metadata()
        response = api_get_project_from_name(project_config["name"], CLI_config)
        if response.status_code == 200:
            remote_project = response.json()
            logger.info(f"Remote project : {remote_project}")

            validated_config = merge_existing_ids(
                remote_project, convert_objectid_to_str(validated_config.to_json())
            )
            validated_config = Project.from_mongo(validated_config)

        # else:
        #     validated_config = Project.from_mongo(validated_config)

        logger.info(f"Pipeline configuration validated: {validated_config}")

        # Create metadata entry and update metadata
        # metadata_entry = create_metadata_entry(validated_config, KEYS_TO_SAVE)
        # update_metadata(metadata_entry)
        # logger.info(f"Metadata updated with new entry: {metadata_entry}")

        # # add computed hash to the validated config
        # # validated_config.hash = metadata_entry["hash"]
        # logger.info(f"Pipeline configuration with hash: {validated_config}")

        # tmp_validated_config = validated_config.mongo()
        # logger.info(f"mongo -Pipeline configuration with hash: {tmp_validated_config}")

        # tmp_validated_config = Project.from_mongo(tmp_validated_config)
        # logger.info(f"from_mongo - Pipeline configuration with hash: {tmp_validated_config}")

        return {
            "success": True,
            "config": validated_config,
            "project_config": validated_config,
        }

    except ValueError as e:
        logger.error(f"Pipeline configuration validation failed: {e}")
        return {"success": False}
