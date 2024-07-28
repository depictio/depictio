# from gridfs import GridFS
from datetime import time
from fastapi import HTTPException
import pymongo
import redis
from depictio.api.v1.configs.config import settings, MONGODB_URL, logger
from depictio.api.v1.endpoints.user_endpoints.models import User
from depictio.api.v1.endpoints.user_endpoints.utils import hash_password, verify_password

client = pymongo.MongoClient(MONGODB_URL)
db = client[settings.mongodb.db_name]
redis_cache = redis.Redis(
    host=settings.redis.service_name, port=settings.redis.port, db=settings.redis.db
)

# Define the collections

data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db[settings.mongodb.collections.users_collection]
deltatables_collection = db[settings.mongodb.collections.deltatables_collection]
jbrowse_collection = db[settings.mongodb.collections.jbrowse_collection]
dashboards_collection = db[settings.mongodb.collections.dashboards_collection]






# Create a user if it does not exist

user_dict = {
    "username": "admin",
    "password": hash_password("changeme"),
    "is_admin": True,
    "email": "admin@embl.de"
}

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
    users_collection.insert_one(User(**user_dict).mongo())
    logger.info("Admin user added to the database")