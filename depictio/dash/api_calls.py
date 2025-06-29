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
from depictio.models.models.users import TokenBase, TokenData, UserBaseUI
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
def api_call_fetch_user_from_token(token: str) -> UserBaseUI | None:
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
        timeout=settings.performance.api_request_timeout,
    )

    if response.status_code == 404:
        return None

    user_data = response.json()
    logger.debug(f"User data fetched from API: {user_data.get('email', 'No email found')}")

    if not user_data or "email" not in user_data:
        return None

    # Ensure all required fields are present with defaults
    user = UserBaseUI(
        email=user_data["email"],
        is_admin=user_data.get("is_admin", False),
        is_active=user_data.get("is_active", True),
        is_verified=user_data.get("is_verified", False),
        last_login=user_data.get("last_login"),
        registration_date=user_data.get("registration_date"),
        **{
            k: v
            for k, v in user_data.items()
            if k
            not in [
                "email",
                "is_admin",
                "is_active",
                "is_verified",
                "last_login",
                "registration_date",
            ]
        },
    )

    # Cache the result
    _user_cache[cache_key] = (user, current_time)

    # Clean old cache entries (simple cleanup)
    if len(_user_cache) > 100:  # Prevent memory buildup
        oldest_key = min(_user_cache.keys(), key=lambda k: _user_cache[k][1])
        del _user_cache[oldest_key]

    return user


@validate_call(validate_return=True)
def api_call_fetch_user_from_email(email: EmailStr) -> UserBaseUI | None:
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

    if not user_data or "email" not in user_data:
        return None

    # Ensure all required fields are present with defaults
    user = UserBaseUI(
        email=user_data["email"],
        is_admin=user_data.get("is_admin", False),
        is_active=user_data.get("is_active", True),
        is_verified=user_data.get("is_verified", False),
        last_login=user_data.get("last_login"),
        registration_date=user_data.get("registration_date"),
        **{
            k: v
            for k, v in user_data.items()
            if k
            not in [
                "email",
                "is_admin",
                "is_active",
                "is_verified",
                "last_login",
                "registration_date",
            ]
        },
    )

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


def api_call_create_temporary_user(expiry_hours: int = 24) -> dict[str, Any] | None:
    """
    Create a temporary user with automatic expiration.

    Args:
        expiry_hours: Number of hours until the user expires (default: 24)

    Returns:
        Session data for the temporary user or None if failed
    """
    try:
        logger.info(f"Creating temporary user with expiry: {expiry_hours} hours")

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/create_temporary_user",
            params={"expiry_hours": expiry_hours},
            headers={"api-key": settings.auth.internal_api_key},
            timeout=30.0,
        )

        if response.status_code == 200:
            session_data = response.json()
            logger.info("Successfully created temporary user session")
            return session_data
        else:
            logger.error(
                f"Failed to create temporary user: {response.status_code} - {response.text}"
            )
            return None

    except Exception as e:
        logger.error(f"Error creating temporary user: {e}")
        return None


def api_call_cleanup_expired_temporary_users() -> dict[str, Any] | None:
    """
    Clean up expired temporary users and their tokens.

    Returns:
        Cleanup results or None if failed
    """
    try:
        logger.info("Requesting cleanup of expired temporary users")

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/cleanup_expired_temporary_users",
            headers={"api-key": settings.auth.internal_api_key},
            timeout=30.0,
        )

        if response.status_code == 200:
            cleanup_results = response.json()
            logger.info(f"Cleanup completed: {cleanup_results}")
            return cleanup_results
        else:
            logger.error(
                f"Failed to cleanup temporary users: {response.status_code} - {response.text}"
            )
            return None

    except Exception as e:
        logger.error(f"Error cleaning up temporary users: {e}")
        return None


def api_call_upgrade_to_temporary_user(
    access_token: str, expiry_hours: int = 24, expiry_minutes: int = 0
) -> dict[str, Any] | None:
    """
    Upgrade from anonymous user to temporary user for interactive features.

    Args:
        access_token: Current user's access token
        expiry_hours: Number of hours until the temporary user expires (default: 24)
        expiry_minutes: Number of additional minutes until the temporary user expires (default: 0)

    Returns:
        Session data for the new temporary user or None if failed
    """
    try:
        logger.info(
            f"Upgrading to temporary user with expiry: {expiry_hours} hours, {expiry_minutes} minutes"
        )

        params = {"expiry_hours": expiry_hours}
        if expiry_minutes > 0:
            params["expiry_minutes"] = expiry_minutes

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/upgrade_to_temporary_user",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )

        if response.status_code == 200:
            session_data = response.json()
            logger.info("Successfully upgraded to temporary user")
            return session_data
        elif response.status_code == 400:
            logger.info("User is already a temporary user, no upgrade needed")
            return None
        else:
            logger.error(
                f"Failed to upgrade to temporary user: {response.status_code} - {response.text}"
            )
            return None

    except Exception as e:
        logger.error(f"Error upgrading to temporary user: {e}")
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


