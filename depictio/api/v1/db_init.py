import json
import os

from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import format_pydantic, logger
from depictio.api.v1.endpoints.dashboards_endpoints.routes import save_dashboard
from depictio.api.v1.endpoints.projects_endpoints.utils import _helper_create_project_beanie
from depictio.api.v1.endpoints.user_endpoints.core_functions import _create_user_in_db
from depictio.api.v1.endpoints.user_endpoints.token_utils import create_default_token
from depictio.api.v1.endpoints.user_endpoints.utils import (
    _ensure_mongodb_connection,
    create_group_helper_beanie,
)
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.projects import ProjectBeanie
from depictio.models.models.users import GroupBeanie, Permission, TokenBeanie, UserBase, UserBeanie
from depictio.models.utils import get_config


async def create_initial_project(admin_user: UserBeanie, token_payload: dict | None) -> dict | None:
    # from depictio.models.models.projects import Project,

    project_yaml_path = os.path.join(
        os.path.dirname(__file__), "configs", "iris_dataset", "initial_project.yaml"
    )
    project_config = get_config(project_yaml_path)
    project_config["yaml_config_path"] = project_yaml_path

    project_config["permissions"] = {
        "owners": [
            UserBase(
                id=admin_user.id,  # type: ignore[invalid-argument-type]  # type: ignore[invalid-argument-type]
                email=admin_user.email,
                is_admin=True,
            )
        ],
        "editors": [],
        "viewers": [],
    }

    logger.debug(f"Project config: {project_config}")
    project = ProjectBeanie(**project_config)  # type: ignore[missing-argument]
    logger.debug(f"Project object: {format_pydantic(project)}")
    token = TokenBeanie(**token_payload["token"])  # type: ignore[missing-argument]
    logger.debug(f"Token: {format_pydantic(token)}")

    try:
        payload = await _helper_create_project_beanie(project)

        logger.debug(f"Project creation payload: {payload}")
        if payload["success"]:
            project_name = (
                payload["project"].name if hasattr(payload["project"], "name") else "unknown"
            )
            logger.info(f"Project created successfully: {project_name}")
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


async def create_initial_dashboard(admin_user: UserBeanie) -> dict | None:
    """
    Create an initial dashboard for the admin user.
    This function is a placeholder and should be implemented based on your application's requirements.
    """
    # Check if dashboard was already created
    from depictio.api.v1.db import dashboards_collection

    dashboard_json_path = os.path.join(
        os.path.dirname(__file__), "configs", "iris_dataset", "initial_dashboard.json"
    )
    # Load the dashboard configuration from the JSON file
    from bson import json_util

    dashboard_data = json.load(open(dashboard_json_path, "r"), object_hook=json_util.object_hook)
    logger.debug(f"Dashboard data: {dashboard_data}")
    _check = dashboards_collection.find_one({"_id": ObjectId(dashboard_data["_id"])})
    if _check:
        logger.info(f"Dashboard already exists: {_check}")
        return {
            "success": True,
            "message": "Dashboard already exists",
        }

    # Convert dashboard data to the correct format
    dashboard_data = DashboardData.from_mongo(dashboard_data)
    dashboard_data.permissions = Permission(
        owners=[
            UserBase(
                id=admin_user.id,  # type: ignore[invalid-argument-type]
                email=admin_user.email,
                is_admin=True,
            )
        ],
        editors=[],
        viewers=[],
    )

    # Create the dashboard object into the database
    response = await save_dashboard(
        dashboard_id=dashboard_data.id,
        data=dashboard_data,
        current_user=admin_user,
    )
    logger.debug(f"Dashboard response: {response}")
    return response


async def initialize_db(wipe: bool = False) -> UserBeanie | None:
    """
    Initialize the database with default users and groups. If wipe is True, the database will be wiped before initialization.
    """
    logger.debug(f"Bootstrap: {wipe} and type: {type(wipe)}")

    _ensure_mongodb_connection()

    if wipe:
        logger.info("Wipe is enabled. Deleting the database...")
        from depictio.api.v1.db import client

        client.drop_database(settings.mongodb.db_name)
        logger.info("Database deleted successfully.")

    # Load and validate configuration for initial users and groups
    config_path = os.path.join(os.path.dirname(__file__), "configs", "initial_users.yaml")
    initial_config = get_config(config_path)

    logger.info("Running initial database setup...")

    # Create groups
    for group_config in initial_config.get("groups", []):
        group = GroupBeanie(**group_config)  # type: ignore[missing-argument]
        payload = await create_group_helper_beanie(group)
        logger.debug(f"Created group: {format_pydantic(payload['group'])}")

    admin_user = None
    token_payload = None

    # Create users
    for user_config in initial_config.get("users", []):
        # Validate user config
        logger.debug(user_config)

        user_payload = await _create_user_in_db(
            id=user_config["id"],
            email=user_config["email"],
            password=user_config["password"],
            is_admin=user_config.get("is_admin", False),
        )
        logger.debug(f"User payload: {user_payload}")

        # # Create default token if user was just created
        if user_payload["success"]:
            token_payload = await create_default_token(user_payload["user"])
            if token_payload:
                logger.info("Created default token")

            if user_payload["user"].is_admin:
                admin_user = user_payload["user"]
                logger.info(f"Admin user created: {admin_user.email}")
                logger.debug(f"Admin token created: {format_pydantic(token_payload)}")
        else:
            token_beanie = await TokenBeanie.find_one(
                {"user_id": user_payload["user"].id, "name": "default_token"}
            )
            logger.debug(f"Token beanie: {format_pydantic(token_beanie)}")
            if token_beanie:
                token_payload = {
                    "token": token_beanie.model_dump(),
                    "config_path": None,
                    "new_token_created": False,
                }
                logger.debug(f"Token payload: {format_pydantic(token_payload)}")  # type: ignore[invalid-argument-type]
                logger.info(f"Default token already exists for {user_payload['user'].email}")
            else:
                logger.warning(f"Failed to create default token for {user_payload['user'].email}")

    # If no admin user was created through the loop, try to find one
    if admin_user is None:
        logger.debug("No admin user created during initialization, checking if one exists...")
        admin_user = await UserBeanie.find_one({"is_admin": True})
        if admin_user:
            logger.info(f"Found existing admin user: {admin_user.email}")
            token_beanie = await TokenBeanie.find_one(
                {"user_id": admin_user.id, "name": "default_token"}
            )

            logger.debug(f"Token payload: {format_pydantic(token_beanie)}")

            token_payload = {
                "token": token_beanie.model_dump(),
                "config_path": None,
                "new_token_created": False,
            }
        else:
            logger.warning("No admin user found in the database")

    if admin_user is None or token_payload is None:
        logger.error("Cannot proceed with project creation: admin_user or token_payload is None")
        raise RuntimeError("Admin user and token are required for initialization")

    project_payload = await create_initial_project(
        admin_user=admin_user, token_payload=token_payload
    )
    logger.debug(f"Project payload: {project_payload}")

    # Create initial dashboard
    dashboard_payload = await create_initial_dashboard(admin_user=admin_user)
    logger.debug(f"Dashboard payload: {dashboard_payload}")

    logger.info("Database initialization completed successfully.")

    return admin_user
