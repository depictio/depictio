from datetime import datetime, time, timedelta
import hashlib
from typing import List
from bson import ObjectId
from fastapi import HTTPException
import httpx
import jwt
import bcrypt

from depictio.api.v1.configs.config import API_BASE_URL, PRIVATE_KEY, ALGORITHM
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    add_token_to_user,
    fetch_user_from_email,
)

# from depictio.api.v1.endpoints.user_endpoints.models import Token
from depictio_models.models.base import convert_objectid_to_str
from depictio_models.models.users import Token, UserBaseGroupLess, Group


def login_user(email):
    return {"logged_in": True, "email": email}


# Dummy logout function
def logout_user():
    return {"logged_in": False, "access_token": None}


# Check if user is logged in
def is_user_logged_in(session_data):
    return session_data.get("logged_in", False)


def hash_password(password: str) -> str:
    # Generate a salt
    salt = bcrypt.gensalt()
    # Hash the password with the salt
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    # Return the hashed password
    return hashed.decode("utf-8")


def verify_password(stored_hash: str, password: str) -> bool:
    logger.info(f"Stored hash: {stored_hash}")
    logger.info(f"Password to verify: {password}")
    # Verify the password against the stored hash
    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))


def find_user(email, return_tokens=False):
    # Call the core function directly
    user_data = fetch_user_from_email(email, return_tokens)
    if user_data:
        logger.info(f"Found user data: {user_data}")
        return user_data
    return None


def get_groups(TOKEN):
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/get_all_groups",
        headers={"Authorization ": f"Bearer {TOKEN}"},
    )
    if response.status_code == 200:
        return response.json()
    else:
        return []




def get_users_group() -> Group:
    response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/auth/get_users_group")
    if response.status_code == 200:
        group = response.json()
        logger.info(f"Group: {group}")
        group = Group.from_mongo(group)
        logger.info(f"Group: {group}")
        return group
    else:
        return []


# Function to add a new user
def add_user(email, password, group=None, is_admin=False):
    hashed_password = hash_password(password)
    # user_dict = {
    #     "email": email,
    #     "password": hashed_password,
    #     "is_admin": is_admin,
    #     "registration_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    #     "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    # }
    from depictio_models.models.users import User

    logger.info(f"Groups: {group}")
    if not group:
        group = get_users_group()
        logger.info(f"Users Group: {group}")
    logger.info(f"Groups: {group}")

    user = User(
        email=email,
        password=hashed_password,
        is_admin=is_admin,
        registration_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        groups=[group],
    )
    from depictio_models.utils import convert_model_to_dict

    logger.info(f"User: {user}")
    user = convert_model_to_dict(user)
    logger.info(f"User: {user}")
    response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/register", json=user)
    if response.status_code == 200:
        logger.info(f"User {email} added successfully.")
    else:
        logger.error(f"Error adding user {email}: {response.text}")
    return response


def edit_password(email, old_password, new_password, headers):
    logger.info(f"Editing password for user {email}.")
    logger.info(f"Old password: {old_password}")
    logger.info(f"New password: {new_password}")
    user = find_user(email)
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


def check_password(email, password):
    user = find_user(email)
    logger.info(f"User: {user}")
    if user:
        if verify_password(user.password, password):
            return True
    return False


def create_access_token(token_data):
    token_lifetime = token_data["token_lifetime"]

    if token_lifetime == "short-lived":
        expires_delta = timedelta(hours=12)
    elif token_lifetime == "long-lived":
        expires_delta = timedelta(days=365)
    else:
        raise ValueError("Invalid token type. Must be 'short-lived' or 'long-lived'.")

    to_encode = token_data.copy()
    expire = datetime.now() + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)
    return encoded_jwt, expire


def add_token(token_data: dict) -> dict:
    email = token_data["sub"]
    logger.info(f"Adding token for user {email}.")
    logger.info(f"Token: {token_data}")
    token, expire = create_access_token(token_data)
    token_data = {
        "access_token": token,
        "expire_datetime": expire.strftime("%Y-%m-%d %H:%M:%S"),
        "name": token_data["name"],
        "token_lifetime": token_data["token_lifetime"],
    }

    # create hash from access token
    token_data["hash"] = hashlib.sha256(token.encode()).hexdigest()

    logger.info(f"Adding token for user {email}.")
    user = find_user(email)
    logger.info(f"User: {user}")
    if user:
        # Check if the token already exists based on the name
        tokens = list_existing_tokens(email)
        logger.info(f"Tokens: {tokens}")
        for t in tokens:
            if t["name"] == token_data["name"]:
                logger.error(
                    f"Token with name {token_data['name']} already exists for user {email}."
                )
                return None

        logger.info(f"Adding token for user {email}.")
        token = Token(**token_data)
        logger.info(f"Token: {token}")
        logger.info(f"Token.mongo(): {token.mongo()}")

        result = add_token_to_user(user, token.mongo())
        logger.info(f"Result: {result}")
        if result["success"]:
            logger.info(f"Token added for user {email}.")
        else:
            logger.error(f"Error adding token for user {email}")
        # return token
    return token