@validate_call(config=dict(arbitrary_types_allowed=True), validate_return=True)  # type: ignore[invalid-argument-type]
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
        timeout=settings.performance.api_request_timeout,
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


@validate_call(validate_return=True)
def api_call_get_dashboard(dashboard_id: str, token: str) -> dict[str, Any] | None:
    """
    Get dashboard data by calling the API.
    Uses environment-specific timeout settings.

    Args:
        dashboard_id: The dashboard ID
        token: The authentication token

    Returns:
        Optional[Dict[str, Any]]: Dashboard data or None if failed
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.performance.api_request_timeout,
        )
        response.raise_for_status()
        logger.debug(f"Dashboard data fetched successfully for dashboard {dashboard_id}.")
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to fetch dashboard data: {e}")
        return None


@validate_call(validate_return=True)
def api_call_save_dashboard(dashboard_id: str, dashboard_data: dict, token: str) -> bool:
    """
    Save dashboard data by calling the API.
    Uses environment-specific timeout settings.

    Args:
        dashboard_id: The dashboard ID
        dashboard_data: The dashboard data to save
        token: The authentication token

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}",
            json=dashboard_data,
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.performance.api_request_timeout,
        )
        response.raise_for_status()
        logger.info(f"Dashboard data saved successfully for dashboard {dashboard_id}.")
        return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to save dashboard data: {e}")
        return False


@validate_call(validate_return=True)
def api_call_screenshot_dashboard(dashboard_id: str) -> bool:
    """
    Request dashboard screenshot generation by calling the API.
    Uses generous timeout for screenshot generation to handle production complexity.

    Args:
        dashboard_id: The dashboard ID

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Use dedicated screenshot API timeout (configurable per environment)
        # Production environments need generous timeouts due to:
        # - Browser startup overhead
        # - Network latency for service communication
        # - Complex page rendering and content loading
        # - Screenshot capture and file I/O operations
        screenshot_timeout = settings.performance.screenshot_api_timeout

        logger.info(
            f"🎯 Screenshot API timeout set to {screenshot_timeout}s for production robustness"
        )

        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/utils/screenshot-dash-fixed/{dashboard_id}",
            timeout=screenshot_timeout,
        )

        if response.status_code == 200:
            logger.info("Dashboard screenshot saved successfully.")
            return True
        else:
            logger.warning(f"Failed to save dashboard screenshot: {response.json()}")
            return False
    except Exception as e:
        logger.error(f"Failed to save dashboard screenshot: {str(e)}")
        return False


def api_call_get_google_oauth_login_url() -> dict[str, Any] | None:
    """
    Get Google OAuth login URL from the API.

    Returns:
        Dictionary with authorization_url and state, or None if failed
    """
    try:
        logger.info("Getting Google OAuth login URL")

        with httpx.Client() as client:
            response = client.get(f"{API_BASE_URL}/depictio/api/v1/auth/google/login")

            if response.status_code == 200:
                oauth_data = response.json()
                logger.info("Successfully retrieved Google OAuth login URL")
                return oauth_data
            else:
                logger.error(
                    f"Failed to get Google OAuth login URL: {response.status_code} {response.text}"
                )
                return None

    except Exception as e:
        logger.error(f"Error getting Google OAuth login URL: {e}")
        return None


def api_call_handle_google_oauth_callback(code: str, state: str) -> dict[str, Any] | None:
    """
    Handle Google OAuth callback by calling the API.

    Args:
        code: Authorization code from Google
        state: State parameter for CSRF protection

    Returns:
        Dictionary with OAuth result, or None if failed
    """
    try:
        logger.info("Handling Google OAuth callback")

        with httpx.Client() as client:
            response = client.get(
                f"{API_BASE_URL}/depictio/api/v1/auth/google/callback",
                params={"code": code, "state": state},
            )

            if response.status_code == 200:
                oauth_result = response.json()
                logger.info("Google OAuth callback successful")
                return oauth_result
            else:
                logger.error(
                    f"Google OAuth callback failed: {response.status_code} {response.text}"
                )
                return None

    except Exception as e:
        logger.error(f"Error handling Google OAuth callback: {e}")
        return None
