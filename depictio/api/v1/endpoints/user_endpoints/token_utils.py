from typing import Any

from depictio.api.v1.configs.config import settings
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
        Token data dict if created, None if token already exists
    """
    existing_token = await TokenBeanie.find_one({"user_id": user.id, "name": "default_token"})
    if existing_token:
        return None

    token_data = {
        "sub": str(user.id),
        "name": "default_token",
        "token_lifetime": "long-lived",
    }

    token = await _add_token(token_data)

    # Generate and export agent config
    cli_config = await _generate_agent_config(user, token)
    await export_agent_config(
        cli_config=cli_config, email=user.email, wipe=bool(settings.mongodb.wipe)
    )

    return {"token": token.model_dump(), "config_path": None, "new_token_created": True}
