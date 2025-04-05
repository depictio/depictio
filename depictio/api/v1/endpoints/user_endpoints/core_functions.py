import asyncio
from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException
from typing import Optional

from depictio.api.v1.configs.custom_logging import format_pydantic, logger

from depictio_models.models.users import User
from depictio_models.models.base import PyObjectId
from depictio_models.models.users import UserBeanie, TokenBeanie


async def async_fetch_user_from_token(token: str) -> Optional[UserBeanie]:
    """
    Fetch a user based on the provided access token by first querying TokenBeanie.

    Args:
        token: The access token to look up

    Returns:
        The UserBeanie object if found, None otherwise
    """
    # Validate input
    if not isinstance(token, str):
        logger.debug("Invalid token format")
        return None

    logger.debug(
        f"Fetching user from token {token[:10]}..."
    )  # Only log part of the token for security

    if not token:
        logger.debug("Empty token provided")
        return None

    # Find the token in the TokenBeanie collection
    token_doc = await TokenBeanie.find_one({"access_token": token})

    if not token_doc:
        logger.debug(f"No token found matching {token[:10]}...")
        return None

    # Get the user_id from the token and find the corresponding user
    user_id = token_doc.user_id
    user = await UserBeanie.get(user_id)

    if not user:
        logger.debug(f"Token exists but no matching user found with ID {user_id}")
        return None

    # Fetch linked documents if needed
    await user.fetch_all_links()
    logger.debug(f"User fetched from token: {format_pydantic(user_id)}")

    return user


def fetch_user_from_token(token: str) -> Optional[UserBeanie]:
    """Synchronous wrapper for backward compatibility"""
    try:
        # Use a new event loop to run the async function
        return asyncio.run(async_fetch_user_from_token(token))
    except RuntimeError:
        # Handle case where event loop is already running
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(async_fetch_user_from_token(token))


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

    logger.debug(f"Current user ID: {user_id}")

    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    elif isinstance(user_id, dict) and "$oid" in user_id:
        user_id = ObjectId(user_id["$oid"])

    # Log the _id and the query structure
    logger.debug(f"User _id (ObjectId): {user_id}")
    query = {"_id": user_id}

    # Get existing tokens from the user and remove the token to be deleted
    user_data = users_collection.find_one(query)
    tokens = user_data.get("tokens", [])
    logger.debug(f"Tokens: {tokens}")

    # Remove expired tokens, convert expire_datetime from that format (2024-08-21 02:26:39) to datetime object
    tokens = [
        e
        for e in tokens
        if datetime.strptime(e["expire_datetime"], "%Y-%m-%d %H:%M:%S") > datetime.now()
    ]
    logger.debug(f"Tokens after deletion: {tokens}")

    # Update the user with the new tokens
    update = {"$set": {"tokens": tokens}}
    logger.debug(f"Query: {query}")

    # Insert in the user collection
    result = users_collection.update_one(query, update)
    logger.debug(f"Update result: {result.modified_count} document(s) updated")

    # Return success status
    return {"success": True, "message": f"{result.modified_count} document(s) updated"}


