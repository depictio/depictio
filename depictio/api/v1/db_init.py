import os
from typing import Optional
from fastapi import HTTPException

from depictio.api.v1.endpoints.projects_endpoints.utils import (
    helper_create_project_beanie,
)
from depictio.api.v1.endpoints.user_endpoints.token_utils import create_default_token
from depictio.api.v1.endpoints.user_endpoints.utils import (
    _ensure_mongodb_connection,
    create_group_helper_beanie,
    create_user_in_db,
)
from depictio.api.v1.configs.custom_logging import format_pydantic, logger
from depictio.api.v1.configs.config import settings
from depictio_models.utils import get_config

from depictio_models.models.users import GroupBeanie, UserBeanie, UserBase
from depictio_models.models.projects import ProjectBeanie


async def create_initial_project(admin_user: UserBeanie) -> None:
    # from depictio_models.models.projects import Project,

    project_yaml_path = os.path.join(
        os.path.dirname(__file__), "configs", "initial_project.yaml"
    )
    project_config = get_config(project_yaml_path)
    project_config["yaml_config_path"] = project_yaml_path

    project_config["permissions"] = {
        "owners": [
            UserBase(
                id=admin_user.id,
                email=admin_user.email,
                is_admin=True,
            )
        ],
        "editors": [],
        "viewers": [],
    }

    logger.debug(f"Project config: {project_config}")
    project = ProjectBeanie(**project_config)
    logger.debug(f"Project object: {format_pydantic(project)}")

    try:
        payload = await helper_create_project_beanie(project)
        logger.debug(f"Project creation payload: {payload}")
        if payload["success"]:
            logger.info(
                f"Project created successfully: {format_pydantic(payload['project'])}"
            )
            return {
                "success": True,
                "project": payload["project"],
                "message": "Project created successfully",
            }
    except HTTPException as e:
        logger.error(f"Error creating project: {e}")
        return {
            "success": False,
            "message": f"Error creating project: {e}",
        }


async def initialize_db(wipe: bool = False) -> Optional[UserBeanie]:
    """
    Initialize the database with default users and groups.
    """
    logger.info(f"Bootstrap: {wipe} and type: {type(wipe)}")

    _ensure_mongodb_connection()

    if wipe:
        logger.info("Wipe is enabled. Deleting the database...")
        from depictio.api.v1.db import client

        client.drop_database(settings.mongodb.db_name)
        logger.info("Database deleted successfully.")

    # Load and validate configuration for initial users and groups
    config_path = os.path.join(
        os.path.dirname(__file__), "configs", "initial_users.yaml"
    )
    initial_config = get_config(config_path)

    logger.info("Running initial database setup...")

    # Create groups
    for group_config in initial_config.get("groups", []):
        group = GroupBeanie(**group_config)
        payload = await create_group_helper_beanie(group)
        logger.debug(f"Created group: {format_pydantic(payload['group'])}")

    admin_user = None

    # Create users
    for user_config in initial_config.get("users", []):
        # Validate user config
        logger.debug(user_config)

        user_payload = await create_user_in_db(
            email=user_config["email"],
            password=user_config["password"],
            is_admin=user_config.get("is_admin", False),
        )
        logger.debug(f"User payload: {user_payload}")

        # # Create default token if user was just created
        if user_payload["success"]:
            token = await create_default_token(user_payload["user"])
            if token:
                logger.info(f"Created token: {format_pydantic(token)}")

        if user_payload["user"].is_admin:
            admin_user = user_payload["user"]
            logger.info(f"Admin user created: {admin_user.email}")

    # If no admin user was created through the loop, try to find one
    if admin_user is None:
        logger.debug(
            "No admin user created during initialization, checking if one exists..."
        )
        admin_user = await UserBeanie.find_one({"is_admin": True})
        if admin_user:
            logger.info(f"Found existing admin user: {admin_user.email}")
        else:
            logger.warning("No admin user found in the database")

    project_payload = await create_initial_project(admin_user=admin_user)
    logger.debug(f"Project payload: {project_payload}")

    logger.info("Database initialization completed successfully.")

    return admin_user
