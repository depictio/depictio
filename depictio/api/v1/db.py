"""
MongoDB database configuration and collection definitions.

Provides synchronous MongoDB client and collection instances for the Depictio API.
"""

import os
import sys

import pymongo

from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.configs.logging_init import logger

is_testing = os.environ.get("DEPICTIO_DEV_MODE", "false").lower() == "true" or any(
    "pytest" in arg for arg in sys.argv
)

client = pymongo.MongoClient(MONGODB_URL)
db_name = settings.mongodb.db_name
db = client[db_name]


def clean_test_database() -> bool:
    """
    Clean the test database by dropping all collections.

    Only operates in test environments. Returns False if not in test mode.

    Returns:
        True if database was cleaned successfully, False otherwise.
    """
    if not is_testing:
        logger.warning(
            "Attempted to clean test database while not in test mode. Operation aborted."
        )
        return False

    try:
        for collection_name in client[db_name].list_collection_names():
            client[db_name].drop_collection(collection_name)
        return True
    except Exception as e:
        logger.error(f"Error cleaning test database: {e}")
        return False


# Collection instances
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
multiqc_collection = db[settings.mongodb.collections.multiqc_collection]
test_collection = db[settings.mongodb.collections.test_collection]