def check_if_token_is_valid(token: str) -> bool:
    from depictio.api.v1.db import users_collection
    # Check if the token exists in the database and has not expired

    # Query the database for the user with a non-expired token
    user = users_collection.find_one(
        {
            "tokens": {
                "$elemMatch": {
                    "access_token": token,
                    "expire_datetime": {
                        "$gt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    },
                }
            }
        }
    )
    # logger.info(f"Checking token: {token} : {user}")

    if user:
        return True
    else:
        return False


def fetch_user_from_id(user_id: PyObjectId, return_tokens: bool = False) -> User:
    from depictio.api.v1.db import users_collection

    if return_tokens:
        # Find the user in the database and only returns tokens with token_lifetime = "long-lived"
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        # user = users_collection.find_one({"_id": ObjectId(user_id) }, {"tokens": {"$elemMatch": {"token_lifetime": "long-lived"}}})

        # Filter the tokens to only return the long-lived tokens
        user["tokens"] = [
            token for token in user["tokens"] if token["token_lifetime"] == "long-lived"
        ]

    else:
        # Find the user in the database and exclude the tokens field
        logger.info(f"Fetching user with ID: {user_id} of type {type(user_id)}")
        user = users_collection.find_one({"_id": ObjectId(user_id)}, {"tokens": 0})
        logger.info(f"User: {user}")
    logger.debug(f"Fetching user with ID: {user_id} : {user}")
    user = User.from_mongo(user)
    logger.debug("After conversion to User model")
    logger.debug(user)

    if user:
        # user = user.dict()
        return user
    else:
        return None


async def async_fetch_user_from_id(
    user_id: PyObjectId, return_tokens: bool = False
) -> UserBeanie:
    user = await UserBeanie.find(user_id)
    if not user:
        logger.debug(f"No user found with ID {user_id}")
        raise HTTPException(status_code=404, detail="User not found")
    if return_tokens:
        # Find the user in the database and only returns tokens with token_lifetime = "long-lived"
        # user = users_collection.find_one({"_id": ObjectId(user_id)})
        # user = users_collection.find_one({"_id": ObjectId(user_id) }, {"tokens": {"$elemMatch": {"token_lifetime": "long-lived"}}})

        # Filter the tokens to only return the long-lived tokens
        user["tokens"] = [
            token for token in user["tokens"] if token["token_lifetime"] == "long-lived"
        ]
        user.tokens = [
            token for token in user.tokens if token.token_lifetime == "long-lived"
        ]

    else:
        # Find the user in the database and exclude the tokens field
        # logger.info(f"Fetching user with ID: {user_id} of type {type(user_id)}")
        # user = users_collection.find_one({"_id": ObjectId(user_id)}, {"tokens": 0})
        # logger.info(f"User: {user}")
        user.tokens = []
    # logger.debug(f"Fetching user with ID: {user_id} : {user}")
    # user = User.from_mongo(user)
    # logger.debug("After conversion to User model")
    # logger.debug(user)

    # if user:
    #     # user = user.dict()
    #     return user
    # else:
    #     return None
    return user


async def fetch_user_from_email(email: str) -> Optional[UserBeanie]:
    """
    Fetch a user based on their email address.

    Args:
        email: The email address to look up
        return_tokens: Whether to include tokens in the response (only long-lived tokens if True)

    Returns:
        The UserBeanie object if found, None otherwise
    """
    # Find the user by email
    user = await UserBeanie.find_one({"email": email})

    if not user:
        logger.debug(f"No user found with email {email}")
        return None

    # Fetch linked documents
    await user.fetch_all_links()
    logger.debug(f"User fetched from email: {format_pydantic(user)}")
    return user


# def fetch_user_from_email(email: str, return_tokens: bool = False) -> User:
#     from depictio.api.v1.db import users_collection

#     if return_tokens:
#         # Find the user in the database and only returns tokens with token_lifetime = "long-lived"
#         user = users_collection.find_one({"email": email})
#         logger.info(f"Fetching user with email: {email} : {user}")
#         # user = users_collection.find_one({"email": email }, {"tokens": {"$elemMatch": {"token_lifetime": "long-lived"}}})

#         # Filter the tokens to only return the long-lived tokens
#         user["tokens"] = [
#             token for token in user["tokens"] if token["token_lifetime"] == "long-lived"
#         ]

#     else:
#         # Find the user in the database and exclude the tokens field
#         user = users_collection.find_one({"email": email}, {"tokens": 0})
#     logger.debug(f"Fetching user with email: {email} : {user}")
#     user = User.from_mongo(user)
#     logger.debug("After conversion to User model")
#     logger.debug(user)

#     if user:
#         # user = user.dict()
#         return user
#     else:
#         return None


# def fetch_user_from_token(token: str) -> User:
#     from depictio.api.v1.db import users_collection
#     # check if token is a string
#     if not isinstance(token, str):
#         return None

#     logger.debug(f"Fetching user from token {token}")

#     if not token:
#         return None

#     # Find the user in the database and exclude the tokens field
#     user = users_collection.find_one({"tokens.access_token": token}, {"tokens": 0})

#     if not user:
#         return None

#     logger.debug(f"Fetching user with token: {token} : {user}")
#     user = User.from_mongo(user)
#     logger.debug("After conversion to User model")
#     logger.debug(f"Current access token: {token}")
#     user.current_access_token = token
#     logger.debug(user)

#     if user:
#         return user
#     else:
#         return None
