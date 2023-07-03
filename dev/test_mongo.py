import pymongo

try:
    # Replace "localhost" and "27017" with your host and port number
    client = pymongo.MongoClient("mongodb://localhost:27017/")
    db = client.admin
    server_info = db.command("serverStatus")
    print("MongoDB server is running!")
except pymongo.errors.ConnectionFailure as e:
    print(f"Error connecting to MongoDB: {e}")
