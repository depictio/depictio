from fastapi import APIRouter, Depends, HTTPException
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user

from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_email
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.models import UserBase
from depictio.api.v1.models.base import convert_objectid_to_str
from depictio.api.v1.models.top_structure import RootConfig
from depictio.api.v1.models_utils import validate_config

cli_endpoint_router = APIRouter()


@cli_endpoint_router.post("/validate_agent_config")
async def validate_agent_config_endpoint(agent_config: dict):
    # Validate that the agent config is correct using token and email
    user = agent_config["user"]
    token = user["token"]
    email = user["email"]

    logger.info(f"Agent config: {agent_config}")
    logger.info(f"User: {user}")
    logger.info(f"Token: {token}")
    logger.info(f"Email: {email}")

    db_user = fetch_user_from_email(email, return_tokens=True)

    if db_user:
        tokens = db_user.tokens
        for t in tokens:
            t = t.dict()
            if t["name"] == token["name"] and t["access_token"] == token["access_token"]:
                return {"valid": True}
        return {"valid": False}
    else:
        return {"valid": False}


@cli_endpoint_router.post("/validate_pipeline_config")
async def validate_pipeline_config_endpoint(pipeline_config: dict = dict(), current_user=Depends(get_current_user)):
    if not pipeline_config:
        return {"success": False, "error": "No pipeline config provided"}

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    logger.info(f"Current user: {current_user}")
    current_userbase = UserBase(**current_user.dict(exclude={"tokens", "is_active", "is_verified", "last_login", "registration_date", "password"}))
    logger.info(f"Current user base: {current_userbase}")

    current_userbase = convert_objectid_to_str(current_userbase)
    logger.info(f"Current user base: {current_user}")
    if not current_user:
        return {"success": False, "error": "Invalid token"}

    # Validate that the pipeline config is correct using agent config and pipeline config

    logger.info(f"Pipeline config: {pipeline_config}")

    # Validate Root config
    validated_pipeline_config = validate_config(pipeline_config, RootConfig)

    # For all workflows, add the current_user.id to the owners list
    for workflow in validated_pipeline_config.workflows:
        workflow.permissions["owners"].append(current_userbase)

    logger.info(f"Validated pipeline config: {validated_pipeline_config}")
    validated_pipeline_config = convert_objectid_to_str(validated_pipeline_config.dict())
    logger.info(f"Validated pipeline config: {validated_pipeline_config}")

    return {"success": True, "config": validated_pipeline_config}
