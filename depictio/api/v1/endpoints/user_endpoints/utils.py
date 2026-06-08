import json
import time
from datetime import datetime, timedelta

import jwt
from beanie import PydanticObjectId
from bson import ObjectId
from fastapi import HTTPException
from pydantic import validate_call

from depictio.api.v1.configs.config import ALGORITHM, PRIVATE_KEY_PATH
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.key_utils import get_private_key
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import (
    Group,
    GroupBeanie,
    TokenBeanie,
    TokenData,
    UserBeanie,
)


def _dummy_mongodb_connection():
    """Get MongoDB server info for connection testing."""
    from depictio.api.v1.db import client

    return client.server_info()


@validate_call
def _ensure_mongodb_connection(max_attempts: int = 5, sleep_interval: int = 5) -> None:
    """
    Ensure MongoDB connection is established.

    Args:
        max_attempts (int, optional): Maximum number of connection attempts. Defaults to 5.
        sleep_interval (int, optional): Sleep time between attempts. Defaults to 5.

    Raises:
        RuntimeError: If unable to connect to MongoDB after max_attempts.
    """
    from depictio.api.v1.db import client

    for attempt in range(1, max_attempts + 1):
        try:
            info = client.server_info()
            logger.debug(f"Successfully connected to MongoDB (Attempt {attempt})")
            return info  # type: ignore[invalid-return-type]
        except Exception as e:
            if attempt == max_attempts:
                logger.error(f"Failed to connect to MongoDB after {max_attempts} attempts")
                raise RuntimeError(f"Could not connect to MongoDB: {e}")
            logger.warning(f"Waiting for MongoDB to start (Attempt {attempt})...")
            time.sleep(sleep_interval)


@validate_call(validate_return=True)
async def get_users_by_group_id(group_id: PydanticObjectId) -> list[UserBeanie]:
    """
    Retrieve all users that belong to a specific group by group ID.
    """
    # Find users where the groups array contains a reference to this group ID
    users = await UserBeanie.find(
        {"groups": {"$elemMatch": {"$ref": "groups", "$id": group_id}}}
    ).to_list()

    return users


@validate_call()
async def create_group_helper_beanie(
    group: GroupBeanie,
) -> dict[str, bool | str | GroupBeanie | PyObjectId | PydanticObjectId | None]:
    """
    Create a group in the database using Beanie ODM.

    Args:
        group: The group to be created.

    Returns:
        dict: A dictionary containing the result of the group creation.
    """
    existing_group = await GroupBeanie.find_one({"name": group.name})
    if existing_group:
        return {"success": False, "message": "Group already exists", "group": existing_group}

    try:
        await group.insert()
        return {
            "success": True,
            "message": "Group created successfully",
            "group": group,
            "inserted_id": group.id,
        }
    except Exception as e:
        logger.error(f"Error creating group {group.name}: {e}")
        return {"success": False, "message": f"Error creating group: {str(e)}", "group": None}


@validate_call(validate_return=True)
def create_group_helper(group: Group) -> dict[str, bool | str | Group | None]:
    """
    Create a group in the database.

    Args:
        group: The group to be created.

    Returns:
        dict: A dictionary containing the result of the group creation.
    """
    from depictio.api.v1.db import groups_collection

    existing_group = groups_collection.find_one({"name": group.name})
    if existing_group:
        return {"success": False, "message": "Group already exists", "group": existing_group}

    try:
        group_mongo = group.mongo()
        result = groups_collection.insert_one(group_mongo)
        return {
            "success": True,
            "message": "Group created successfully",
            "group": group,
            "inserted_id": str(result.inserted_id),
        }
    except Exception as e:
        logger.error(f"Error creating group {group.name}: {e}")
        return {"success": False, "message": f"Error creating group: {str(e)}", "group": None}


@validate_call(validate_return=True)
async def create_access_token(
    token_data: TokenData,
    expiry_hours: int = None,  # type: ignore[invalid-parameter-default]
) -> tuple[str, datetime]:
    """Create a JWT access token with the specified expiry."""
    if not expiry_hours:
        if token_data.token_lifetime == "short-lived":
            expires_delta = timedelta(hours=12)
        elif token_data.token_lifetime == "long-lived":
            expires_delta = timedelta(days=365)
        elif token_data.token_lifetime == "permanent":
            expires_delta = timedelta(days=365 * 100)
        else:
            raise ValueError(
                "Invalid token type. Must be 'short-lived', 'long-lived', or 'permanent'."
            )
    else:
        expires_delta = timedelta(hours=expiry_hours)

    to_encode = token_data.model_dump()
    expire = datetime.now() + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, get_private_key(PRIVATE_KEY_PATH), algorithm=ALGORITHM)
    return encoded_jwt, expire


@validate_call(validate_return=True)
def delete_user_from_db(
    user_id: PyObjectId | None = None, email: str | None = None
) -> dict[str, bool | str]:
    """
    Delete a user from the database by ID or email.

    Args:
        user_id: User's ID (optional, mutually exclusive with email)
        email: User's email (optional, mutually exclusive with user_id)

    Returns:
        A dictionary indicating success or failure
    """
    from depictio.api.v1.db import users_collection

    if not user_id and not email:
        return {"success": False, "message": "Either user_id or email must be provided"}
    if user_id and email:
        return {"success": False, "message": "Cannot use both user_id and email"}

    user = None
    if email:
        user = users_collection.find_one({"email": email})
        if not user:
            return {"success": False, "message": "User not found"}
        user_id = user["_id"]
    else:
        user_id = ObjectId(user_id)  # type: ignore[invalid-assignment]
        user = users_collection.find_one({"_id": user_id})

    if not user:
        return {"success": False, "message": "User not found"}

    result = users_collection.delete_one({"_id": user_id})
    if result.deleted_count == 1:
        return {"success": True, "message": "User deleted successfully"}
    return {"success": False, "message": "Error deleting user"}


def login_user(email: str):
    """Return login success payload."""
    return {"logged_in": True, "email": email}


def logout_user():
    """Return logout payload."""
    return {"logged_in": False, "access_token": None}


async def _get_admin_token_localstorage_payload() -> str:
    """Return the JSON string that the frontend expects in `localStorage['local-store']`.

    Used by the Playwright-driven screenshot endpoint and by the standalone
    docs-screenshot CLI to inject admin auth into a fresh browser context.
    """
    admin_user = await UserBeanie.find_one({"is_admin": True, "is_anonymous": {"$ne": True}})
    if not admin_user:
        raise HTTPException(status_code=404, detail="Admin user not found")

    token = await TokenBeanie.find_one(
        {
            "user_id": admin_user.id,
            "refresh_expire_datetime": {"$gt": datetime.now()},
        }
    )
    if not token:
        raise HTTPException(status_code=404, detail="Valid token not found")

    token_data = token.model_dump(exclude_none=True)
    token_data["_id"] = str(token_data.pop("id", None))
    token_data["user_id"] = str(token_data["user_id"])
    token_data["logged_in"] = True

    if isinstance(token_data.get("expire_datetime"), datetime):
        token_data["expire_datetime"] = token_data["expire_datetime"].strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(token_data.get("created_at"), datetime):
        token_data["created_at"] = token_data["created_at"].strftime("%Y-%m-%d %H:%M:%S")

    return json.dumps(token_data)
