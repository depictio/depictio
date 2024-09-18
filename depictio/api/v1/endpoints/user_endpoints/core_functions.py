from datetime import datetime
from bson import ObjectId
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.models import User, UserBase
from depictio.api.v1.models.base import convert_objectid_to_str


def generate_agent_config(current_user, request):
    logger.debug(f"Current user type: {type(current_user)}")
    logger.debug(f"Current user: {current_user}")
    logger.debug(f"Request: {request}")


    # convert to dict if it is a User object
    if isinstance(current_user, User):
        current_user = current_user.dict()
    

    current_userbase = UserBase(
        **current_user
        # **current_user.dict(exclude={"tokens", "is_active", "is_verified", "last_login", "registration_date", "password", "current_access_token"})
    )

    logger.debug(f"Current user base: {current_userbase}")
    current_userbase = convert_objectid_to_str(current_userbase.dict())

    # Keep only email and is_admin fields from user
    token = request["token"]

    # Add token to user
    current_userbase["token"] = token

    # Depictio API config
    from depictio.api.v1.configs.config import API_BASE_URL

    # FIXME: Temporary fix for local development - docker compose
    tmp_api_base_url = API_BASE_URL.replace("depictio_backend", "localhost")

    depictio_agent_config = {
        "api_base_url": tmp_api_base_url,
        "user": current_userbase,
    }

    return depictio_agent_config


def add_token_to_user(user, token):
    from depictio.api.v1.db import users_collection

    logger.info(f"Adding token to user: {user}")
    # Ensure _id is an ObjectId
    # user_id = user["_id"]
    user_id = user.id
    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    elif isinstance(user_id, dict) and "$oid" in user_id:
        user_id = ObjectId(user_id["$oid"])

    # Log the _id and the query structure
    logger.info(f"User _id (ObjectId): {user_id}")
    query = {"_id": user_id}
    update = {"$push": {"tokens": token}}
    logger.info(f"Query: {query}")
    logger.info(f"Update: {update}")

    # Insert in the user collection
    result = users_collection.update_one(query, update)
    logger.info(f"Update result: {result.modified_count} document(s) updated")

    # Return success status
    return {"success": result.modified_count > 0}


def purge_expired_tokens_from_user(user_id):
    from depictio.api.v1.db import users_collection

    logger.info(f"Current user ID: {user_id}")

    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    elif isinstance(user_id, dict) and "$oid" in user_id:
        user_id = ObjectId(user_id["$oid"])

    # Log the _id and the query structure
    logger.info(f"User _id (ObjectId): {user_id}")
    query = {"_id": user_id}

    # Get existing tokens from the user and remove the token to be deleted
    user_data = users_collection.find_one(query)
    tokens = user_data.get("tokens", [])
    logger.info(f"Tokens: {tokens}")

    # Remove expired tokens, convert expire_datetime from that format (2024-08-21 02:26:39) to datetime object
    tokens = [e for e in tokens if datetime.strptime(e["expire_datetime"], "%Y-%m-%d %H:%M:%S") > datetime.now()]
    logger.info(f"Tokens after deletion: {tokens}")

    # Update the user with the new tokens
    update = {"$set": {"tokens": tokens}}
    logger.info(f"Query: {query}")

    # Insert in the user collection
    result = users_collection.update_one(query, update)
    logger.info(f"Update result: {result.modified_count} document(s) updated")

    # Return success status
    return {"success": True, "message": f"{result.modified_count} document(s) updated"}


def check_if_token_is_valid(token: str) -> bool:
    from depictio.api.v1.db import users_collection

    # Check if the token exists in the database and has not expired

    # Query the database for the user with a non-expired token
    user = users_collection.find_one({"tokens": {"$elemMatch": {"access_token": token, "expire_datetime": {"$gt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}}})
    logger.info(f"Checking token: {token} : {user}")

    if user:
        return True
    else:
        return False


def fetch_user_from_email(email: str, return_tokens: bool = False) -> User:
    from depictio.api.v1.db import users_collection  # Move import inside the function

    if return_tokens:
        # Find the user in the database and only returns tokens with token_lifetime = "long-lived"
        user = users_collection.find_one({"email": email})
        # user = users_collection.find_one({"email": email }, {"tokens": {"$elemMatch": {"token_lifetime": "long-lived"}}})

        # Filter the tokens to only return the long-lived tokens
        user["tokens"] = [token for token in user["tokens"] if token["token_lifetime"] == "long-lived"]

    else:
        # Find the user in the database and exclude the tokens field
        user = users_collection.find_one({"email": email}, {"tokens": 0})
    logger.debug(f"Fetching user with email: {email} : {user}")
    user = User.from_mongo(user)
    logger.debug("After conversion to User model")
    logger.debug(user)

    if user:
        # user = user.dict()
        return user
    else:
        return None


def fetch_user_from_token(token: str) -> User:
    logger.debug(f"Fetching user from token {token}")
    from depictio.api.v1.db import users_collection  # Move import inside the function

    if not token:
        return None

    # Find the user in the database and exclude the tokens field
    user = users_collection.find_one({"tokens.access_token": token}, {"tokens": 0})

    if not user:
        return None

    logger.debug(f"Fetching user with token: {token} : {user}")
    user = User.from_mongo(user)
    logger.debug("After conversion to User model")
    logger.debug(f"Current access token: {token}")
    user.current_access_token = token
    logger.debug(user)

    if user:
        return user
    else:
        return None
