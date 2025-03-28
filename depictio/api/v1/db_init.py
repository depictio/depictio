# Create a user if it does not exist

from datetime import time
import os

from bson import ObjectId
import yaml
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    generate_agent_config,
)
from depictio.api.v1.endpoints.user_endpoints.utils import (
    hash_password,
    list_existing_tokens,
)
from depictio.api.v1.configs.logging import logger

# from depictio.api.v1.endpoints.user_endpoints.models import User
from depictio.api.v1.endpoints.user_endpoints.utils import add_token
from depictio.api.v1.endpoints.utils_endpoints.core_functions import create_bucket

# from depictio_models.models.base import User
from depictio_models.models.users import User, Group
from depictio.api.v1.endpoints.user_endpoints.utils import create_group_helper


admin_user_dict = {
    "_id": ObjectId("67658ba033c8b59ad489d7c7"),
    "username": "admin",
    "password": hash_password("changeme"),
    "is_admin": True,
    "email": "admin@embl.de",
}
admin_group_dict = {"name": "admin"}
users_group_dict = {"name": "users"}



def create_admin_user(admin_user_dict: dict):
    from depictio.api.v1.db import users_collection, client

    # Ensure MongoDB is up and running
    for _ in range(5):
        try:
            client.server_info()
            logger.info("Connected to MongoDB")
            break
        except Exception as e:
            logger.warning("Waiting for MongoDB to start...")
            time.sleep(5)
    else:
        raise Exception("Could not connect to MongoDB")

    # Check if the user already exists
    existing_user = users_collection.find_one({"email": admin_user_dict["email"]})
    if existing_user:
        logger.info("Admin user already exists in the database")
    # Insert the user into the database
    else:
        logger.info("Adding admin user to the database")
        logger.info(f"User: {admin_user_dict}")
        user = User(**admin_user_dict)
        logger.info(f"User: {user}")
        user = user.mongo()
        logger.info(f"User.mongo(): {user}")
        users_collection.insert_one(user)
        logger.info("Admin user added to the database")

    # Check if default admin token exists

    if not users_collection.find_one(
        {"email": admin_user_dict["email"], "tokens.name": "default_admin_token"}
    ):
        user = users_collection.find_one({"email": admin_user_dict["email"]})
        logger.info(f"User: {user}")
        user = User.from_mongo(user)
        logger.info(f"User.from_mongo: {user}")

        logger.info("Creating default admin token")
        token_data = {
            "sub": admin_user_dict["email"],
            "name": "default_admin_token",
            "token_lifetime": "long-lived",
        }
        token = add_token(token_data)
        logger.info("Default admin token created")
        logger.info(f"Token: {token}")
        token_data["access_token"] = token.access_token
        token_data["expire_datetime"] = token.expire_datetime

        # Generate the agent config

        agent_config = generate_agent_config(user, {"token": token_data})
        agent_config = yaml.dump(agent_config, default_flow_style=False)

        # Export the agent config to a file
        logger.info(f"Creating .depictio directory in {os.getcwd()}")
        os.makedirs("/app/depictio/.depictio", exist_ok=True)
        with open("/app/depictio/.depictio/default_admin_agent.yaml", "w") as f:
            f.write(agent_config)
        logger.info(
            "Agent config exported to /app/depictio/.depictio/default_admin_agent.yaml"
        )
        return user

    else:
        logger.info("Default admin token already exists")
        return None


def initialize_db():
    from depictio.api.v1.db import initialization_collection

    # Check if the initialization has already been done
    initialization_status = initialization_collection.find_one({"initialized": True})
    if not initialization_status:
        logger.info("Running initial setup...")

        # Create the admin group
        admin_group = create_group_helper(admin_group_dict)
        users_group = create_group_helper(users_group_dict)
        admin_user_dict["groups"] = [admin_group, users_group]
        logger.info(f"Admin group: {admin_group}")
        logger.info(f"Users group: {users_group}")
        logger.info(f"Admin user: {admin_user_dict}")

        # Create the admin user
        admin_user = create_admin_user(admin_user_dict)

        if admin_user:
            # Create a bucket if it does not exist
            create_bucket(admin_user)

        # Insert the initialization status
        initialization_collection.insert_one({"initialized": True})
        logger.info("Initialization setup done.")

    else:
        logger.info("Initialization already done. Skipping...")
