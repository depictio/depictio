from typing import Dict, Any, Optional
import httpx
import sys
import os
from pydantic import EmailStr, validate_call

from depictio.api.v1.configs.config import (
    FASTAPI_INTERNAL_API_KEY,
    API_BASE_URL,
)
from depictio.api.v1.configs.custom_logging import format_pydantic, logger

from depictio.api.v1.endpoints.user_endpoints.utils import find_user_by_email
from depictio.models.models.users import User, TokenBase
from depictio.models.utils import convert_model_to_dict
from depictio.models.models.base import PyObjectId, convert_objectid_to_str

# Check if running in a test environment
# First check environment variable, then check for pytest in sys.argv
is_testing = os.environ.get("DEPICTIO_TEST_MODE", "false").lower() == "true" or any(
    "pytest" in arg for arg in sys.argv
)

# Add a query parameter to API calls when in test mode to indicate test database should be used
API_QUERY_PARAMS = {"test_mode": "true"} if is_testing else {}


@validate_call(validate_return=True)
def api_call_register_user(
    email: EmailStr, password: str, group: Optional[str] = None, is_admin: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Register a new user by calling the API.

    Args:
        email: User's email address
        password: User's password
        group: User's group (optional)
        is_admin: Whether user is admin

    Returns:
        Response from registration or None if failed
    """
    try:
        logger.info(f"Registering user with email: {email}")
        logger.debug(f"Password: {password}")
        logger.debug(f"Group: {group}")
        logger.debug(f"Is Admin: {is_admin}")

        # Create payload with parameters
        params = {"email": email, "password": password, "is_admin": is_admin}

        # # Add group if provided
        # if group:
        #     params["group"] = group

        # Add test mode parameter if in test environment
        # params.update(API_QUERY_PARAMS)

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/register",
            params=params,
        )

        if response.status_code == 200:
            logger.info("User registered successfully.")
            return response.json()
        else:
            logger.error(f"Registration error: {response.text}")
            return None

    except Exception as e:
        logger.error(f"Registration exception: {str(e)}")
        return None


@validate_call(validate_return=True)
def api_call_fetch_user_from_token(token: str) -> Optional[User]:
    """
    Fetch a user from the authentication service using a token.
    Synchronous version for Dash compatibility.

    Args:
        token: The authentication token

    Returns:
        Optional[User]: The user if found, None otherwise
    """
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
        params={"token": token},
        headers={"Authorization": f"Bearer {token}"},
    )

    if response.status_code == 404:
        return None

    user_data = response.json()
    logger.debug(f"User data fetched: {user_data}")

    if not user_data:
        return None

    user = User(**user_data)

    logger.debug(f"User object created: {format_pydantic(user)}")

    return user


@validate_call(validate_return=True)
def api_call_fetch_user_from_email(email: EmailStr) -> Optional[User]:
    """
    Fetch a user from the authentication service using an email.
    Synchronous version for Dash compatibility.

    Args:
        email: The user's email address

    Returns:
        Optional[User]: The user if found, None otherwise
    """
    logger.debug(f"Fetching user with email: {email}")
    logger.debug(f"API Base URL: {API_BASE_URL}")
    logger.debug(f"Internal API Key: {FASTAPI_INTERNAL_API_KEY}")

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_email",
        params={"email": email},
        headers={"api-key": FASTAPI_INTERNAL_API_KEY},
    )

    if response.status_code == 404:
        return None

    user_data = response.json()
    logger.debug(f"User data fetched: {user_data}")

    if not user_data:
        return None

    user = User(**user_data)

    logger.debug(f"User object created: {format_pydantic(user)}")

    return user


@validate_call(validate_return=True)
def purge_expired_tokens(token: str) -> Optional[Dict[str, Any]]:
    """
    Purge expired tokens from the database.
    Args:
        token: The authentication token
    Returns:
        Optional[Dict[str, Any]]: The response from the purge operation
    """
    if token:
        # Clean existing expired token from DB
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/purge_expired_tokens",
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code == 200:
            logger.info("Expired tokens purged successfully.")
            return response.json()
        else:
            logger.error(f"Error purging expired tokens: {response.text}")
            return None
    else:
        logger.error("Token not found.")
        return None


@validate_call(validate_return=True)
def check_token_validity(token: TokenBase):
    logger.info("Checking token validity.")
    logger.info(f"Token: {token}")
    # logger.info(f"Token : {format_pydantic(TokenBase(**token))}")

    logger.info(f"Token: {format_pydantic(token)}")
    # logger.info(f"Token model dump: {token.mongo()}")
    logger.info(f"Token model dump: {convert_model_to_dict(token)}")

    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/check_token_validity",
        json=convert_model_to_dict(token),  # Sending the token in the body
    )
    if response.status_code == 200:
        logger.info("Token is valid.")
        return True
    logger.error("Token is invalid.")
    return False


def api_create_group(group_dict: dict, current_token: str):
    logger.info(f"Creating group {group_dict}.")

    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/create_group",
        json=group_dict,
        headers={"Authorization": f"Bearer {current_token}"},
    )
    if response.status_code == 200:
        logger.info(f"Group {group_dict['name']} created successfully.")
    else:
        logger.error(f"Error creating group {group_dict['name']}: {response.text}")
    return response


def api_update_group_in_users(group_id: str, payload: dict, current_token: str):
    logger.info(f"Updating group {group_id}.")
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/update_group_in_users/{group_id}",
        json=payload,
        headers={"Authorization": f"Bearer {current_token}"},
    )
    if response.status_code == 200:
        logger.info(f"Group {group_id} updated successfully.")
    else:
        logger.error(f"Error updating group {group_id}: {response.text}")
    return response


def delete_token(email, token_id, current_token):
    logger.info(f"Deleting token for user {email}.")
    user = find_user_by_email(email)
    user = convert_objectid_to_str(user.dict())
    logger.info(f"User: {user}")
    if user:
        logger.info(f"Deleting token for user {email}.")
        request_body = {"user": user, "token_id": token_id}
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/delete_token",
            json=request_body,
            headers={"Authorization": f"Bearer {current_token}"},
        )
        if response.status_code == 200:
            logger.info(f"Token deleted for user {email}.")
        else:
            logger.error(f"Error deleting token for user {email}: {response.text}")
        return response
    return None


def generate_agent_config(email, token, current_token):
    user = api_call_fetch_user_from_email(email)
    user = convert_objectid_to_str(user.model_dump())
    logger.info(f"User: {user}")

    token = convert_objectid_to_str(token)
    token = {
        "access_token": token["access_token"],
        "expire_datetime": token["expire_datetime"],
        "name": token["name"],
    }

    logger.info(f"Generating agent config for user {user}.")
    result = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/generate_agent_config",
        json={"user": user, "token": token},
        headers={"Authorization": f"Bearer {current_token}"},
    )
    # logger.info(f"Result: {result.json()}")
    if result.status_code == 200:
        logger.info(f"Agent config generated for user {user}.")
        return result.json()
    else:
        logger.error(f"Error generating agent config for user {user}: {result.text}")


@validate_call(config=dict(arbitrary_types_allowed=True), validate_return=True)
def api_get_project_from_id(project_id: PyObjectId, token: str) -> httpx.Response:
    """
    Get a project from the server using the project ID.
    """
    # First check if the project exists on the server DB for existing IDs and if the same metadata hash is used
    logger.info(f"Getting project with ID: {project_id}")
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
        params={"project_id": project_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    return response