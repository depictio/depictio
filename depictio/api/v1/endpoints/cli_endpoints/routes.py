from datetime import datetime

from fastapi import APIRouter

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _async_fetch_user_from_id
from depictio.models.models.cli import CLIConfig, CLIValidationResponse
from depictio.models.models.users import TokenBeanie

cli_endpoint_router = APIRouter()


@cli_endpoint_router.post("/validate_cli_config", response_model=CLIValidationResponse)
async def validate_cli_config_endpoint(cli_config: CLIConfig):
    """Validate CLI configuration and token."""
    token = cli_config.user.token

    _token_check = await TokenBeanie.find_one(
        {
            "access_token": token.access_token,
            "expire_datetime": {"$gt": datetime.now()},
        }
    )

    if not _token_check:
        logger.error("Token expired or not found.")
        return CLIValidationResponse(success=False, message="Token expired or not found.")

    user = await _async_fetch_user_from_id(_token_check.user_id)
    if not user:
        logger.error("User not found.")
        return CLIValidationResponse(success=False, message="User not found.")

    return CLIValidationResponse(
        success=True,
        message="CLI config is valid.",
        is_admin=bool(user.is_admin),
        user_id=str(user.id),
        email=user.email,
    )
