from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.agent_config_utils import (
    _generate_agent_config,
    export_agent_config,
)
from depictio.api.v1.endpoints.user_endpoints.core_functions import _add_token
from depictio.models.models.users import TokenBeanie, UserBeanie


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
    token = await _add_token(token_data)

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
