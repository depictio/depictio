import os
import sys
from typing import Any

import httpx
from pydantic import EmailStr, validate_call

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.logging_init import format_pydantic, logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _hash_password
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.users import TokenBase, TokenData, User
from depictio.models.utils import convert_model_to_dict

# Check if running in a test environment
# First check environment variable, then check for pytest in sys.argv
is_testing = os.environ.get("DEV_MODE", "false").lower() == "true" or any(
    "pytest" in arg for arg in sys.argv
)

# Add a query parameter to API calls when in test mode to indicate test database should be used
API_QUERY_PARAMS = {"test_mode": "true"} if is_testing else {}


@validate_call(validate_return=True)
def api_call_register_user(
    email: EmailStr, password: str, group: str | None = None, is_admin: bool = False
) -> dict[str, Any] | None:
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

        # Convert boolean to string for is_admin
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/register",
            json=params,
        )
        # Sending parameters as URL query parameters to match the FastAPI endpoint signature
        # response = httpx.post(
        #     f"{API_BASE_URL}/depictio/api/v1/auth/register",
        #     params={"email": email, "password": password, "is_admin": str(is_admin)},
        # )
        if response.status_code == 200:
            logger.info("User registered successfully.")
            return dict(response.json())
        else:
            logger.error(f"Registration error: {response.text}")
            return None

    except Exception as e:
        logger.error(f"Registration exception: {str(e)}")
        return None


@validate_call(validate_return=True)
def api_call_fetch_user_from_token(token: str) -> User | None:
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
def api_call_fetch_user_from_email(email: EmailStr) -> User | None:
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
    logger.debug(f"Internal API Key: {settings.auth.internal_api_key}")

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_email",
        params={"email": email},
        headers={"api-key": settings.auth.internal_api_key},
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
def api_call_create_token(token_data: TokenData) -> dict[str, Any] | None:
    """
    Create a new token for a user by calling the API.

    Args:
        token_data: TokenData object containing token information

    Returns:
        Optional[Dict[str, Any]]: The response from the token creation or None if failed
    """
    logger.debug(f"Creating token: {format_pydantic(token_data)}")
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/create_token",
        json=convert_model_to_dict(token_data),
        headers={"api-key": settings.auth.internal_api_key},
    )

    if response.status_code == 200:
        logger.info("Token created successfully.")
        return dict(response.json())
    else:
        logger.error(f"Token creation error: {response.text}")
        return None


@validate_call(validate_return=True)
def purge_expired_tokens(token: str) -> dict[str, Any] | None:
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
            return dict(response.json())
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
        logger.debug("Token validity check successful.")
        validity = response.json()["success"]
        logger.debug(f"Token validity: {validity}")
        return validity
    else:
        logger.error(f"Error checking token validity: {response.text}")
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


def api_call_delete_token(token_id):
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/delete_token",
        params={"token_id": token_id},
        headers={"api-key": settings.auth.internal_api_key},
    )
    if response.status_code == 200:
        logger.info(f"Token {token_id} deleted successfully.")
        return True
    else:
        logger.error(f"Error deleting token {token_id}: {response.text}")
        return False


def api_call_list_tokens(
    current_token: str,
    token_lifetime: str | None = None,
) -> list | None:
    """
    List all tokens for the current user.

    Args:
        current_token: The current authentication token

    Returns:
        Response from the token listing or None if failed
    """
    if token_lifetime:
        params = {"token_lifetime": token_lifetime}
    else:
        params = {}

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/list_tokens",
        params=params,
        headers={"Authorization": f"Bearer {current_token}"},
    )
    if response.status_code == 200:
        logger.info("Tokens listed successfully.")
        tokens = response.json()
        if isinstance(tokens, list):
            return tokens
        else:
            logger.error(f"Expected list but got {type(tokens)}: {tokens}")
            return None
    else:
        logger.error(f"Error listing tokens: {response.text}")
        return None


def api_call_generate_agent_config(token: TokenData, current_token: str) -> dict[str, Any] | None:
    """
    Generate an agent configuration for a user with the given token.

    Args:
        token: The TokenData object
        current_token: The current authentication token

    Returns:
        Response from the agent config generation or None if failed
    """
    logger.info(f"Generating agent config for token: {token}")
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/generate_agent_config",
        json=convert_model_to_dict(token),
        headers={"Authorization": f"Bearer {current_token}"},
    )
    if response.status_code == 200:
        logger.info("Agent config generated successfully.")
        return dict(response.json())
    else:
        logger.error(f"Error generating agent config: {response.text}")
        return None


@validate_call(config=dict(arbitrary_types_allowed=True), validate_return=True)
def api_get_project_from_id(project_id: PyObjectId, token: str) -> httpx.Response:
    """
    Get a project from the server using the project ID.
    """
    # First check if the project exists on the server DB for existing IDs and if the same metadata hash is used
    logger.info(f"Getting project with ID: {project_id}")
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
        params={"project_id": convert_objectid_to_str(project_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    return response


@validate_call(validate_return=True)
def api_call_edit_password(
    old_password: str,
    new_password: str,
    access_token: str,
) -> dict[str, Any] | None:
    """
    Edit the password of a user by calling the API.
    Args:
        old_password: The old password
        new_password: The new password
        access_token: The user's access token
    Returns:
        Optional[Dict[str, Any]]: The response from the password edit or None if failed
    """
    old_password_hashed = _hash_password(old_password)
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/edit_password",
        json={
            "old_password": old_password_hashed,
            "new_password": new_password,
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code == 200:
        logger.info("Password edited successfully.")
        return dict(response.json())
    else:
        logger.error(f"Error editing password: {response.text}")
        return {
            "success": False,
            "message": f"Error editing password: {response.text}",
        }
