from datetime import datetime, timedelta
import time
import hashlib
from typing import Dict, List, Optional, Tuple, Union
from beanie import PydanticObjectId
from bson import ObjectId
from fastapi import HTTPException
import httpx
import jwt
import bcrypt
from pydantic import EmailStr, validate_call

from depictio.api.v1.configs.config import API_BASE_URL, PRIVATE_KEY, ALGORITHM
from depictio.api.v1.configs.custom_logging import format_pydantic, logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    async_fetch_user_from_email,
    fetch_user_from_email,
    # fetch_user_from_id,
)

# from depictio.api.v1.endpoints.user_endpoints.models import Token
from depictio_models.models.base import convert_objectid_to_str, PyObjectId
from depictio_models.utils import convert_model_to_dict
from depictio_models.models.users import (
    Token,
    Group,
    GroupBeanie,
    UserBeanie,
    TokenData,
    TokenBeanie,
    TokenBase,
    UserBase,
)


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
            return info
        except Exception as e:
            if attempt == max_attempts:
                logger.error(
                    f"Failed to connect to MongoDB after {max_attempts} attempts"
                )
                raise RuntimeError(f"Could not connect to MongoDB: {e}")
            logger.warning(f"Waiting for MongoDB to start (Attempt {attempt})...")
            time.sleep(sleep_interval)


@validate_call(validate_return=True)
def hash_password(password: str) -> str:
    # Generate a salt
    salt = bcrypt.gensalt()
    # Hash the password with the salt
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    # Return the hashed password
    return hashed.decode("utf-8")


@validate_call(validate_return=True)
def verify_password(stored_hash: str, password: str) -> bool:
    logger.info(f"Stored hash: {stored_hash}")
    logger.info(f"Password to verify: {password}")
    # Verify the password against the stored hash
    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))


@validate_call(validate_return=True)
async def check_password(email: str, password: str) -> bool:
    """
    Check if the provided password matches the stored password for the user.
    Args:
        email (str): The email of the user.
        password (str): The password to verify.
    Returns:
        bool: True if the password matches, False otherwise.
    """
    logger.debug(f"Checking password for user {email}.")
    user = await async_fetch_user_from_email(email)
    logger.debug(f"User found: {user}")
    if user:
        if verify_password(user.password, password):
            return True
    return False


@validate_call(validate_return=True)
async def get_users_by_group_id(group_id: PydanticObjectId) -> List[UserBeanie]:
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
) -> Dict[str, Union[bool, str, Optional[GroupBeanie]]]:
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
def create_group_helper(group: Group) -> Dict[str, Union[bool, str, Optional[Group]]]:
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
def delete_group_helper(group_id: PyObjectId) -> Dict[str, Union[bool, str]]:
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
async def create_access_token(token_data: TokenData) -> Tuple[str, datetime]:
    token_lifetime = token_data.token_lifetime

    if token_lifetime == "short-lived":
        expires_delta = timedelta(hours=12)
    elif token_lifetime == "long-lived":
        expires_delta = timedelta(days=365)
    else:
        raise ValueError("Invalid token type. Must be 'short-lived' or 'long-lived'.")

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
async def add_token(token_data: TokenData) -> TokenBeanie:
    email = token_data.sub
    logger.info(f"Adding token for user {email}.")
    logger.info(f"Token: {format_pydantic(token_data)}")
    token_value, expire = await create_access_token(token_data)

    token = TokenBeanie(
        access_token=token_value,
        expire_datetime=expire.strftime("%Y-%m-%d %H:%M:%S"),
        name=token_data.name,
        token_lifetime=token_data.token_lifetime,
        user_id=token_data.sub,
    )
    logger.debug(f"Token: {format_pydantic(token)}")

    await TokenBeanie.save(token)

    logger.info(f"Token created for user {email}.")

    return token


# # Function to add a new user
# def add_user(email, password, group=None, is_admin=False):
#     hashed_password = hash_password(password)
#     # user_dict = {
#     #     "email": email,
#     #     "password": hashed_password,
#     #     "is_admin": is_admin,
#     #     "registration_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#     #     "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#     # }
#     from depictio_models.models.users import User

#     logger.info(f"Groups: {group}")
#     # if not group:
#     #     group = get_users_group()
#     #     logger.info(f"Users Group: {group}")
#     # logger.info(f"Groups: {group}")

#     user = User(
#         email=email,
#         password=hashed_password,
#         is_admin=is_admin,
#         registration_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#         last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#         groups=[group],
#     )
#     from depictio_models.utils import convert_model_to_dict

