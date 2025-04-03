import pymongo
from depictio.api.v1.configs.config import settings, MONGODB_URL
from depictio.api.v1.db_init import initialize_db
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.utils import _ensure_mongodb_connection
client = pymongo.MongoClient(MONGODB_URL)
db = client[settings.mongodb.db_name]
logger.info(f"MongoDB client created with URL: {MONGODB_URL}")
logger.info(f"MongoDB database selected: {settings.mongodb.db_name}")
logger.info(f"Client: {client}")    
logger.info(f"DB: {db}")


# redis_cache = redis.Redis(host=settings.redis.service_name, port=settings.redis.port, db=settings.redis.db)

# Define the collections

data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db[settings.mongodb.collections.users_collection]
groups_collection = db[settings.mongodb.collections.groups_collection]
deltatables_collection = db[settings.mongodb.collections.deltatables_collection]
jbrowse_collection = db[settings.mongodb.collections.jbrowse_collection]
dashboards_collection = db[settings.mongodb.collections.dashboards_collection]
initialization_collection = db[settings.mongodb.collections.initialization_collection]
projects_collection = db[settings.mongodb.collections.projects_collection]
test_collection = db[settings.mongodb.collections.test_collection]

# Ensure MongoDB connection
_ensure_mongodb_connection()

# Initialize admin user and token
initialize_db()
