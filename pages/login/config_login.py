import configparser
from pymongo import MongoClient
import pymongo

config = configparser.ConfigParser()
config.read('config_mongodb.txt')


# Establish the connection
client = MongoClient(f"mongodb://{config.get('database', 'host')}:{config.get('database', 'port')}")

# Access the database
db = client[config.get('database', 'db')]

# Test MongoDB connection
try:
    client.server_info()
    print("Connected to MongoDB!")
    # auth.seed_initial_admin_user(mongo_db)
except pymongo.errors.ConnectionFailure:
    print("Failed to connect to MongoDB.")


collection = db["users"]