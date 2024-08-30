# Create a user if it does not exist

from datetime import time
import os

import yaml
from depictio.api.v1.endpoints.user_endpoints.utils import generate_agent_config, hash_password, list_existing_tokens
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.models import User
from depictio.api.v1.endpoints.user_endpoints.utils import add_token


user_dict = {"username": "admin", "password": hash_password("changeme"), "is_admin": True, "email": "admin@embl.de"}


def create_admin_user(user_dict=user_dict):
    from depictio.api.v1.db import users_collection, client

    # Ensure MongoDB is up and running
    for _ in range(5):
        try:
            client.server_info()
            print("Connected to MongoDB")
            break
        except Exception as e:
            print("Waiting for MongoDB to start...")
            time.sleep(5)
    else:
        raise Exception("Could not connect to MongoDB")

    # Check if the user already exists
    existing_user = users_collection.find_one({"email": user_dict["email"]})
    if existing_user:
        logger.info("Admin user already exists in the database")
    # Insert the user into the database
    else:
        logger.info("Adding admin user to the database")
        logger.info(f"User: {user_dict}")
        user = User(**user_dict)
        logger.info(f"User: {user}")
        user = user.mongo()
        logger.info(f"User.mongo(): {user}")
        users_collection.insert_one(user)
        logger.info("Admin user added to the database")

    # Check if default admin token exists

    if not users_collection.find_one({"email": user_dict["email"], "tokens.name": "default_admin_token"}):
        logger.info("Creating default admin token")
        token_data = {"sub": user_dict["email"], "name": "default_admin_token", "token_lifetime": "long-lived"}
        token = add_token()
        logger.info("Default admin token created")

        # Generate the agent config

        agent_config = generate_agent_config(user.email, token_data, current_token=token.access_token)
        agent_config = yaml.dump(agent_config, default_flow_style=False)

        # Export the agent config to a file
        os.makedirs("./.depictio", exist_ok=True)
        with open("./.depictio/default_admin_agent.yaml", "w") as f:
            f.write(agent_config)
        logger.info("Agent config exported to ~/.depictio/default_admin_agent.yaml")

    else:
        logger.info("Default admin token already exists")


def initialize_db():
    from depictio.api.v1.db import initialization_collection

    # Check if the initialization has already been done
    initialization_status = initialization_collection.find_one({"initialized": True})
    if not initialization_status:
        logger.info("Running initial setup...")

        # Create the admin user
        create_admin_user(user_dict)

        # Insert the initialization status
        initialization_collection.insert_one({"initialized": True})
        logger.info("Initialization setup done.")

    else:
        logger.info("Initialization already done. Skipping...")
