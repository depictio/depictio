from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _async_fetch_user_from_id
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.telemetry.cli_versions import record_cli_version
from depictio.models.models.cli import CLIConfig, CLIValidationResponse
from depictio.models.models.users import TokenBeanie, User

cli_endpoint_router = APIRouter()


@cli_endpoint_router.post("/validate_cli_config", response_model=CLIValidationResponse)
async def validate_cli_config_endpoint(
    cli_config: CLIConfig,
    current_user: User = Depends(get_current_user),
    x_depictio_cli_version: Optional[str] = Header(default=None),
):
    """Validate CLI configuration and token.

    Also the point where the calling CLI's version is noted, since ``api_login``
    makes this the de-facto preflight for every CLI command. Recording it here
    rather than in a middleware keeps the cost to the one request that already
    exists, and works even when the CLI's own outbound telemetry is switched off —
    the version is a header on a request the user is making anyway. Only the
    version string is kept; the hostname header the CLI also sends is never read
    for telemetry.

    SECURITY: now requires a valid bearer token in the ``Authorization`` header
    (``get_current_user``). Previously this endpoint had NO auth dependency, so
    any unauthenticated caller could submit a CLIConfig and probe whether the
    embedded token was valid. The CLI authenticates with a token anyway, so the
    header is the right credential source.

    NOTE (client follow-up required): ``depictio/cli/cli/utils/api_calls.py:api_login``
    currently POSTs the CLIConfig as JSON WITHOUT an Authorization header (the
    token sits inside the body at ``cli_config.user.token``). With this change
    that call will now receive 401 until the CLI is updated to also send
    ``Authorization: Bearer <access_token>`` (it can reuse
    ``generate_api_headers`` from ``depictio/cli/cli/utils/common.py``).
    """
    record_cli_version(x_depictio_cli_version)

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