def delete_token(email, token_id, current_token):
    logger.info(f"Deleting token for user {email}.")
    user = find_user(email)
    user = convert_objectid_to_str(user.dict())
    logger.info(f"User: {user}")
    if user:
        logger.info(f"Deleting token for user {email}.")
        request_body = {"user": user, "token_id": token_id}
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/delete_token",
            json=request_body,
            headers={"Authorization": f"Bearer {current_token}"},
        )
        if response.status_code == 200:
            logger.info(f"Token deleted for user {email}.")
        else:
            logger.error(f"Error deleting token for user {email}: {response.text}")
        return response
    return None


def purge_expired_tokens(token):
    if token:
        # Clean existing expired token from DB
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/purge_expired_tokens",
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code == 200:
            logger.info(f"Expired tokens purged successfully.")
            return response.json()
        else:
            logger.error(f"Error purging expired tokens: {response.text}")
            return None
    else:
        logger.error(f"Token not found.")
        return None


def check_token_validity(token):
    logger.info(f"Checking token validity.")
    logger.info(f"Token: {token}")
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/check_token_validity",
        json={"token": token},  # Sending the token in the body
    )
    if response.status_code == 200:
        logger.info(f"Token is valid.")
        return True
    logger.error(f"Token is invalid.")
    return False


def fetch_user_from_token(token):
    logger.info(f"Fetching user from token.")
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
        params={"token": token},
    )
    if response.status_code == 200:
        user_data = response.json()
        logger.info(f"Raw user data from response: {user_data}")
        return user_data
    return None


def list_existing_tokens(email):
    logger.info(f"Listing tokens for user {email}.")
    user = find_user(email, return_tokens=True)
    logger.info(f"User: {user}")
    if user:
        user = user.dict()
        return user.get("tokens", [])
    return None


def generate_agent_config(email, token, current_token):
    user = find_user(email)
    user = convert_objectid_to_str(user.dict())
    logger.info(f"User: {user}")

    token = convert_objectid_to_str(token)
    token = {
        "access_token": token["access_token"],
        "expire_datetime": token["expire_datetime"],
        "name": token["name"],
    }

    logger.info(f"Generating agent config for user {user}.")
    result = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/generate_agent_config",
        json={"user": user, "token": token},
        headers={"Authorization": f"Bearer {current_token}"},
    )
    # logger.info(f"Result: {result.json()}")
    if result.status_code == 200:
        logger.info(f"Agent config generated for user {user}.")
        return result.json()
    else:
        logger.error(f"Error generating agent config for user {user}: {result.text}")


def create_group_helper(group_dict: dict):
    from depictio.api.v1.db import client

    # Ensure MongoDB is up and running
    for _ in range(5):
        try:
            client.server_info()
            logger.info("Connected to MongoDB")
            break
        except Exception as e:
            logger.warning("Waiting for MongoDB to start...")
            time.sleep(5)
    else:
        raise Exception("Could not connect to MongoDB")

    from depictio.api.v1.db import groups_collection
    from depictio_models.models.users import Group

    # Check if the group already exists
    existing_group = groups_collection.find_one({"name": group_dict["name"]})
    if existing_group:
        logger.info("Admin group already exists in the database")
        return convert_objectid_to_str(existing_group)
    # Insert the group into the database
    else:
        logger.info("Adding admin group to the database")
        logger.info(f"Group: {group_dict}")
        admin_group = Group(**group_dict)
        logger.info(f"Group: {admin_group}")
        admin_group = admin_group.mongo()
        groups_collection.insert_one(admin_group)
        logger.info("Admin group added to the database")
        return convert_objectid_to_str(admin_group)


def delete_group_helper(group_id: ObjectId) -> dict:
    # check first if the group is not in the following groups (users, admin)
    from depictio.api.v1.db import groups_collection

    groups = groups_collection.find()
    groups = [convert_objectid_to_str(group) for group in groups]
    for group in groups:
        if group["name"] in ["users", "admin"]:
            if group_id == group["_id"]:
                return {"success": False, "error": "Cannot delete this group."}

    result = groups_collection.delete_one({"_id": group_id})
    if result.deleted_count == 1:
        return {"success": True}
    else:
        return {"success": False}


def update_group_in_users_helper(
    group_id: ObjectId, group_users: List[UserBaseGroupLess]
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


def api_create_group(group_dict: dict, current_token: str):
    logger.info(f"Creating group {group_dict}.")

    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/create_group",
        json=group_dict,
        headers={"Authorization": f"Bearer {current_token}"},
    )
    if response.status_code == 200:
        logger.info(f"Group {group_dict['name']} created successfully.")
    else:
        logger.error(f"Error creating group {group_dict['name']}: {response.text}")
    return response


def api_update_group_in_users(group_id: str, payload: dict, current_token: str):
    logger.info(f"Updating group {group_id}.")
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/update_group_in_users/{group_id}",
        json=payload,
        headers={"Authorization": f"Bearer {current_token}"},
    )
    if response.status_code == 200:
        logger.info(f"Group {group_id} updated successfully.")
    else:
        logger.error(f"Error updating group {group_id}: {response.text}")
    return response
