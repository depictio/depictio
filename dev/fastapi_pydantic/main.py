from typing import Annotated, Any, List, Optional

from bson import ObjectId
from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pymongo import MongoClient


# Helper function to convert ObjectId to string for validation
def convert_object_id(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, str):
        return v
    raise ValueError("Invalid ObjectId")


# Define PydanticObjectId type with proper validation and serialization
PydanticObjectId = Annotated[str, BeforeValidator(convert_object_id)]


# Pydantic model for input (creating a document)
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    age: Optional[int] = Field(None, gt=0, lt=120)


# Pydantic model for output (retrieving a document)
class UserResponse(UserCreate):
    id: PydanticObjectId = Field(alias="_id")
    # username: str
    # email: str
    # age: Optional[int] = None

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "_id": "67ec063aac2b04ea10e1f604",
                "username": "testuser",
                "email": "test@example.com",
                "age": 30,
            }
        },
    )


# FastAPI app setup
app = FastAPI()

# MongoDB connection
client = MongoClient("mongodb://localhost:27018")
db = client["depictioDV_dev"]
users_collection = db["users"]


@app.post("/users/", response_model=UserResponse)
async def create_user(user: UserCreate):
    # Convert Pydantic model to dict for MongoDB insertion
    print(f"Creating user: {user}")
    user_dict = user.model_dump()
    print(f"User dict before insertion: {user_dict}")

    # Insert the user and get the inserted ID
    result = users_collection.insert_one(user_dict)

    # Retrieve the newly created user
    created_user = users_collection.find_one({"_id": result.inserted_id})
    if not created_user:
        raise HTTPException(status_code=404, detail="Failed to create user")

    # Convert ObjectId to string before returning
    # This is the key fix - manually convert the _id to a string here
    created_user["_id"] = str(created_user["_id"])
    # created_user = UserResponse(**created_user)
    print(f"Created user: {created_user}")

    return created_user


@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str = Path(..., description="The ID of the user to retrieve")):
    try:
        object_id = ObjectId(user_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    user = users_collection.find_one({"_id": object_id})

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Convert to Pydantic model explicitly
    user_model = UserResponse(**user)
    print(f"Retrieved user: {user_model}")

    return user_model  # Return the Pydantic model instead of the dict


@app.get("/users/", response_model=List[UserResponse])
async def list_users():
    # Retrieve all users
    users = list(users_collection.find())

    # Convert ObjectId to string in each user document
    for user in users:
        user["_id"] = str(user["_id"])

    return users
