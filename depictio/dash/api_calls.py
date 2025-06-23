import os
import sys
import time
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

# Simple cache for user data to reduce redundant API calls
_user_cache: dict[str, tuple[Any, float]] = {}
_cache_timeout = 30  # seconds


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

        # Create payload with parameters
        params = {"email": email, "password": password, "is_admin": is_admin}

        # Convert boolean to string for is_admin
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/register",
            json=params,
        )

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
    Synchronous version for Dash compatibility with caching to reduce redundant API calls.

    Args:
        token: The authentication token

    Returns:
        Optional[User]: The user if found, None otherwise
    """
    # Check cache first
    current_time = time.time()
    cache_key = f"user_token_{token}"

    if cache_key in _user_cache:
        cached_data, cache_time = _user_cache[cache_key]
        if current_time - cache_time < _cache_timeout:
            logger.debug("Returning cached user data")
            return cached_data

    # Make API call if not cached or expired
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
        params={"token": token},
        headers={"api-key": settings.auth.internal_api_key},
    )

    if response.status_code == 404:
        return None

    user_data = response.json()
    logger.debug(f"User data fetched from API: {user_data.get('email', 'No email found')}")

    if not user_data:
        return None

    user = User(**user_data)

    # Cache the result
    _user_cache[cache_key] = (user, current_time)

    # Clean old cache entries (simple cleanup)
    if len(_user_cache) > 100:  # Prevent memory buildup
        oldest_key = min(_user_cache.keys(), key=lambda k: _user_cache[k][1])
        del _user_cache[oldest_key]

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
    logger.debug(f"API internal key: {settings.auth.internal_api_key}")

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_email",
        params={"email": email},
        headers={"api-key": settings.auth.internal_api_key},
    )

    if response.status_code == 404:
        return None

    user_data = response.json()
    logger.debug(
        f"User data fetched: {user_data.get('email', 'No email found')} with ID {user_data.get('_id', 'No ID found')}"
    )

    if not user_data:
        return None

    user = User(**user_data)

    return user


@validate_call(validate_return=True)
def api_call_get_anonymous_user_session() -> dict | None:
    """
    Get the anonymous user session data for unauthenticated mode.
    Synchronous version for Dash compatibility.

    Returns:
        Optional[dict]: The session data if successful, None otherwise
    """
    logger.debug("Fetching anonymous user session via API")

    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/get_anonymous_user_session",
            headers={"api-key": settings.auth.internal_api_key},
            timeout=10,
        )

        if response.status_code == 200:
            session_data = response.json()
            logger.debug("Anonymous user session fetched successfully via API")
            return session_data
        elif response.status_code == 403:
            logger.warning("Anonymous user session not available - unauthenticated mode disabled")
            return None
        else:
            logger.error(
                f"Error fetching anonymous user session: {response.status_code} - {response.text}"
            )
            return None

    except Exception as e:
        logger.error(f"Exception during anonymous user session fetch: {e}")
        return None


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


# Helper function for refresh token API call
def refresh_access_token(refresh_token: str) -> dict | None:
    """
    Use refresh token to get new access token.

    Args:
        refresh_token: The refresh token

    Returns:
        dict: Updated token data or None if failed
    """
    try:
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/refresh_token",
            json={"refresh_token": refresh_token},
            headers={"api-key": settings.auth.internal_api_key},
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            logger.debug("Access token refreshed successfully")
            return {
                "access_token": data["access_token"],
                "expire_datetime": data["expire_datetime"],
            }
        else:
            logger.error(f"Token refresh failed with status {response.status_code}")
            return None

    except Exception as e:
        logger.error(f"Error during token refresh: {e}")
        return None


@validate_call(validate_return=True)
def check_token_validity(token: TokenBase) -> dict:
    """
    Enhanced token validity check that returns detailed status.

    Returns:
        dict: {
            "valid": bool,
            "can_refresh": bool,
            "action": str  # "valid", "refresh", "logout"
        }
    """
    logger.info("Checking token validity.")
    logger.info(
        f"Token with name: {token.name}, user_id: {token.user_id}, access_token: {token.access_token[:10]}..."
    )

    try:
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/check_token_validity",
            json=convert_model_to_dict(token),
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            result = {
                "valid": data.get("success", False),
                "can_refresh": data.get("can_refresh", False),
                "action": data.get("action", "logout"),
            }

            # logger.debug(f"Token validation result: {result['valid']}, can refresh: {result['can_refresh']}, action: {result['action']}")
            return result
        else:
            logger.error(f"Token validation failed with status {response.status_code}")
            return {"valid": False, "can_refresh": False, "action": "logout"}

    except Exception as e:
        logger.error(f"Error during token validation: {e}")
        return {"valid": False, "can_refresh": False, "action": "logout"}


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
    logger.info("Generating agent config")
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
