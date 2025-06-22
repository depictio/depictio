import os
import sys

import pymongo

from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.configs.logging_init import logger

# Check if running in a test environment
# First check environment variable, then check for pytest in sys.argv
is_testing = os.environ.get("DEV_MODE", "false").lower() == "true" or any(
    "pytest" in arg for arg in sys.argv
)
logger.debug(f"Is testing: {is_testing}")

# Initialize MongoDB client
logger.debug(f"Using MongoDB URL: {MONGODB_URL}")
client = pymongo.MongoClient(MONGODB_URL)

# Get the database name from settings
db_name = settings.mongodb.db_name


# Function to clean the test database
def clean_test_database():
    """
    Clean the test database by dropping all collections.
    Only use this in test environments.
    """
    if not is_testing:
        logger.warning(
            "Attempted to clean test database while not in test mode. Operation aborted."
        )
        return False

    try:
        # Get all collection names
        collection_names = client[db_name].list_collection_names()

        # Drop each collection
        for collection_name in collection_names:
            client[db_name].drop_collection(collection_name)

        logger.debug(f"Cleaned test database: {db_name}")
        return True
    except Exception as e:
        logger.error(f"Error cleaning test database: {e}")
        return False


db = client[db_name]
logger.debug(f"MongoDB database selected: {db_name}")
logger.debug(f"Client: {client}")
logger.debug(f"DB: {db}")


# Define the collections

data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db[settings.mongodb.collections.users_collection]
tokens_collection = db[settings.mongodb.collections.tokens_collection]
groups_collection = db[settings.mongodb.collections.groups_collection]
deltatables_collection = db[settings.mongodb.collections.deltatables_collection]
jbrowse_collection = db[settings.mongodb.collections.jbrowse_collection]
dashboards_collection = db[settings.mongodb.collections.dashboards_collection]
initialization_collection = db[settings.mongodb.collections.initialization_collection]
projects_collection = db[settings.mongodb.collections.projects_collection]
test_collection = db[settings.mongodb.collections.test_collection]
