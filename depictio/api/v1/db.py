from pydantic import BaseModel
import pymongo
import os
import sys
import socket
from depictio.api.v1.configs.config import settings, MONGODB_URL
# from depictio.api.v1.db_init import initialize_db
from depictio.api.v1.configs.custom_logging import logger
# from depictio.api.v1.endpoints.user_endpoints.utils import _ensure_mongodb_connection

# Check if running in a test environment
# First check environment variable, then check for pytest in sys.argv
is_testing = os.environ.get('DEPICTIO_TEST_MODE', 'false').lower() == 'true' or any('pytest' in arg for arg in sys.argv)

# Check if running in Docker or locally
# If we can't resolve 'mongo', we're running locally
is_running_locally = True
try:
    socket.gethostbyname('mongo')
    is_running_locally = False
except socket.gaierror:
    is_running_locally = True

# Determine the MongoDB URL based on whether we're running locally or in Docker
if is_running_locally:
    # When running locally, use localhost instead of 'mongo'
    MONGODB_LOCAL_URL = "mongodb://localhost:27018/"
    client = pymongo.MongoClient(MONGODB_LOCAL_URL)
    logger.info(f"Running locally, MongoDB client created with URL: {MONGODB_LOCAL_URL}")
else:
    # When running in Docker, use the original URL
    client = pymongo.MongoClient(MONGODB_URL)
    logger.info(f"Running in Docker, MongoDB client created with URL: {MONGODB_URL}")

# Use a test-specific database name if in test mode
if is_testing:
    db_name = os.environ.get('DEPICTIO_MONGODB_DB_NAME', 'depictioDB_test')
    logger.info(f"Using test database: {db_name}")
else:
    db_name = settings.mongodb.db_name

# Function to clean the test database
def clean_test_database():
    """
    Clean the test database by dropping all collections.
    Only use this in test environments.
    """
    if not is_testing:
        logger.warning("Attempted to clean test database while not in test mode. Operation aborted.")
        return False
    
    try:
        # Get all collection names
        collection_names = client[db_name].list_collection_names()
        
        # Drop each collection
        for collection_name in collection_names:
            client[db_name].drop_collection(collection_name)
        
        logger.info(f"Cleaned test database: {db_name}")
        return True
    except Exception as e:
        logger.error(f"Error cleaning test database: {e}")
        return False

db = client[db_name]
logger.info(f"MongoDB database selected: {db_name}")
logger.info(f"Client: {client}")    
logger.info(f"DB: {db}")


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

# # Ensure MongoDB connection
# _ensure_mongodb_connection()

# # Initialize admin user and token
# initialize_db()
