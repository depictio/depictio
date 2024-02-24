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
