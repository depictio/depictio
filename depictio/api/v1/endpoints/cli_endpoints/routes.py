
from fastapi import APIRouter, Depends
from depictio.api.v1.endpoints.user_endpoints.auth import oauth2_scheme

from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_email, fetch_user_from_token
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.models import UserBase
from depictio.api.v1.models.base import convert_objectid_to_str
from depictio.api.v1.models.top_structure import RootConfig
from depictio.api.v1.models_utils import validate_config

cli_endpoint_router = APIRouter()


# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/fetch_user/from_token")


# Define the collections from the settings
# data_collections_collection = db[settings.mongodb.collections.data_collection]
# workflows_collection = db[settings.mongodb.collections.workflow_collection]
# runs_collection = db[settings.mongodb.collections.runs_collection]
# files_collection = db[settings.mongodb.collections.files_collection]
# users_collection = db["users"]

# Define the MinIO endpoint and bucket name from the settings
# endpoint_url = settings.minio.internal_endpoint
# bucket_name = settings.minio.bucket


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
async def validate_pipeline_config_endpoint(pipeline_config: dict = dict(), token: str = Depends(oauth2_scheme)):
    
    if not pipeline_config:
        return {"success": False, "error": "No pipeline config provided"}
    
    if not token:
        return {"success": False, "error": "No token provided"}
    
    current_user = fetch_user_from_token(token)
    logger.info(f"Current user: {current_user}")
    current_userbase =user_base = UserBase(**current_user.dict(exclude={'tokens', 'is_active', 'is_verified', 'last_login', 'registration_date', 'password'}))
    logger.info(f"Current user base: {current_userbase}")

    current_userbase = convert_objectid_to_str(current_userbase)
    logger.info(f"Current user base: {current_user}")
    if not current_user:
        return {"success": False, "error": "Invalid token"}

    # Validate that the pipeline config is correct using agent config and pipeline config

    logger.info(f"Pipeline config: {pipeline_config}")
    logger.info(f"Token: {token}")

    # Validate Root config
    validated_pipeline_config = validate_config(pipeline_config, RootConfig)

    # For all workflows, add the current_user.id to the owners list
    for workflow in validated_pipeline_config.workflows:

        workflow.permissions["owners"].append(current_userbase)

    logger.info(f"Validated pipeline config: {validated_pipeline_config}")
    validated_pipeline_config = convert_objectid_to_str(validated_pipeline_config.dict())
    logger.info(f"Validated pipeline config: {validated_pipeline_config}")

    return {"success": True, "config": validated_pipeline_config}
