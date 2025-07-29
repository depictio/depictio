import asyncio
from typing import Any, List, Optional

import httpx
from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_serializer


# Reuse the PyObjectId class from the main application
class PyObjectId(str):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler):
        from pydantic_core import core_schema

        return core_schema.no_info_plain_validator_function(
            cls.validate,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @classmethod
    def validate(cls, v: Any) -> ObjectId:
        if isinstance(v, ObjectId):
            return v
        if isinstance(v, str):
            if not ObjectId.is_valid(v):
                raise ValueError("Invalid ObjectId")
            return ObjectId(v)
        raise TypeError("ObjectId must be a string or ObjectId")


# Pydantic model for user response (matching the server-side model)
class UserResponse(BaseModel):
    id: PyObjectId = Field(alias="_id")
    username: str
    email: str
    age: Optional[int]

    # Customize serialization of ObjectId
    @field_serializer("id")
    def serialize_id(self, id: PyObjectId):
        return str(id)

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)


class FastAPIClient:
    def __init__(self, base_url: str = "http://localhost:8001"):
        """
        Initialize the async FastAPI client with a base URL.

        :param base_url: Base URL of the FastAPI application
        """
        self.base_url = base_url
        # Create an async client that will be used for all requests
        self.client = httpx.AsyncClient()

    async def create_user(
        self, username: str, email: str, age: Optional[int] = None
    ) -> UserResponse:
        """
        Async method to create a new user and return the UserResponse object.

        :param username: User's username
        :param email: User's email
        :param age: User's age (optional)
        :return: UserResponse object
        """
        # Prepare the user data payload
        payload = {"username": username, "email": email, "age": age}

        # Send POST request to create user
        response = await self.client.post(f"{self.base_url}/users/", json=payload)

        # Raise an exception for HTTP errors
        response.raise_for_status()

        # Convert the response to UserResponse model
        return UserResponse(**response.json())

    async def get_user(self, user_id: str) -> UserResponse:
        """
        Async method to retrieve a user by their ID.

        :param user_id: User's ObjectId as a string
        :return: UserResponse object
        """
        # Send GET request to retrieve user
        response = await self.client.get(f"{self.base_url}/users/{user_id}")

        # Raise an exception for HTTP errors
        response.raise_for_status()

        # Convert the response to UserResponse model
        return UserResponse(**response.json())

    async def list_users(self) -> List[UserResponse]:
        """
        Async method to retrieve all users.

        :return: List of UserResponse objects
        """
        # Send GET request to list users
        response = await self.client.get(f"{self.base_url}/users/")

        # Raise an exception for HTTP errors
        response.raise_for_status()

        # Convert each user in the response to UserResponse model
        return [UserResponse(**user) for user in response.json()]

    async def close(self):
        """
        Close the async client session.
        """
        await self.client.aclose()


async def main():
    # Example usage of the async FastAPI client
    client = FastAPIClient()

    try:
        # Create a new user
        print("Creating a new user...")
        new_user = await client.create_user(username="johndoe", email="johndoe@example.com", age=30)
        print(f"Created user: {new_user}")

        # Retrieve the newly created user
        print("\nRetrieving the created user...")
        retrieved_user = await client.get_user(str(new_user.id))
        print(f"Retrieved user: {retrieved_user}")

        # List all users
        print("\nListing all users...")
        all_users = await client.list_users()
        for user in all_users:
            print(f"User: {user}")

    except httpx.RequestError as e:
        print(f"A request error occurred: {e}")
    except httpx.HTTPStatusError as e:
        print(f"An HTTP status error occurred: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        # Always close the client
        await client.close()


if __name__ == "__main__":
    # Use asyncio to run the async main function
    asyncio.run(main())
