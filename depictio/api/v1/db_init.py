from datetime import time
import os

from bson import ObjectId
import yaml
from depictio.api.v1.endpoints.user_endpoints.agent_config_utils import (
    generate_agent_config,
)
from depictio.api.v1.endpoints.user_endpoints.utils import hash_password
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.configs.config import settings

from depictio.api.v1.endpoints.user_endpoints.utils import add_token

from depictio_models.models.users import User, Group
from depictio.api.v1.endpoints.user_endpoints.utils import create_group_helper

from depictio_models.utils import get_config, validate_model_config


# def prepare_user_dict(user_config):
#     """Prepare user dictionary with hashed password and ObjectId"""
#     user_dict = user_config.copy()
#     # user_dict['_id'] = ObjectId(user_dict.pop('id'))
#     # user_dict['password'] = hash_password(user_dict['password'])
#     return user_dict


def create_user(user_dict: dict) -> dict:
    """
    Create a user if it doesn't exist in the database.

    Args:
        user_dict: Dictionary containing user information

    Returns:
        User object if created, None if user already exists
    """
    from depictio.api.v1.db import users_collection, client

    # Ensure MongoDB is up and running
    for _ in range(5):
        try:
            client.server_info()
            logger.info("Connected to MongoDB")
            break
        except Exception as e:
            logger.warning(f"Waiting for MongoDB to start... {str(e)}")
            time.sleep(5)
    else:
        raise Exception("Could not connect to MongoDB")

    # Check if the user already exists
    existing_user = users_collection.find_one({"email": user_dict["email"]})
    if existing_user:
        logger.info(f"User {user_dict['email']} already exists in the database")
        existing_user = User.from_mongo(existing_user)
        return {"user": existing_user, "created": False}

    # Insert the user into the database
    logger.info(f"Adding user {user_dict['email']} to the database")
    user = User(**user_dict)
    user_mongo = user.mongo()
    logger.info(f"User MongoDB object: {user_mongo}")
    users_collection.insert_one(user_mongo)
    logger.info(f"User {user_dict['email']} added to the database")

    # Return the created user object
    return {"user": user, "created": True}


def create_default_token(user):
    """
    Create a default token for a user if it doesn't exist.

    Args:
        user: User object

    Returns:
        Token data if created, None if token already exists
    """
    from depictio.api.v1.db import users_collection

    # Check if default token exists
    if users_collection.find_one({"email": user.email, "tokens.name": "default_token"}):
        logger.info(f"Default token for {user.email} already exists")
        return None

    logger.info(f"Creating default token for {user.email}")
    token_data = {
        "sub": str(user.email),
        "name": "default_token",
        "token_lifetime": "long-lived",
    }
    token = add_token(token_data)
    logger.info(f"Default token created for {user.email}")

    token_data["access_token"] = token.access_token
    token_data["expire_datetime"] = token.expire_datetime

    # Generate and save agent config
    agent_config = generate_agent_config(user, {"token": token_data})
    agent_config_yaml = yaml.dump(agent_config, default_flow_style=False)

    # Create username-based filename
    username = user.email.split("@")[0]
    config_filename = f"{username}_config.yaml"

    # Export the agent config to a file
    config_dir = settings.auth.cli_config_dir
    logger.info(f"Creating config directory: {config_dir}")
    os.makedirs(config_dir, exist_ok=True)

    config_path = f"{config_dir}/{config_filename}"
    with open(config_path, "w") as f:
        f.write(agent_config_yaml)
    logger.info(f"Agent config for {user.email} exported to {config_path}")

    return token_data


def initialize_db(wipe: bool = False) -> tuple:
    """
    Initialize the database with default users and groups.
    """
    logger.info(f"Bootstrap: {wipe} and type: {type(wipe)}")

    if wipe:
        logger.info("Wipe is enabled. Deleting the database...")
        from depictio.api.v1.db import client

        client.drop_database(settings.mongodb.db_name)
        logger.info("Database deleted successfully.")

    # Load and validate configuration
    config_path = os.path.join(
        os.path.dirname(__file__), "configs", "initial_users.yaml"
    )
    initial_config = get_config(config_path)

    logger.info("Running initial database setup...")

    # Validate and create groups
    groups = {}
    for group_config in initial_config.get("groups", []):
        group = validate_model_config(group_config, Group)
        payload = create_group_helper(group)
        groups[group.name] = payload["group"]
        logger.info(f"Created group: {group}")

    # Validate and create users
    created_users = []
    for user_config in initial_config.get("users", []):
        # Prepare user dictionary
        # user_dict = prepare_user_dict(user_config)

        # Validate user config
        logger.info(f"Validating user config: {user_config}")
        # Assign groups to user
        user_config["groups"] = [
            groups[group_name] for group_name in user_config.get("groups", [])
        ]
        user_config["password"] = hash_password(user_config["password"])
        logger.info(f"User config with groups: {user_config}")
        user_model = User.from_mongo(user_config)

        logger.info(f"User config: {user_model}")

        # Create user
        user_payload = create_user(user_config)
        logger.info(f"Created user: {user_payload['user']}")

        # Create default token if user was just created
        if user_payload["created"]:
            create_default_token(user_payload["user"])

        created_users.append(user_payload["user"])

    logger.info("Database initialization completed successfully.")
    return tuple(created_users)
