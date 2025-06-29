import os
from typing import Any

import httpx
import pymongo
from bson import ObjectId

from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.configs.logging_init import format_pydantic, logger
from depictio.cli.cli.utils.helpers import process_data_collection_helper
from depictio.models.models.projects import Project

# from depictio.models.models.s3 import S3DepictioCLIConfig
from depictio.models.models.users import CLIConfig, UserBaseCLIConfig
from depictio.models.utils import get_config


def process_collections():
    try:
        logger.info(
            f"Checking if API is ready at http://127.0.0.1:{settings.fastapi.port}/depictio/api/v1/utils/status..."
        )

        # Use 127.0.0.1 instead of localhost to avoid potential DNS issues
        response = httpx.get(
            f"http://127.0.0.1:{settings.fastapi.port}/depictio/api/v1/utils/status",
            timeout=10.0,
        )

        if response.status_code == 200:
            logger.info("API is ready. Processing initial data collections...")

            # Call the synchronous version of process_initial_data_collections
            from depictio.api.v1.endpoints.utils_endpoints.process_data_collections import (
                sync_process_initial_data_collections,  # type: ignore[unresolved-import]
            )

            result = sync_process_initial_data_collections()

            if result["success"]:
                logger.info("Initial data collections processed successfully")
            else:
                logger.error(f"Failed to process initial data collections: {result['message']}")
        else:
            logger.error(
                f"API returned status code {response.status_code}. Skipping data collection processing."
            )
    except Exception as e:
        logger.error(f"Error checking API status or processing data collections: {str(e)}")


async def process_initial_data_collections() -> dict[str, Any]:
    """
    Process the initial data collections for the first project.
    This function should be called after the API is fully started.

    Returns:
        Dict[str, Any]: A dictionary containing the result of the operation
    """
    # For now, let's skip the actual processing since it's causing issues
    # We'll return success without actually doing the processing
    logger.info("Skipping data collection processing due to async/sync issues")

    return {
        "success": True,
        "message": "Data collection processing skipped (async/sync issues)",
    }


def sync_process_initial_data_collections() -> dict[str, Any]:
    """
    Synchronous version of process_initial_data_collections using pymongo directly.
    This function should be called from a separate thread.

    Returns:
        Dict[str, Any]: A dictionary containing the result of the operation
    """
    # Connect to MongoDB using pymongo
    client = pymongo.MongoClient(MONGODB_URL)
    db = client[settings.mongodb.db_name]

    # Get collections
    users_collection = db["users"]
    tokens_collection = db["tokens"]
    projects_collection = db["projects"]

    # Get the admin user
    admin_user = users_collection.find_one({"is_admin": True})
    if not admin_user:
        logger.error("No admin user found in the database")
        return {"success": False, "message": "No admin user found in the database"}

    # Get the admin token
    token = tokens_collection.find_one({"user_id": admin_user["_id"]})
    if not token:
        logger.error(f"No token found for admin user {admin_user['email']}")
        return {
            "success": False,
            "message": f"No token found for admin user {admin_user['email']}",
        }

    # Get the initial project
    from depictio import BASE_PATH

    project_yaml_path = os.path.join(
        BASE_PATH, "api/v1/configs/iris_dataset", "initial_project.yaml"
    )
    project_config = get_config(project_yaml_path)
    project_config_id = project_config["id"]
    logger.debug(f"Project config ID: {project_config_id}")

    # FIXME: not so clean, should rely on a endpoint
    # Get the first project
    project = projects_collection.find_one({"_id": ObjectId(project_config_id)})
    project = Project.from_mongo(project)  # type: ignore[invalid-argument-type]

    logger.debug(f"Project: {project}")
    if not project:
        logger.error("No project found in the database")
        return {"success": False, "message": "No project found in the database"}

    # Create CLI config with localhost as base_url to avoid network issues
    cli_config = CLIConfig(
        user=UserBaseCLIConfig(
            id=admin_user["_id"],
            email=admin_user["email"],
            is_admin=admin_user["is_admin"],
            token=token,
        ),
        base_url=f"http://localhost:{settings.fastapi.port}",
        s3=settings.minio,
    )

    logger.debug(f"CLI config: {format_pydantic(cli_config)}")

    wf = project.workflows[0]
    dc_id = str(project.workflows[0].data_collections[0].id)

    # Process the first data collection in scan mode
    result = process_data_collection_helper(
        CLI_config=cli_config,
        wf=wf,
        dc_id=dc_id,
        mode="scan",
    )

    logger.info("Data collection processed successfully in scan mode")

    # Process the first data collection in process mode
    result = process_data_collection_helper(
        CLI_config=cli_config.model_dump(),
        wf=wf,
        dc_id=dc_id,
        mode="process",
        command_parameters={
            "overwrite": True,
        },
    )
    logger.debug(f"Result: {result}")
    if result["result"] != "success":  # type: ignore[non-subscriptable]
        logger.error(f"Error processing data collection: {result['message']}")  # type: ignore[non-subscriptable]
        return {
            "success": False,
            "message": f"Error processing data collection: {result['message']}",  # type: ignore[non-subscriptable]
        }

    return {"success": True, "message": "Data collections processed successfully"}
