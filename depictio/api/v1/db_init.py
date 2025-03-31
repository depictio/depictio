from datetime import time
import os

from bson import ObjectId
import yaml
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    generate_agent_config,
)
from depictio.api.v1.endpoints.user_endpoints.utils import hash_password
from depictio.api.v1.configs.logging import logger

from depictio.api.v1.endpoints.user_endpoints.utils import add_token
# from depictio.api.v1.endpoints.utils_endpoints.core_functions import create_bucket

from depictio_models.models.users import User
from depictio.api.v1.endpoints.user_endpoints.utils import create_group_helper


# Define configuration dictionaries
admin_user_dict = {
    "_id": ObjectId("67658ba033c8b59ad489d7c7"),
    "password": hash_password("changeme"),
    "is_admin": True,
    "email": "admin@embl.de",
}

test_user_dict = {
    "_id": ObjectId("67658ba033c8b59ad489d7c8"),
    "password": hash_password("test_pwd"),
    "is_admin": False,
    "email": "test_user@embl.de",
}

admin_group_dict = {"name": "admin"}
users_group_dict = {"name": "users"}


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
        "sub": user.email,
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
    config_dir = "/app/depictio/.depictio"
    logger.info(f"Creating config directory: {config_dir}")
    os.makedirs(config_dir, exist_ok=True)

    config_path = f"{config_dir}/{config_filename}"
    with open(config_path, "w") as f:
        f.write(agent_config_yaml)
    logger.info(f"Agent config for {user.email} exported to {config_path}")

    return token_data


def initialize_db():
    """
    Initialize the database with default users and groups.
    """
    from depictio.api.v1.db import initialization_collection

    # Check if the initialization has already been done
    initialization_status = initialization_collection.find_one({"initialized": True})
    if initialization_status:
        logger.info("Database already initialized. Skipping...")

    logger.info("Running initial database setup...")

    # Create the groups
    admin_group = create_group_helper(admin_group_dict)
    users_group = create_group_helper(users_group_dict)
    logger.info(f"Created admin group: {admin_group}")
    logger.info(f"Created users group: {users_group}")

    # Assign groups to users
    admin_user_dict["groups"] = [admin_group, users_group]
    test_user_dict["groups"] = [users_group]

    # Create the users
    admin_user_payload = create_user(admin_user_dict)
    logger.info(f"Created admin user: {admin_user_payload['user']}")
    test_user_payload = create_user(test_user_dict)

    # Create tokens
    if admin_user_payload["created"]:
        admin_token = create_default_token(admin_user_payload["user"])
        # Create a bucket if admin user was just created
        # create_bucket(admin_user)

    if test_user_payload["created"]:
        test_token = create_default_token(test_user_payload["user"])

    # Mark initialization as complete
    initialization_collection.insert_one({"initialized": True})
    logger.info("Database initialization completed successfully.")
    return admin_user_payload["user"], test_user_payload["user"]
