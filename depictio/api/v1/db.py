# from gridfs import GridFS
import pymongo
import redis
from depictio.api.v1.configs.config import settings, MONGODB_URL


client = pymongo.MongoClient(MONGODB_URL)
print(client)
print(client.server_info())
db = client[settings.mongodb.db_name]
print(db)
# grid_fs = GridFS(db)
redis_cache = redis.Redis(
    host=settings.redis.host, port=settings.redis.port, db=settings.redis.db
)

# Define the collections


print("settings.mongodb.collections")
print(settings.mongodb.collections)

data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db[settings.mongodb.collections.users_collection]
deltatables_collection = db[settings.mongodb.collections.deltatables_collection]