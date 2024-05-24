import pymongo
from depictio.api.v1.configs.config import settings

# FIXME: This is a temporary solution to avoid the error: "pymongo.errors.ServerSelectionTimeoutError: localhost:27017: [Errno 111] Connection refused"
MONGODB_URL = f"mongodb://localhost:{settings.mongodb.port}/"

# Set up the MongoDB client
client = pymongo.MongoClient(MONGODB_URL)
db = client[settings.mongodb.db_name]

# Access the collections
users_collection = db[settings.mongodb.collections.users_collection]

# Insert a new document into the users collection
new_user = {
    "username": "Cezanne",
    "password": "Paul"
}

result = users_collection.insert_one(new_user)
print(f"Inserted user with _id: {result.inserted_id}")
