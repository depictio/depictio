from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _async_fetch_user_from_id
from depictio.models.models.cli import CLIConfig
from depictio.models.models.users import TokenBeanie


class CLIValidationResponse(BaseModel):
    """Response model for CLI config validation."""

    success: bool
    message: str
    is_admin: bool = False
    user_id: str | None = None
    email: str | None = None


cli_endpoint_router = APIRouter()


@cli_endpoint_router.post("/validate_cli_config", response_model=CLIValidationResponse)
async def validate_cli_config_endpoint(cli_config: CLIConfig):
    logger.info(f"CLI config: {cli_config}")

    token = cli_config.user.token
    logger.info(f"Token: {token}")

    # Find token by access_token since TokenData doesn't have id
    _token_check = await TokenBeanie.find_one(
        {
            "access_token": token.access_token,
            # check expire datetime is greater than now
            "expire_datetime": {"$gt": datetime.now()},
        }
    )

    if not _token_check:
        logger.error("Token expired or not found.")
        return CLIValidationResponse(success=False, message="Token expired or not found.")
    logger.debug(f"Token check: {_token_check}")
    # Check if the user exists in the database using user_id from the found token
    user = await _async_fetch_user_from_id(_token_check.user_id)
    logger.debug(f"User fetched: {user}")
    if not user:
        logger.error("User not found.")
        return CLIValidationResponse(success=False, message="User not found.")
    # logger.info(f"User check: {user}")

    response = CLIValidationResponse(
        success=True,
        message="CLI config is valid.",
        is_admin=bool(user.is_admin),
        user_id=str(user.id),
        email=user.email,
    )

    logger.info(f"CLI config validation response: {response}")
    return response


# @cli_endpoint_router.post("/validate_project_config")
# async def validate_pipeline_config_endpoint(pipeline_config: dict = dict(), current_user=Depends(get_current_user)):

#     logger.info(f"Pipeline config: {pipeline_config}")
#     logger.info(f"Current user: {current_user}")

#     if not pipeline_config:
#         return {"success": False, "error": "No pipeline config provided"}

#     if not current_user:
#         raise HTTPException(status_code=401, detail="Current user not found.")

#     logger.info(f"Current user: {current_user}")
#     current_userbase = UserBase(**current_user.dict())
#     # current_userbase = UserBase(**current_user.dict(exclude={"tokens", "is_active", "is_verified", "last_login", "registration_date", "password"}))
#     logger.info(f"Current user base: {current_userbase}")

#     current_userbase = convert_objectid_to_str(current_userbase)
#     logger.info(f"Current user base: {current_user}")
#     if not current_user:
#         logger.error("Current user not found.")
#         return {"success": False, "error": "Invalid token"}

#     # Validate that the pipeline config is correct using cli config and pipeline config

#     logger.info(f"Pipeline config: {pipeline_config}")

#     # Validate Root config
#     validated_pipeline_config = validate_config(pipeline_config, RootConfig)

#     # For all workflows, add the current_user.id to the owners list
#     # for workflow in validated_pipeline_config.workflows:
#     #     workflow.permissions["owners"].append(current_userbase)

#     logger.info(f"Validated pipeline config: {validated_pipeline_config}")
#     validated_pipeline_config = convert_objectid_to_str(validated_pipeline_config.dict())
#     logger.info(f"Validated pipeline config: {validated_pipeline_config}")

#     return {"success": True, "config": validated_pipeline_config}
