from typing import List, Optional, Any
from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, Field, ConfigDict, field_serializer
from pydantic.json_schema import JsonSchemaValue
from bson import ObjectId
import pymongo
from pymongo import MongoClient


# Custom JSON encoder for ObjectId with Pydantic v2 validation
class PyObjectId(str):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler):
        # Use the default string schema and add custom validation
        from pydantic_core import core_schema

        return core_schema.no_info_plain_validator_function(
            cls.validate,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @classmethod
    def validate(cls, v: Any) -> ObjectId:
        # Handle both string and ObjectId inputs
        if isinstance(v, ObjectId):
            return v

        # Validate string representation of ObjectId
        if isinstance(v, str):
            if not ObjectId.is_valid(v):
                raise ValueError("Invalid ObjectId")
            return ObjectId(v)

        raise TypeError("ObjectId must be a string or ObjectId")


# Pydantic model for input (creating a document)
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    age: Optional[int] = Field(None, gt=0, lt=120)


# Pydantic model for output (retrieving a document)
class UserResponse(BaseModel):
    id: PyObjectId = Field(alias="_id")
    username: str
    email: str
    age: Optional[int]

    # Customize serialization of ObjectId
    @field_serializer("id")
    def serialize_id(self, id: PyObjectId):
        return str(id)


# FastAPI app setup
app = FastAPI()

# MongoDB connection
client = MongoClient("mongodb://localhost:27018")
db = client["depictioDV_dev"]
users_collection = db["users"]


@app.post("/users/", response_model=UserResponse)
async def create_user(user: UserCreate):
    print(f"Creating user: {user}")
    # Convert Pydantic model to dict for MongoDB insertion
    user_dict = user.model_dump()
    print(f"User dict: {user_dict}")

    # Insert the user and get the inserted ID
    result = users_collection.insert_one(user_dict)
    print(f"Inserted user ID: {result.inserted_id}")

    # Retrieve the newly created user
    created_user = users_collection.find_one({"_id": result.inserted_id})
    print(f"Created user: {created_user}")

    # Return the user using the UserResponse model
    user_response = UserResponse(**created_user)
    print(f"User response: {user_response}")
    return user_response


@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: PyObjectId = Path(..., description="The ID of the user to retrieve"),
):
    print(f"Retrieving user with ID: {user_id}")
    # Find the user
    user = users_collection.find_one({"_id": user_id})
    print(f"Found user: {user}")

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Return the user using the UserResponse model
    user_response = UserResponse(**user)

    print(f"User response: {user_response}")

    return user_response


@app.get("/users/", response_model=List[UserResponse])
async def list_users():
    # Retrieve all users
    users = list(users_collection.find())

    # Convert to UserResponse models
    return [UserResponse(**user) for user in users]
