import os
from typing import Optional
from beanie import PydanticObjectId
import yaml

from depictio.api.v1.endpoints.user_endpoints.agent_config_utils import (
    generate_agent_config,
)
from depictio.api.v1.endpoints.user_endpoints.token_utils import create_default_token
from depictio.api.v1.endpoints.user_endpoints.utils import (
    _ensure_mongodb_connection,
    create_group_helper_beanie,
    create_user_helper_beanie,
    get_users_by_group_id,
    hash_password,
)
from depictio.api.v1.configs.custom_logging import format_pydantic, logger
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.utils import add_token
from depictio.api.v1.endpoints.user_endpoints.utils import create_group_helper
from depictio_models.utils import get_config, validate_model_config

from depictio_models.models.users import User, Group, GroupBeanie, UserBeanie


def create_user(user: User) -> dict:
    """
    Create a user if it doesn't exist in the database.

    Args:
        user: User object containing user information

    Returns:
        Dictionary with the user object and a boolean indicating if it was created
    """
    from depictio.api.v1.db import users_collection, _ensure_mongodb_connection

    # Ensure MongoDB connection
    _ensure_mongodb_connection()
    logger.debug("Ensuring MongoDB connection...")

    # Check if the user already exists
    existing_user = users_collection.find_one({"email": user.email})
    if existing_user:
        logger.warning(f"User {user.email} already exists in the database")
        existing_user = User.from_mongo(existing_user)
        return {"user": existing_user, "created": False}

    # Insert the user into the database
    logger.debug(f"Adding user {user.email} to the database")
    user_mongo = user.mongo()
    logger.debug(f"User MongoDB object: {user_mongo}")
    users_collection.insert_one(user_mongo)
    logger.debug(f"User {user.email} added to the database")

    # Return the created user object
    return {"user": user, "created": True}


# async def create_default_token(user: User) -> dict:
#     """
#     Create a default token for a user if it doesn't exist.

#     Args:
#         user: User object

#     Returns:
#         Token data if created, None if token already exists
#     """

#     user = await UserBeanie.find_one(user.id)
#     if user:

#     from depictio.api.v1.db import users_collection

#     # Check if default token exists
#     if users_collection.find_one({"email": user.email, "tokens.name": "default_token"}):
#         logger.warning(f"Default token for {user.email} already exists")
#         return None

#     logger.debug(f"Creating default token for {user.email}")
#     token_data = {
#         "sub": str(user.email),
#         "name": "default_token",
#         "token_lifetime": "long-lived",
#     }
#     token = add_token(token_data)
#     logger.debug(f"Default token created for {user.email}")

#     token_data["access_token"] = token.access_token
#     token_data["expire_datetime"] = token.expire_datetime

#     # Generate and save agent config
#     agent_config = generate_agent_config(user, {"token": token_data})
#     agent_config_yaml = yaml.dump(agent_config, default_flow_style=False)

#     # Create username-based filename
#     username = user.email.split("@")[0]
#     config_filename = f"{username}_config.yaml"

#     # Export the agent config to a file
#     config_dir = settings.auth.cli_config_dir
#     logger.debug(f"Creating config directory: {config_dir}")
#     os.makedirs(config_dir, exist_ok=True)

#     config_path = f"{config_dir}/{config_filename}"
#     with open(config_path, "w") as f:
#         f.write(agent_config_yaml)
#     logger.debug(f"Agent config for {user.email} exported to {config_path}")

#     return token_data


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


    # Validate and create groups
    groups = {}
    for group_config in initial_config.get("groups", []):
        group = GroupBeanie(**group_config)
        payload = await create_group_helper_beanie(group)
        logger.debug(f"Created group: {format_pydantic(payload['group'])}")
        group = payload["group"]
        groups[group.name] = payload["group"]

    # Variable to store the admin user
    admin_user = None

    # Validate and create users
    created_users = []
    for user_config in initial_config.get("users", []):
        # Validate user config
        logger.debug(user_config)
        # Assign groups to user
        user_config["groups"] = [
            groups[group_name] for group_name in user_config.get("groups", [])
        ]
        user_config["password"] = hash_password(user_config["password"])
        logger.debug(user_config)

        user = UserBeanie(**user_config)
        logger.debug(f"User config: {format_pydantic(user)}")

        # Create user
        user_payload = await create_user_helper_beanie(user)
        logger.debug(f"Created user: {format_pydantic(user_payload['user'])}")
        
        created_user = user_payload["user"]
        created_users.append(created_user)
        
        # If this is an admin user, save it for return
        if created_user.is_admin:
            admin_user = created_user
            logger.info(f"Admin user identified: {created_user.email}")

        # Create default token if user was just created
        if user_payload["success"]:
            token = await create_default_token(created_user)
            if token:
                logger.info(f"Created token: {format_pydantic(token)}")

    # If no admin user was created through the loop, try to find one
    if admin_user is None:
        logger.debug("No admin user created during initialization, checking if one exists...")
        admin_user = await UserBeanie.find_one({"is_admin": True})
        if admin_user:
            logger.info(f"Found existing admin user: {admin_user.email}")
        else:
            logger.warning("No admin user found in the database")

    logger.info("Database initialization completed successfully.")
    return admin_user