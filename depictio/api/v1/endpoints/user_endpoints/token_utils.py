from datetime import datetime, timedelta
from typing import Any

import jwt
from beanie import PydanticObjectId

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.agent_config_utils import (
    _generate_agent_config,
    export_agent_config,
)
from depictio.models.models.users import TokenBeanie, UserBeanie


# Assuming you have this function somewhere in your codebase
async def create_access_token(token_data: dict) -> tuple[str, datetime]:
    """Create a JWT access token."""
    # This is a placeholder - replace with your actual token creation logic
    expires_delta = timedelta(days=30 if token_data["token_lifetime"] == "long-lived" else 1)
    expire = datetime.now() + expires_delta

    to_encode = token_data.copy()
    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, "your-secret-key", algorithm="HS256")
    return encoded_jwt, expire


async def add_token(token_data: dict) -> TokenBeanie:
    """
    Add a token for a user using Beanie.

    Args:
        token_data: Dictionary containing token information

    Returns:
        The created TokenBeanie object
    """
    user_id = token_data["sub"]
    logger.info(f"Adding token for user {user_id}.")
    logger.info(f"Token data: {token_data}")

    # Find the user by ID - use _id not id
    user = await UserBeanie.get(PydanticObjectId(user_id))
    if not user:
        logger.error(f"User with ID {user_id} not found.")
        raise ValueError(f"User with ID {user_id} not found.")

    # Create the token
    token_string, expire = await create_access_token(token_data)

    # Create a new TokenBeanie object
    token = TokenBeanie(
        user_id=(user.id),
        access_token=token_string,
        expire_datetime=expire,
        name=token_data.get("name"),
        token_lifetime=token_data.get("token_lifetime", "short-lived"),
    )

    logger.debug(token)

    # Save the token to the database
    await token.insert()

    # Add the token to the user's tokens list
    # user.tokens.append(token)
    # await user.save()

    logger.info(f"Token created for user {user_id}.")
    return token


async def create_default_token(user: UserBeanie) -> dict[str, Any] | None:
    """
    Create a default token for a user if it doesn't exist.

    Args:
        user: UserBeanie object

    Returns:
        TokenBeanie object if created, None if token already exists
    """
    # Check if default token exists for this user
    existing_token = await TokenBeanie.find_one({"user_id": user.id, "name": "default_token"})

    if existing_token:
        logger.warning(f"Default token for {user.email} already exists")
        return None

    logger.debug(f"Creating default token for {user.email}")

    token_data = {
        "sub": str(user.id),
        "name": "default_token",
        "token_lifetime": "long-lived",
    }

    # Create and add the token
    token = await add_token(token_data)

    # Generate and export agent config
    cli_config = await _generate_agent_config(user, token)
    config_path = await export_agent_config(
        cli_config=cli_config, email=user.email, wipe=bool(settings.mongodb.wipe)
    )
    config_path = None

    logger.debug(f"Default token created for {user.email}")
    return {
        "token": token.model_dump(),
        "config_path": config_path,
        "new_token_created": True,
    }
