# from gridfs import GridFS
import pymongo
import redis
from depictio.api.v1.configs.config import settings


client = pymongo.MongoClient(settings.MONGODB_URL)
db = client[settings.mongodb["db_name"]]
# grid_fs = GridFS(db)
redis_cache = redis.Redis(
    host=settings.redis["host"], port=settings.redis["port"], db=settings.redis["db"]
)
