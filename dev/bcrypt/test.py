import logging

import bcrypt
import pymongo

# Setup logger
logger = logging.getLogger(__name__)

# MongoDB client setup
client = pymongo.MongoClient("mongodb://localhost:27018/")
db = client["depictioDB"]
users_collection = db["users_dev"]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(stored_hash: str, password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))


def find_user(email: str):
    user = users_collection.find_one({"email": email})
    return user


def login_user():
    return "User logged in"


def validate_login(login_email, login_password):
    if not login_email or not login_password:
        return "Please fill in all fields.", True, None

    user = find_user(login_email)
    if not user:
        return "Invalid email or password.", True, None

    logger.info(f"User: {user['email']}")

    if verify_password(user["password"], login_password):
        logger.info("Password verification successful.")
        return "Login successful!", False, login_user()

    logger.info("Password verification failed.")
    return "Invalid email or password.", True, None


# Example usage
def example_usage():
    # Example: Register a new user
    email = "thomas.weber@embl.de"
    password = "password123"
    hashed_password = hash_password(password)

    # Save the user to MongoDB
    users_collection.insert_one({"email": email, "password": hashed_password})

    # Example: Validate login
    result = validate_login(email, password)
    print(result)


# Run example usage
example_usage()
