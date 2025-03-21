# from gridfs import GridFS
import pymongo
# import redis

# from depictio.api.v1.admin_creation_startup import create_admin_user
from depictio.api.v1.configs.config import settings, MONGODB_URL
from depictio.api.v1.db_init import initialize_db

client = pymongo.MongoClient(MONGODB_URL)
db = client[settings.mongodb.db_name]
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

# Initialize admin user and token
initialize_db()
