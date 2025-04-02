import os
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.configs.config import settings
from depictio.api.v1.s3 import minios3_external_config

from depictio_models.utils import convert_model_to_dict
from depictio_models.models.users import UserBase, User, UserBaseCLIConfig


def generate_agent_config(current_user, request):
    logger.info(f"Current user type: {type(current_user)}")
    logger.info(f"Current user: {current_user}")
    logger.info(f"Request: {request}")

    # convert to dict if it is a User object
    # if isinstance(current_user, User):
    #     current_user = current_user.dict()

    # current_userbase = UserBase(
    #     **current_user
    #     # **current_user.dict(exclude={"tokens", "is_active", "is_verified", "last_login", "registration_date", "password", "current_access_token"})
    # )
    user = current_user.turn_to_userbasegroupless()
    logger.info(f"Current user base: {user}")
    token_subless = request["token"]
    token_subless.pop("sub", None)
    user = UserBaseCLIConfig(
        **user.dict(),
        token=request["token"],
    )

    logger.info(f"Current user base: {user}")
    current_userbase = convert_model_to_dict(user, exclude_none=True)

    # Keep only email and is_admin fields from user
    # token = request["token"]

    # Add token to user
    # current_userbase["token"] = token

    # FIXME: Temporary fix for local development - docker compose

    depictio_agent_config = {
        "api_base_url": f"http://{settings.fastapi.host}:{settings.fastapi.port}",
        "user": convert_model_to_dict(user, exclude_none=True),
        "s3": convert_model_to_dict(minios3_external_config, exclude_none=True),
    }

    return depictio_agent_config
