import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from bson import ObjectId
import sys
import os

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the main FastAPI app
from main import app, users_collection, client as mongo_client, db

# Create a test client
client = TestClient(app)


# Fixture to set up and tear down test database
@pytest.fixture(scope="module")
def test_db():
    # Use a test database
    test_client = MongoClient("mongodb://localhost:27018")
    test_db = test_client["test_depictioDV_dev"]
    test_collection = test_db["users"]

    # Yield the collection for tests to use
    yield test_collection

    # Clean up: drop the test database
    test_client.drop_database("test_depictioDV_dev")
    test_client.close()


# Fixture to replace the main collection with test collection
@pytest.fixture(autouse=True)
def override_collection(test_db, monkeypatch):
    monkeypatch.setattr("main.users_collection", test_db)


# Test creating a valid user
def test_create_user():
    user_data = {"username": "testuser", "email": "testuser@example.com", "age": 30}

    response = client.post("/users/", json=user_data)

    assert response.status_code == 200

    # Check response data
    result = response.json()
    assert result["username"] == user_data["username"]
    assert result["email"] == user_data["email"]
    assert result["age"] == user_data["age"]
    assert "id" in result
    assert len(result["id"]) == 24  # ObjectId length


# Test creating a user with invalid data
def test_create_user_invalid_data():
    # Test with invalid email
    invalid_email_user = {"username": "testuser2", "email": "invalid-email", "age": 30}

    response = client.post("/users/", json=invalid_email_user)
    assert response.status_code == 422  # Unprocessable Entity

    # Test with invalid age
    invalid_age_user = {"username": "testuser3", "email": "testuser3@example.com", "age": 200}

    response = client.post("/users/", json=invalid_age_user)
    assert response.status_code == 422  # Unprocessable Entity


# Test retrieving a user
def test_get_user(test_db):
    # First, create a user to retrieve
    user_data = {"username": "retrieveuser", "email": "retrieve@example.com", "age": 25}

    # Insert directly into test database
    result = test_db.insert_one(user_data)
    user_id = str(result.inserted_id)

    # Retrieve the user
    response = client.get(f"/users/{user_id}")

    assert response.status_code == 200

    # Check response data
    result = response.json()
    assert result["username"] == user_data["username"]
    assert result["email"] == user_data["email"]
    assert result["age"] == user_data["age"]


# Test retrieving a non-existent user
def test_get_user_not_found():
    # Use a valid but non-existent ObjectId
    non_existent_id = str(ObjectId())

    response = client.get(f"/users/{non_existent_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


# Test retrieving a user with invalid ObjectId
def test_get_user_invalid_id():
    # Use an invalid ObjectId
    invalid_id = "invalid_id"

    response = client.get(f"/users/{invalid_id}")

    assert response.status_code == 422  # Unprocessable Entity


# Test listing users
def test_list_users(test_db):
    # Clear existing users
    test_db.delete_many({})

    # Insert some test users
    test_users = [
        {"username": "user1", "email": "user1@example.com", "age": 25},
        {"username": "user2", "email": "user2@example.com", "age": 30},
    ]
    test_db.insert_many(test_users)

    # List users
    response = client.get("/users/")

    assert response.status_code == 200

    # Check response data
    result = response.json()
    assert len(result) == 2

    # Check user details
    usernames = [user["username"] for user in result]
    assert set(usernames) == {"user1", "user2"}
