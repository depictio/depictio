# from gridfs import GridFS
from datetime import time
from fastapi import HTTPException
import pymongo
import redis

# from depictio.api.v1.admin_creation_startup import create_admin_user
from depictio.api.v1.configs.config import settings, MONGODB_URL, logger
from depictio.api.v1.db_init import initialize_db
from depictio.api.v1.endpoints.user_endpoints.models import User
from depictio.api.v1.endpoints.user_endpoints.utils import add_token, hash_password, verify_password

client = pymongo.MongoClient(MONGODB_URL)
db = client[settings.mongodb.db_name]
redis_cache = redis.Redis(host=settings.redis.service_name, port=settings.redis.port, db=settings.redis.db)

# Define the collections

data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db[settings.mongodb.collections.users_collection]
deltatables_collection = db[settings.mongodb.collections.deltatables_collection]
jbrowse_collection = db[settings.mongodb.collections.jbrowse_collection]
dashboards_collection = db[settings.mongodb.collections.dashboards_collection]
initialization_collection = db[settings.mongodb.collections.initialization_collection]

# Initialize admin user and token
initialize_db()