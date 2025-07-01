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
    """
    Dummy function to simulate MongoDB connection.
    This function is a placeholder and does not perform any actual connection.
    """
    # This function is a placeholder and does not perform any actual connection.
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
) -> dict[str, bool | str | GroupBeanie | None]:
    """
    Create a group in the database using Beanie ODM.

    Args:
        group (GroupBeanie): The group to be created.

    Returns:
        dict: A dictionary containing the result of the group creation.
    """
    # Check if the group already exists
    existing_group = await GroupBeanie.find_one({"name": group.name})
    if existing_group:
        logger.info(f"Group {group.name} already exists in the database")
        return {
            "success": False,
            "message": "Group already exists",
            "group": existing_group,  # The CustomJSONResponse will handle serialization
        }

    # Insert the group into the database
    try:
        logger.debug(f"Preparing to add group {group.name} to the database")

        # Insert the document
        await group.insert()

        logger.info(f"Group {group.name} added to the database successfully")
        return {
            "success": True,
            "message": "Group created successfully",
            "group": group,  # The CustomJSONResponse will handle serialization
            "inserted_id": group.id,  # No need to manually convert to string
        }
    except Exception as e:
        logger.error(f"Error creating group {group.name}: {e}")
        return {
            "success": False,
            "message": f"Error creating group: {str(e)}",
            "group": None,
        }


@validate_call(validate_return=True)
def create_group_helper(group: Group) -> dict[str, bool | str | Group | None]:
    """
    Create a group in the database.

    Args:
        group (Group): The group to be created.

    Returns:
        dict: A dictionary containing the result of the group creation.
    """

    from depictio.api.v1.db import groups_collection

    # Check if the group already exists
    existing_group = groups_collection.find_one({"name": group.name})
    if existing_group:
        logger.info(f"Group {group.name} already exists in the database")
        return {
            "success": False,
            "message": "Group already exists",
            "group": existing_group,
        }

    # Insert the group into the database
    try:
        logger.debug(f"Preparing to add group {group.name} to the database")
        group_mongo = group.mongo()
        logger.debug(f"Group MongoDB object: {group_mongo}")

        result = groups_collection.insert_one(group_mongo)

        logger.info(f"Group {group.name} added to the database successfully")
        return {
            "success": True,
            "message": "Group created successfully",
            "group": group,
            "inserted_id": str(result.inserted_id),
        }
    except Exception as e:
        logger.error(f"Error creating group {group.name}: {e}")
        return {
            "success": False,
            "message": f"Error creating group: {str(e)}",
            "group": None,
        }


@validate_call(validate_return=True)
def delete_group_helper(group_id: PyObjectId) -> dict[str, bool | str]:
    # check first if the group is not in the following groups (users, admin)
    from depictio.api.v1.db import groups_collection

    groups = groups_collection.find()
    groups = [convert_objectid_to_str(group) for group in groups]
    for group in groups:
        if group["name"] in ["users", "admin"]:
            if group_id == group["_id"]:
                return {
                    "success": False,
                    "message": f"Cannot delete group {group['name']}",
                }

    result = groups_collection.delete_one({"_id": group_id})
    if result.deleted_count == 1:
        return {"success": True, "message": "Group deleted successfully"}
    else:
        return {"success": False, "message": "Group not found"}


@validate_call(validate_return=True)
async def create_access_token(
    token_data: TokenData,
    expiry_hours: int = None,  # type: ignore[invalid-parameter-default]
) -> tuple[str, datetime]:
    token_lifetime = token_data.token_lifetime

    if not expiry_hours:
        if token_lifetime == "short-lived":
            expires_delta = timedelta(hours=12)
        elif token_lifetime == "long-lived":
            expires_delta = timedelta(days=365)
        elif token_lifetime == "permanent":
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
    logger.debug(f"Token data: {to_encode}")
    logger.debug(f"Token expiration: {expire}")
    logger.debug(f"Token lifetime: {token_lifetime}")
    logger.debug(f"ALGORITHM: {ALGORITHM}")
    encoded_jwt = jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)
    logger.debug(f"Encoded JWT: {encoded_jwt}")
    return encoded_jwt, expire


@validate_call(validate_return=True)
def delete_user_from_db(
    user_id: PyObjectId | None = None, email: str | None = None
) -> dict[str, bool | str]:
    """
    Helper function to delete a user from the database using Beanie.

    Args:
        user_id: User's ID

    Returns:
        A dictionary indicating success or failure
    """
    logger.info(f"Deleting user with id: {user_id} or email: {email}")
    from depictio.api.v1.db import users_collection

    # Cannot use both user_id and email
    if not user_id and not email:
        logger.error("Either user_id or email must be provided")
        return {"success": False, "message": "Either user_id or email must be provided"}
    if user_id and email:
        logger.error("Cannot use both user_id and email")
        return {"success": False, "message": "Cannot use both user_id and email"}
    # If email is provided, find the user by email
    if email:
        user = users_collection.find_one({"email": email})
        if not user:
            logger.warning(f"User with email {email} not found")
            return {"success": False, "message": "User not found"}
        user_id = user["_id"]
        logger.info(f"User ID resolved from email: {user_id}")
    # If user_id is provided, find the user by user_id
    else:
        user_id = ObjectId(user_id)  # type: ignore[invalid-assignment]
        logger.info(f"User ID provided: {user_id}")

    if not user:
        logger.warning(f"User with id {user_id} not found")
        return {"success": False, "message": "User not found"}
    # Delete the user
    result = users_collection.delete_one({"_id": user_id})
    if result.deleted_count == 1:
        logger.info(f"User with id {user_id} deleted successfully")
        return {"success": True, "message": "User deleted successfully"}
    else:
        logger.error(f"Error deleting user with id {user_id}")
        return {"success": False, "message": "Error deleting user"}


def login_user(email: str):
    return {"logged_in": True, "email": email}


# Dummy logout function
def logout_user():
    return {"logged_in": False, "access_token": None}


def update_group_in_users_helper(group_id: ObjectId, group_users: list[UserBase]) -> dict:
    # retrieve the group
    from depictio.api.v1.db import groups_collection

    group = groups_collection.find_one({"_id": group_id})
    if not group:
        return {"success": False, "error": "Group not found."}

    # Convert group ObjectId to string for logging but keep original for queries
    group_str = convert_objectid_to_str(group)
    logger.debug(f"Updating group {group_str['_id']} in users")

    from depictio.api.v1.db import users_collection

    logger.debug(f"Group: {group_str}")
    logger.debug(f"Group users: {group_users}")

    # Get list of user IDs from the input users list
    group_user_ids = [ObjectId(user.id) for user in group_users]

    # Track users whose group memberships are updated
    updated_users = []

    # Create complete group info to add to users

    group_info = Group(
        id=ObjectId(group_id),  # type: ignore[invalid-argument-type]
        name=group_str["name"],
    )
    group_info = group_info.mongo()

    # Find all users that have this group
    current_users = list(users_collection.find({"groups._id": group_id}))
    current_user_ids = [user["_id"] for user in current_users]
    logger.debug(f"Current user ids: {current_user_ids}")

    # SCENARIO 1 & 2: Add or update group for users in group_user_ids
    for user_id in group_user_ids:
        # Then add the updated group info
        users_collection.update_one({"_id": user_id}, {"$addToSet": {"groups": group_info}})
        updated_users.append(str(user_id))

    # SCENARIO 3: Remove group from users no longer in the group
    users_to_remove_from = [uid for uid in current_user_ids if uid not in group_user_ids]
    logger.debug(f"Users to remove from group: {users_to_remove_from}")

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
