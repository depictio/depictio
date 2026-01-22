import time
from datetime import datetime, timedelta

import jwt
from beanie import PydanticObjectId
from bson import ObjectId
from pydantic import validate_call

from depictio.api.v1.configs.config import ALGORITHM, PRIVATE_KEY
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.users import Group, GroupBeanie, TokenData, UserBase, UserBeanie


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
def delete_group_helper(group_id: PyObjectId) -> dict[str, bool | str]:
    """Delete a group by ID, protecting system groups."""
    from depictio.api.v1.db import groups_collection

    groups = [convert_objectid_to_str(group) for group in groups_collection.find()]
    for group in groups:
        if group["name"] in ["users", "admin"] and group_id == group["_id"]:
            return {"success": False, "message": f"Cannot delete group {group['name']}"}

    result = groups_collection.delete_one({"_id": group_id})
    if result.deleted_count == 1:
        return {"success": True, "message": "Group deleted successfully"}
    return {"success": False, "message": "Group not found"}


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
    encoded_jwt = jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)
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


def update_group_in_users_helper(group_id: ObjectId, group_users: list[UserBase]) -> dict:
    """Update group membership for users, adding and removing as needed."""
    from depictio.api.v1.db import groups_collection, users_collection

    group = groups_collection.find_one({"_id": group_id})
    if not group:
        return {"success": False, "error": "Group not found."}

    group_str = convert_objectid_to_str(group)
    group_user_ids = [ObjectId(user.id) for user in group_users]
    updated_users = []

    group_info = Group(
        id=ObjectId(group_id),  # type: ignore[invalid-argument-type]
        name=group_str["name"],
    )
    group_info = group_info.mongo()

    current_users = list(users_collection.find({"groups._id": group_id}))
    current_user_ids = [user["_id"] for user in current_users]

    # Add or update group for users in group_user_ids
    for user_id in group_user_ids:
        users_collection.update_one({"_id": user_id}, {"$addToSet": {"groups": group_info}})
        updated_users.append(str(user_id))

    # Remove group from users no longer in the group
    users_to_remove_from = [uid for uid in current_user_ids if uid not in group_user_ids]
    if users_to_remove_from:
        users_collection.update_many(
            {"_id": {"$in": users_to_remove_from}},
            {"$pull": {"groups": {"_id": group_id}}},
        )
        updated_users.extend([str(uid) for uid in users_to_remove_from])

    return {
        "success": True,
        "message": f"Updated group membership for users: {updated_users}",
        "updated_users": updated_users,
    }