#     logger.info(f"User: {user}")
#     user = convert_model_to_dict(user)
#     logger.info(f"User: {user}")
#     response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/register", json=user)
#     if response.status_code == 200:
#         logger.info(f"User {email} added successfully.")
#     else:
#         logger.error(f"Error adding user {email}: {response.text}")
#     return response


@validate_call(validate_return=True)
async def create_user_in_db(
    email: EmailStr, password: str, is_admin: bool = False
) -> Optional[Dict[str, Union[bool, str, Optional[UserBeanie]]]]:
    """
    Helper function to create a user in the database using Beanie.

    Args:
        email: User's email address
        password: Raw password (will be hashed)
        group: User's group (optional)
        is_admin: Whether user is admin

    Returns:
        The created UserBeanie object if successful
    """
    logger.info(f"Creating user with email: {email}")

    # Check if the user already exists
    existing_user = await UserBeanie.find_one({"email": email})

    if existing_user:
        logger.warning(f"User {email} already exists in the database")
        return {
            "success": False,
            "message": "User already exists",
            "user": existing_user,  # The CustomJSONResponse will handle serialization
        }

    # Hash the password
    hashed_password = hash_password(password)

    # Create current timestamp
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create new UserBeanie
    user_beanie = UserBeanie(
        email=email,
        password=hashed_password,
        is_admin=is_admin,
        registration_date=current_time,
        last_login=current_time,
        # groups=[group],
    )

    # Save to database
    await user_beanie.create()
    logger.info(f"User created with id: {user_beanie.id}")

    return {
        "success": True,
        "message": "User created successfully",
        "user": user_beanie,
    }


@validate_call(validate_return=True)
def delete_user_from_db(
    user_id: PyObjectId = None, email: str = None
) -> Dict[str, Union[bool, str]]:
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
        user_id = ObjectId(user_id)
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


# def get_users_group() -> Group:
#     response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/auth/get_users_group")
#     if response.status_code == 200:
#         group = response.json()
#         logger.info(f"Group: {group}")
#         group = Group.from_mongo(group)
#         logger.info(f"Group: {group}")
#         return group
#     else:
#         return []


def edit_password(email, old_password, new_password, headers):
    logger.info(f"Editing password for user {email}.")
    logger.info(f"Old password: {old_password}")
    logger.info(f"New password: {new_password}")
    user = find_user_by_email(email)
    user = convert_objectid_to_str(user.dict())
    if user:
        if verify_password(user["password"], old_password):
            hashed_password = hash_password(new_password)
            user_dict = {"new_password": hashed_password, "old_password": old_password}
            logger.info(
                f"Updating password for user {email} with new password: {new_password}"
            )
            response = httpx.post(
                f"{API_BASE_URL}/depictio/api/v1/auth/edit_password",
                json=user_dict,
                headers=headers,
            )
            if response.status_code == 200:
                logger.info(f"Password for user {email} updated successfully.")
            else:
                logger.error(
                    f"Error updating password for user {email}: {response.text}"
                )
            return response
        else:
            logger.error(f"Old password for user {email} is incorrect.")
            return {"error": "Old password is incorrect."}
    else:
        logger.error(f"User {email} not found.")
        return {"error": "User not found."}


def list_existing_tokens(email):
    logger.info(f"Listing tokens for user {email}.")
    user = find_user_by_email(email, return_tokens=True)
    logger.info(f"User: {user}")
    if user:
        user = user.model_dump()
        return user.get("tokens", [])
    return None


def update_group_in_users_helper(
    group_id: ObjectId, group_users: List[UserBase]
) -> dict:
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
        id=ObjectId(group_id),
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
        users_collection.update_one(
            {"_id": user_id}, {"$addToSet": {"groups": group_info}}
        )
        updated_users.append(str(user_id))

    # SCENARIO 3: Remove group from users no longer in the group
    users_to_remove_from = [
        uid for uid in current_user_ids if uid not in group_user_ids
    ]
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


@validate_call()
def find_user_by_email(email: str, return_tokens: bool = False) -> Optional[Dict]:
    """
    Find a user by email.
    Args:
        email (str): The email of the user.
        return_tokens (bool): Whether to return tokens or not.
    Returns:
        dict: The user data if found, None otherwise.
    """
    logger.debug(f"Finding user with email: {email}")
    user_data = fetch_user_from_email(email, return_tokens)
    if user_data:
        logger.info(f"Found user data: {user_data}")
        return user_data
    return None
