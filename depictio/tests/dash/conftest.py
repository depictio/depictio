import os
import pytest
from bson import ObjectId
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from depictio.api.v1.endpoints.user_endpoints.utils import hash_password
from depictio_models.models.users import UserBeanie, GroupBeanie, TokenBeanie
from depictio_models.utils import get_config
from depictio import BASE_PATH

# Set environment variables for test mode
os.environ["DEPICTIO_TEST_MODE"] = "true"
os.environ["DEPICTIO_MONGODB_DB_NAME"] = "depictioDB_test"

@pytest.fixture(scope="function", autouse=True)
def setup_test_database():
    """
    Fixture to set up the test database for all tests.
    This cleans the database and initializes it with test data.
    """
    # Import the database modules
    from depictio.api.v1.db import client, db, users_collection, tokens_collection, groups_collection, clean_test_database
    
    # Clean the test database
    clean_test_database()
    
    # Load initial users from config
    config_path = os.path.join(BASE_PATH, "depictio", "api", "v1", "configs", "initial_users.yaml")
    initial_config = get_config(config_path)
    
    # Initialize the test database with test users
    for user_config in initial_config.get("users", []):
        hashed_password = hash_password(user_config["password"])
        users_collection.insert_one({
            "_id": ObjectId(user_config["id"]),
            "email": user_config["email"],
            "password": hashed_password,
            "is_admin": user_config.get("is_admin", False),
            "registration_date": "2023-01-01 00:00:00",
            "last_login": "2023-01-01 00:00:00",
            "is_active": True,
            "is_verified": False,
            "groups": []
        })
    
    # Initialize groups
    for group_config in initial_config.get("groups", []):
        groups_collection.insert_one({
            "_id": ObjectId(group_config["id"]),
            "name": group_config["name"],
            "description": group_config.get("description", ""),
            "users_ids": [ObjectId(user_id) for user_id in group_config.get("users_ids", [])]
        })
    
    yield
    
    # No need to clean up after the test as we'll clean before the next test

@pytest.fixture(scope="function")
async def mock_mongodb_async():
    """
    Fixture to mock MongoDB for async operations.
    This initializes Beanie with a mock database.
    """
    # Create async mock client
    client = AsyncMongoMockClient()
    db = client.test_db
    
    # Initialize Beanie with the mock database
    await init_beanie(
        database=db,
        document_models=[UserBeanie, GroupBeanie, TokenBeanie]
    )
    
    # Load initial users from config
    config_path = os.path.join(BASE_PATH, "depictio", "api", "v1", "configs", "initial_users.yaml")
    initial_config = get_config(config_path)
    
    # Initialize the mock database with test users
    for user_config in initial_config.get("users", []):
        hashed_password = hash_password(user_config["password"])
        user = UserBeanie(
            id=user_config["id"],
            email=user_config["email"],
            password=hashed_password,
            is_admin=user_config.get("is_admin", False),
            registration_date="2023-01-01 00:00:00",
            last_login="2023-01-01 00:00:00",
            is_active=True,
            is_verified=False
        )
        await user.create()
    
    # Initialize groups
    for group_config in initial_config.get("groups", []):
        group = GroupBeanie(
            id=group_config["id"],
            name=group_config["name"],
            description=group_config.get("description", "")
        )
        await group.create()
    
    yield db
    
    # Clean up
    for collection in await db.list_collection_names():
        await db[collection].delete_many({})
