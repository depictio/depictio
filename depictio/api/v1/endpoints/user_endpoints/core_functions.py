import asyncio
from datetime import datetime
from beanie import PydanticObjectId
from bson import ObjectId
from fastapi import HTTPException
from typing import Dict, Optional

from pydantic import EmailStr, validate_call

from depictio.api.v1.configs.custom_logging import format_pydantic, logger

from depictio_models.models.users import User
from depictio_models.models.base import PyObjectId
from depictio_models.models.users import UserBeanie, TokenBeanie


@validate_call(validate_return=True)
async def async_fetch_user_from_token(token: str) -> Optional[UserBeanie]:
    """
    Fetch a user based on the provided access token by first querying TokenBeanie.

    Args:
        token: The access token to look up

    Returns:
        The UserBeanie object if found, None otherwise
    """
    logger.debug(f"Current token: {token}")

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
    # await user.fetch_all_links()
    logger.debug(f"User fetched from token: {format_pydantic(user)}")

    return user


@validate_call(validate_return=True)
async def async_fetch_user_from_email(
    email: EmailStr, return_tokens: bool = False
) -> Optional[UserBeanie]:
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


def fetch_user_from_email(email: str, return_tokens: bool = False) -> User:
    from depictio.api.v1.db import users_collection

    user = users_collection.find_one({"email": email})
    # user = users_collection.find_one({"email": email}, {"tokens": 0})
    logger.debug(f"Fetching user with email: {email} : {user}")
    user = User.from_mongo(user)
    logger.debug("After conversion to User model")
    logger.debug(user)

    if user:
        # user = user.dict()
        return user
    else:
        return None


@validate_call(validate_return=True)
async def async_fetch_user_from_id(
    user_id: PyObjectId, return_tokens: bool = False
) -> UserBeanie:
    user = await UserBeanie.find(user_id)
    if not user:
        logger.debug(f"No user found with ID {user_id}")
        raise HTTPException(status_code=404, detail="User not found")
    if return_tokens:
        user.tokens = [
            token for token in user.tokens if token.token_lifetime == "long-lived"
        ]

    else:
        user.tokens = []
    return user


@validate_call(validate_return=True)
async def check_if_token_is_valid(token: TokenBeanie) -> bool:
    """
    Check if the provided token is valid and not expired.

    Args:
        token: The token to check

    Returns:
        True if the token is valid, False otherwise
    """
    # Check if the token exists in the database and has not expired
    check = await TokenBeanie.find_one(
        {
            "access_token": token.access_token,
            "expire_datetime": {
                "$gt": datetime.now()
            },  # Use datetime object, not string
            "user_id": token.user_id,
        }
    )
    logger.debug(f"Checking token: {token.access_token} : {check}")
    if check:
        # Token exists and is not expired
        return True
    else:
        # Token does not exist or is expired
        return False


@validate_call(validate_return=True)
async def purge_expired_tokens_from_user(user_id: PyObjectId) -> Dict[str, bool | int]:
    """
    Purge expired tokens for a user.
    Args:
        user_id: The user ID to purge tokens for
    Returns:
        A dictionary with success status and deleted count
    """
    logger.debug(f"Current user ID: {user_id}")

    # Delete the expired tokens - delete many
    outdated_tokens = await TokenBeanie.find(
        {"user_id": user_id, "expire_datetime": {"$lt": datetime.now()}}
    ).to_list()

    for token in outdated_tokens:
        await token.delete()

    logger.debug(f"Deleted {len(outdated_tokens)} expired tokens for user {user_id}")

    if not outdated_tokens:
        logger.debug(f"No expired tokens found for user {user_id}")
        return {"success": False, "deleted_count": 0}

    # Return success status
    return {
        "success": True,
        "deleted_count": len(outdated_tokens),
    }

