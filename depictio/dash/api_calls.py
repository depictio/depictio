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
is_testing = os.environ.get("DEPICTIO_DEV_MODE", "false").lower() == "true" or any(
    "pytest" in arg for arg in sys.argv
)

# Add a query parameter to API calls when in test mode to indicate test database should be used
API_QUERY_PARAMS = {"test_mode": "true"} if is_testing else {}

# Simple cache for user data to reduce redundant API calls
_user_cache: dict[str, tuple[Any, float]] = {}
# Configurable cache timeout via environment variable (default 5 minutes)
_cache_timeout = int(os.getenv("DEPICTIO_USER_CACHE_TTL", "300"))  # seconds

# Minimalistic cache usage counters
_cache_stats = {
    "hits": 0,
    "misses": 0,
    "expirations": 0,
}

# Cache for token validity to eliminate API calls during routing
_token_validity_cache: dict[str, tuple[dict, float]] = {}
_validity_cache_timeout = 300  # 5 minutes

# Cache for token purge operations to avoid repeated calls
_token_purge_cache: dict[str, float] = {}
_purge_cache_timeout = 600  # 10 minutes


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

    Uses manual caching with configurable TTL (default 5 minutes) instead of @lru_cache
    to support cache expiration and prevent stale user data.

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
        cache_age = current_time - cache_time
        if cache_age < _cache_timeout:
            _cache_stats["hits"] += 1
            logger.info(
                f"🎯 CACHE HIT: user_token (age={cache_age:.1f}s, ttl={_cache_timeout}s, email={cached_data.email if cached_data else 'None'})"
            )
            return cached_data
        else:
            _cache_stats["expirations"] += 1
            logger.info(
                f"⏱️  CACHE EXPIRED: user_token (age={cache_age:.1f}s, ttl={_cache_timeout}s)"
            )
            # Remove expired entry
            del _user_cache[cache_key]

    # Make API call if not cached or expired
    _cache_stats["misses"] += 1
    logger.info(f"❌ CACHE MISS: user_token - fetching from API (cache_size={len(_user_cache)})")
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

    if not user_data:
        return None

    # Add default password since frontend doesn't receive actual password
    # user_data_with_password = {**user_data, "password": "$2b$12$dummy"}
    user = User(**user_data)  # type: ignore[misc]

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

    # Add default password since frontend doesn't receive actual password
    # user_data_with_password = {**user_data, "password": "$2b$12$dummy"}
    user = User(**user_data)  # type: ignore[misc]

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
    access_token: str, expiry_hours: int = 24
) -> dict[str, Any] | None:
    """
    Upgrade from anonymous user to temporary user for interactive features.

    Args:
        access_token: Current user's access token
        expiry_hours: Number of hours until the temporary user expires (default: 24)

    Returns:
        Session data for the new temporary user or None if failed
    """
    try:
        logger.info(f"Upgrading to temporary user with expiry: {expiry_hours} hours")

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/upgrade_to_temporary_user",
            params={"expiry_hours": expiry_hours},
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
    Purge expired tokens from the database with caching to avoid repeated calls.
    Args:
        token: The authentication token
    Returns:
        Optional[Dict[str, Any]]: The response from the purge operation
    """
    if not token:
        logger.error("Token not found.")
        return None

    # Check cache to avoid repeated purge calls
    cache_key = f"purge_{token[:10]}"  # Use token prefix for cache key
    current_time = time.time()

    if cache_key in _token_purge_cache:
        cache_time = _token_purge_cache[cache_key]
        if current_time - cache_time < _purge_cache_timeout:
            logger.debug("Skipping token purge - recently purged (cached)")
            return {"message": "Purge skipped - recently executed"}

    # Clean existing expired token from DB
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/purge_expired_tokens",
        headers={"Authorization": f"Bearer {token}"},
    )

    if response.status_code == 200:
        logger.info("Expired tokens purged successfully.")

        # Cache the purge operation
        _token_purge_cache[cache_key] = current_time

        # Clean old cache entries
        if len(_token_purge_cache) > 20:
            oldest_key = min(_token_purge_cache.keys(), key=lambda k: _token_purge_cache[k])
            del _token_purge_cache[oldest_key]

        return dict(response.json())
    else:
        logger.error(f"Error purging expired tokens: {response.text}")
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
    Enhanced token validity check that returns detailed status with caching to eliminate API calls during routing.

    Returns:
        dict: {
            "valid": bool,
            "can_refresh": bool,
            "action": str  # "valid", "refresh", "logout"
        }
    """
    # Create cache key from access token
    cache_key = f"token_validity_{token.access_token}"
    current_time = time.time()

    # Check cache first
    if cache_key in _token_validity_cache:
        cached_result, cache_time = _token_validity_cache[cache_key]
        if current_time - cache_time < _validity_cache_timeout:
            logger.debug("Returning cached token validity result")
            return cached_result

    logger.info("Checking token validity via API.")
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

            # Cache the result (only cache successful responses)
            _token_validity_cache[cache_key] = (result, current_time)

            # Clean old cache entries (simple cleanup)
            if len(_token_validity_cache) > 50:  # Prevent memory buildup
                oldest_key = min(
                    _token_validity_cache.keys(), key=lambda k: _token_validity_cache[k][1]
                )
                del _token_validity_cache[oldest_key]

            logger.debug(f"Token validation result cached: action={result['action']}")
            return result
        else:
            logger.error(f"Token validation failed with status {response.status_code}")
            failure_result = {"valid": False, "can_refresh": False, "action": "logout"}
            # Don't cache failure results as they might be temporary
            return failure_result

    except Exception as e:
        logger.error(f"Error during token validation: {e}")
        failure_result = {"valid": False, "can_refresh": False, "action": "logout"}
        # Don't cache exceptions as they might be temporary network issues
        return failure_result


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


def api_call_generate_agent_config(token: TokenBase, current_token: str) -> dict[str, Any] | None:
    """
    Generate an agent configuration for a user with the given token.

    Args:
        token: The TokenData object
        current_token: The current authentication token

    Returns:
        Response from the agent config generation or None if failed
    """
    logger.info("Generating CLI config")
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/auth/generate_agent_config",
        json=convert_model_to_dict(token),
        headers={"Authorization": f"Bearer {current_token}"},
    )
    if response.status_code == 200:
        logger.info("Agent config generated successfully.")
        return dict(response.json())
    else:
        logger.error(f"Error generating CLI config: {response.text}")
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
        dashboard_data = response.json()

        # Log what metadata is being received from the API
        # stored_metadata = dashboard_data.get("stored_metadata", [])
        # logger.info(f"📊 API LOAD DEBUG - Received {len(stored_metadata)} metadata items from API")
        # if stored_metadata:
        #     for i, elem in enumerate(stored_metadata[:2]):  # Only first 2 to avoid spam
        #         if elem:
        # logger.info(
        #     f"📊 API LOAD DEBUG - Metadata {i}: dict_kwargs={elem.get('dict_kwargs', 'MISSING')}"
        # )
        # logger.info(
        #     f"📊 API LOAD DEBUG - Metadata {i}: wf_id={elem.get('wf_id', 'MISSING')}"
        # )
        # logger.info(
        #     f"📊 API LOAD DEBUG - Metadata {i}: dc_id={elem.get('dc_id', 'MISSING')}"
        # )

        logger.debug(f"Dashboard data fetched successfully for dashboard {dashboard_id}.")
        return dashboard_data
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to fetch dashboard data: {e}")
        return None


@validate_call(validate_return=True)
def api_call_save_dashboard(
    dashboard_id: str, dashboard_data: dict, token: str, enrich: bool = False
) -> bool:
    """
    Save dashboard data by calling the API.
    Uses environment-specific timeout settings.

    Args:
        dashboard_id: The dashboard ID
        dashboard_data: The dashboard data to save
        token: The authentication token
        enrich: If True, enriches component metadata (slower). Default False for fast saves.
                Only manual user saves should pass enrich=True.

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Log what metadata is being sent to the API
        # stored_metadata = dashboard_data.get("stored_metadata", [])
        # logger.info(f"📊 API SAVE DEBUG - Sending {len(stored_metadata)} metadata items to API")
        # if stored_metadata:
        #     for i, elem in enumerate(stored_metadata[:2]):  # Only first 2 to avoid spam
        #         if elem:
        #             logger.info(
        #                 f"📊 API SAVE DEBUG - Metadata {i}: dict_kwargs={elem.get('dict_kwargs', 'MISSING')}"
        #             )
        #             logger.info(
        #                 f"📊 API SAVE DEBUG - Metadata {i}: wf_id={elem.get('wf_id', 'MISSING')}"
        #             )
        #             logger.info(
        #                 f"📊 API SAVE DEBUG - Metadata {i}: dc_id={elem.get('dc_id', 'MISSING')}"
        #             )

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}",
            params={"enrich": enrich},  # Pass enrichment flag to backend
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


@validate_call(validate_return=True)
def api_call_fetch_project_by_id(
    project_id: str, token: str, skip_enrichment: bool = False
) -> dict[str, Any] | None:
    """
    Fetch a specific project by ID.

    Args:
        project_id: Project ID to fetch
        token: Authentication token
        skip_enrichment: Skip delta_location aggregation pipeline (faster, safer for updates)

    Returns:
        Project data dictionary or None if not found
    """
    try:
        logger.debug(f"Fetching project by ID: {project_id} (skip_enrichment={skip_enrichment})")

        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
            headers={"Authorization": f"Bearer {token}"},
            params={"project_id": project_id, "skip_enrichment": skip_enrichment},
            timeout=settings.performance.api_request_timeout,
        )

        if response.status_code == 200:
            project_data = response.json()
            logger.debug(f"Project fetched successfully: {project_id}")
            return project_data
        elif response.status_code == 404:
            logger.debug(f"Project not found: {project_id}")
            return None
        else:
            logger.warning(f"Failed to fetch project {project_id}: {response.status_code}")
            return None

    except Exception as e:
        logger.error(f"Error fetching project {project_id}: {e}")
        return None


@validate_call(validate_return=True)
def api_call_fetch_delta_table_info(data_collection_id: str, token: str) -> dict[str, Any] | None:
    """
    Fetch delta table information for a specific data collection.

    Args:
        data_collection_id: Data collection ID
        token: Authentication token

    Returns:
        Delta table information or None if not found
    """
    try:
        logger.debug(f"Fetching delta table info for data collection: {data_collection_id}")

        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{data_collection_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.performance.api_request_timeout,
        )

        if response.status_code == 200:
            delta_info = response.json()
            logger.debug(f"Delta table info fetched successfully for {data_collection_id}")
            return delta_info
        elif response.status_code == 404:
            logger.debug(f"No delta table found for data collection {data_collection_id}")
            return None
        else:
            logger.warning(
                f"Failed to fetch delta table info for {data_collection_id}: {response.status_code}"
            )
            return None

    except Exception as e:
        logger.error(f"Error fetching delta table info for {data_collection_id}: {e}")
        return None


@validate_call(validate_return=True)
def api_call_create_project(project_data: dict[str, Any], token: str) -> dict[str, Any] | None:
    """
    Create a new project using the API endpoint.

    Args:
        project_data: Project data dictionary
        token: Authentication token

    Returns:
        Response from project creation or None if failed
    """
    try:
        logger.debug(f"Creating project: {project_data.get('name', 'Unknown')}")

        # Ensure datetime objects and ObjectIds are properly serialized
        from depictio.models.models.base import convert_objectid_to_str

        serialized_project_data = convert_objectid_to_str(project_data)

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/projects/create",
            json=serialized_project_data,
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.performance.api_request_timeout,
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(f"Project created successfully: {result.get('message', 'No message')}")
            return result
        else:
            error_msg = f"Failed to create project: {response.status_code} - {response.text}"
            logger.error(error_msg)
            try:
                error_data = response.json()
                return {
                    "success": False,
                    "message": error_data.get("message", error_msg),
                    "status_code": response.status_code,
                }
            except Exception:
                return {"success": False, "message": error_msg, "status_code": response.status_code}

    except Exception as e:
        logger.error(f"Error creating project: {e}")
        return {"success": False, "message": f"Network error: {str(e)}", "status_code": 500}


@validate_call(validate_return=True)
def api_call_update_project(project_data: dict[str, Any], token: str) -> dict[str, Any] | None:
    """
    Update an existing project using the API endpoint.

    Args:
        project_data: Project data dictionary
        token: Authentication token

    Returns:
        Response from project update or None if failed
    """
    try:
        logger.debug(f"Updating project: {project_data.get('name', 'Unknown')}")

        response = httpx.put(
            f"{API_BASE_URL}/depictio/api/v1/projects/update",
            json=project_data,
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.performance.api_request_timeout,
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(f"Project updated successfully: {result.get('message', 'No message')}")
            return result
        else:
            error_msg = f"Failed to update project: {response.status_code} - {response.text}"
            logger.error(error_msg)
            try:
                error_data = response.json()
                return {
                    "success": False,
                    "message": error_data.get("message", error_msg),
                    "status_code": response.status_code,
                }
            except Exception:
                return {"success": False, "message": error_msg, "status_code": response.status_code}

    except Exception as e:
        logger.error(f"Error updating project: {e}")
        return {"success": False, "message": f"Network error: {str(e)}", "status_code": 500}


@validate_call(validate_return=True)
def api_call_delete_project(project_id: str, token: str) -> dict[str, Any] | None:
    """
    Delete a project using the API endpoint.

    Args:
        project_id: Project ID to delete
        token: Authentication token

    Returns:
        Response from project deletion or None if failed
    """
    try:
        logger.debug(f"Deleting project: {project_id}")

        response = httpx.delete(
            f"{API_BASE_URL}/depictio/api/v1/projects/delete",
            params={"project_id": project_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.performance.api_request_timeout,
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(f"Project deleted successfully: {result.get('message', 'No message')}")
            return result
        else:
            error_msg = f"Failed to delete project: {response.status_code} - {response.text}"
            logger.error(error_msg)
            try:
                error_data = response.json()
                return {
                    "success": False,
                    "message": error_data.get("message", error_msg),
                    "status_code": response.status_code,
                }
            except Exception:
                return {"success": False, "message": error_msg, "status_code": response.status_code}

    except Exception as e:
        logger.error(f"Error deleting project: {e}")
        return {"success": False, "message": f"Network error: {str(e)}", "status_code": 500}


@validate_call(validate_return=True)
def api_call_create_data_collection(
    name: str,
    description: str,
    data_type: str,
    file_format: str,
    separator: str,
    custom_separator: str | None,
    compression: str,
    has_header: bool,
    file_contents: str,
    filename: str,
    project_id: str,
    token: str,
) -> dict[str, Any] | None:
    """
    Create a data collection by processing uploaded file.

    This function handles the complete data collection creation workflow:
    1. Validates and decodes the uploaded file
    2. Creates temporary storage for the file
    3. Builds polars configuration based on user selections
    4. Creates data collection and workflow models
    5. Processes the data using the existing CLI infrastructure
    6. Uploads processed data to S3/MinIO

    Args:
        name: Data collection name
        description: Data collection description
        data_type: Type of data (table, jbrowse2)
        file_format: File format (csv, tsv, parquet, etc.)
        separator: Field separator for delimited files
        custom_separator: Custom separator if separator="custom"
        compression: Compression format (none, gzip, zip, bz2)
        has_header: Whether file has header row
        file_contents: Base64 encoded file contents
        filename: Original filename
        project_id: Target project ID
        token: Authentication token

    Returns:
        Response with success/failure status and details
    """
    try:
        import base64
        import os
        import shutil
        import tempfile

        # Import required models and utilities
        from depictio.api.v1.configs.config import settings
        from depictio.cli.cli.utils.helpers import process_data_collection_helper
        from depictio.models.models.cli import CLIConfig, UserBaseCLIConfig
        from depictio.models.models.data_collections import (
            DataCollection,
            DataCollectionConfig,
            Scan,
            ScanSingle,
        )
        from depictio.models.models.data_collections_types.table import DCTableConfig
        from depictio.models.models.workflows import (
            Workflow,
            WorkflowConfig,
            WorkflowDataLocation,
            WorkflowEngine,
        )

        logger.info(f"Creating data collection: {name}")

        # Validate file size (5MB limit)
        try:
            _, content_string = file_contents.split(",")
            decoded = base64.b64decode(content_string)
            file_size = len(decoded)

            max_size = 5 * 1024 * 1024  # 5MB
            if file_size > max_size:
                return {
                    "success": False,
                    "message": f"File size ({file_size / (1024 * 1024):.1f}MB) exceeds 5MB limit",
                    "status_code": 400,
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Invalid file contents: {str(e)}",
                "status_code": 400,
            }

        # Get user information from token first
        current_user = api_call_fetch_user_from_token(token)
        if not current_user:
            return {
                "success": False,
                "message": "Invalid authentication token",
                "status_code": 401,
            }

        # Fetch current project (now that we have a valid token)
        # Use skip_enrichment=True to get complete workflow objects without aggregation pipeline
        project = api_call_fetch_project_by_id(project_id, token, skip_enrichment=True)
        if not project:
            return {
                "success": False,
                "message": f"Project {project_id} not found",
                "status_code": 404,
            }

        # Create temporary directory for the file
        temp_dir = tempfile.mkdtemp(prefix="depictio_upload_")
        temp_file_path = os.path.join(temp_dir, filename)

        try:
            # Save uploaded file
            with open(temp_file_path, "wb") as f:
                f.write(decoded)

            logger.info(f"Saved uploaded file to: {temp_file_path}")

            # Build polars kwargs based on user selections
            polars_kwargs = {}

            if file_format in ["csv", "tsv"]:
                # Determine separator
                if separator == "custom" and custom_separator:
                    polars_kwargs["separator"] = custom_separator
                elif separator == "\t":
                    polars_kwargs["separator"] = "\t"
                elif separator in [",", ";", "|"]:
                    polars_kwargs["separator"] = separator
                else:
                    polars_kwargs["separator"] = "," if file_format == "csv" else "\t"

                # Header handling
                polars_kwargs["has_header"] = has_header

            # Add compression if specified
            if compression != "none":
                polars_kwargs["compression"] = compression

            # Create data collection configuration
            dc_table_config = DCTableConfig(
                format=file_format,
                polars_kwargs=polars_kwargs,
                keep_columns=[],
                columns_description={},
            )

            scan_config = Scan(mode="single", scan_parameters=ScanSingle(filename=temp_file_path))

            dc_config = DataCollectionConfig(
                type=data_type,
                metatype="metadata",  # Always metadata for uploaded files
                scan=scan_config,
                dc_specific_properties=dc_table_config,
            )

            # Create the data collection
            data_collection = DataCollection(
                data_collection_tag=name,
                description=description,
                config=dc_config,
            )

            logger.info(f"Created data collection: {data_collection}")

            # Create a workflow to contain this data collection
            workflow_config = WorkflowConfig()

            workflow_data_location = WorkflowDataLocation(
                structure="flat",
                locations=[temp_dir],
            )

            # For Basic projects, create unique workflow tags to avoid duplicates
            # For Advanced projects, use the standard naming convention
            project_type = getattr(project, "project_type", "basic")

            if project_type == "basic":
                # Import time for unique timestamp
                import time

                timestamp = int(time.time() * 1000)  # milliseconds for uniqueness
                workflow_name = f"{name}_workflow_{timestamp}"
                workflow_tag = f"{name}_workflow_{timestamp}"
            else:
                # Advanced projects use standard naming
                workflow_name = f"{name}_workflow"
                workflow_tag = f"{name}_workflow"

            workflow = Workflow(
                name=workflow_name,
                engine=WorkflowEngine(name="python", version="3.12"),
                workflow_tag=workflow_tag,
                config=workflow_config,
                data_location=workflow_data_location,
                data_collections=[data_collection],
            )

            # Get the full token object from database (like the working sync_process_initial_data_collections does)
            import pymongo

            from depictio.api.v1.configs.config import MONGODB_URL
            from depictio.api.v1.configs.config import settings as api_settings

            # Connect to MongoDB to get full token object
            mongo_client = pymongo.MongoClient(MONGODB_URL)
            db = mongo_client[api_settings.mongodb.db_name]
            tokens_collection = db["tokens"]

            # Get the full token document for this user
            full_token = tokens_collection.find_one({"user_id": current_user.id})
            if not full_token:
                return {
                    "success": False,
                    "message": "Token not found in database",
                    "status_code": 401,
                }

            # Create CLI config for processing (using the same pattern as sync_process_initial_data_collections)
            cli_config = CLIConfig(
                user=UserBaseCLIConfig(
                    id=current_user.id,
                    email=current_user.email,
                    is_admin=current_user.is_admin,
                    token=full_token,  # Use the full token object from database
                ),
                api_base_url=settings.fastapi.url,
                s3_storage=settings.minio,
            )

            # Add the new workflow to the project BEFORE processing
            # This ensures the data collection is associated with the project during processing
            if hasattr(project, "model_dump"):
                # If project is a Pydantic model
                project_dict = project.model_dump()
            else:
                # If project is already a dict (from API)
                project_dict = project.copy()

            project_dict["workflows"].append(workflow.model_dump())

            # Update the project via API
            update_result = api_call_update_project(project_dict, token)
            if not update_result or not update_result.get("success"):
                return {
                    "success": False,
                    "message": f"Failed to add data collection to project: {update_result.get('message', 'Unknown error') if update_result else 'API call failed'}",
                    "status_code": 500,
                }

            logger.info("Data collection added to project successfully!")

            # Process the data collection using existing CLI infrastructure
            logger.info("Starting data collection processing...")

            # First scan the files
            scan_result = process_data_collection_helper(
                CLI_config=cli_config,
                wf=workflow,
                dc_id=str(data_collection.id),
                mode="scan",
            )

            logger.info(f"Scan result: {scan_result}")

            if scan_result.get("result") != "success":
                return {
                    "success": False,
                    "message": f"File scanning failed: {scan_result.get('message', 'Unknown error')}",
                    "status_code": 500,
                }

            # Then process the data
            process_result = process_data_collection_helper(
                CLI_config=cli_config,
                wf=workflow,
                dc_id=str(data_collection.id),
                mode="process",
                command_parameters={"overwrite": True},
            )

            logger.info(f"Process result: {process_result}")

            if process_result.get("result") != "success":
                return {
                    "success": False,
                    "message": f"Data processing failed: {process_result.get('message', 'Unknown error')}",
                    "status_code": 500,
                }

            logger.info("Data collection created and processed successfully!")

            return {
                "success": True,
                "message": f"Data collection '{name}' created and processed successfully",
                "data_collection_id": str(data_collection.id),
                "workflow_id": str(workflow.id),
            }

        finally:
            # Always cleanup temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Cleaned up temporary directory: {temp_dir}")

    except Exception as e:
        logger.error(f"Error creating data collection: {str(e)}")
        import traceback

        traceback.print_exc()
        return {
            "success": False,
            "message": f"Internal error: {str(e)}",
            "status_code": 500,
        }


@validate_call(validate_return=True)
def api_call_edit_data_collection_name(
    data_collection_id: str, new_name: str, token: str
) -> dict[str, Any] | None:
    """
    Edit the name of a data collection.

    Args:
        data_collection_id: ID of the data collection to rename
        new_name: New name for the data collection
        token: Authorization token

    Returns:
        Dict with success status and message
    """
    try:
        url = f"{settings.fastapi.url}/depictio/api/v1/datacollections/{data_collection_id}/name"
        headers = {"Authorization": f"Bearer {token}"}
        data = {"new_name": new_name}

        logger.info(f"Updating data collection name: {data_collection_id} -> {new_name}")

        response = httpx.put(url, headers=headers, json=data, timeout=30.0)
        response.raise_for_status()

        result = response.json()
        logger.info(f"Data collection name updated successfully: {result}")
        return {"success": True, "message": "Data collection name updated successfully"}

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error updating data collection name: {e.response.status_code}")
        try:
            error_detail = e.response.json().get("detail", str(e))
        except Exception:
            error_detail = str(e)
        return {"success": False, "message": f"API error: {error_detail}"}
    except Exception as e:
        logger.error(f"Error updating data collection name: {str(e)}")
        return {"success": False, "message": f"Internal error: {str(e)}"}


@validate_call(validate_return=True)
def api_call_delete_data_collection(data_collection_id: str, token: str) -> dict[str, Any] | None:
    """
    Delete a data collection and all associated data.

    Args:
        data_collection_id: ID of the data collection to delete
        token: Authorization token

    Returns:
        Dict with success status and message
    """
    try:
        url = f"{settings.fastapi.url}/depictio/api/v1/datacollections/{data_collection_id}"
        headers = {"Authorization": f"Bearer {token}"}

        logger.info(f"Deleting data collection: {data_collection_id}")

        response = httpx.delete(url, headers=headers, timeout=60.0)
        response.raise_for_status()

        result = response.json()
        logger.info(f"Data collection deleted successfully: {result}")
        return {"success": True, "message": "Data collection deleted successfully"}

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error deleting data collection: {e.response.status_code}")
        try:
            error_detail = e.response.json().get("detail", str(e))
        except Exception:
            error_detail = str(e)
        return {"success": False, "message": f"API error: {error_detail}"}
    except Exception as e:
        logger.error(f"Error deleting data collection: {str(e)}")
        return {"success": False, "message": f"Internal error: {str(e)}"}


@validate_call(validate_return=True)
def api_call_overwrite_data_collection(
    data_collection_id: str,
    file_contents: str,
    filename: str,
    token: str,
    file_format: str = "csv",
    separator: str = ",",
    compression: str = "none",
    has_header: bool = True,
) -> dict[str, Any] | None:
    """
    Overwrite a data collection with new file data after schema validation.

    Args:
        data_collection_id: ID of the data collection to overwrite
        file_contents: Base64 encoded file contents
        filename: Name of the uploaded file
        token: Authorization token
        file_format: Format of the file (csv, tsv, etc.)
        separator: Field separator for delimited files
        compression: Compression format
        has_header: Whether file has header row

    Returns:
        Dict with success status and message
    """
    import base64
    import shutil
    import tempfile
    from pathlib import Path

    import polars as pl
    import pymongo
    from bson import ObjectId

    from depictio.api.v1.configs.config import MONGODB_URL, settings
    from depictio.models.models.projects import Project

    temp_dir = None
    try:
        # Create temporary directory for file processing
        temp_dir = tempfile.mkdtemp()
        logger.info(f"Created temporary directory: {temp_dir}")

        # Decode and save the uploaded file
        file_data = base64.b64decode(file_contents.split(",")[1])
        temp_file_path = Path(temp_dir) / filename

        with open(temp_file_path, "wb") as f:
            f.write(file_data)

        logger.info(f"Saved file to: {temp_file_path}")

        # Get existing data collection schema using the specs endpoint
        try:
            import httpx

            # Get user token for API call
            current_user = api_call_fetch_user_from_token(token)
            if not current_user:
                return {"success": False, "message": "Invalid authentication token"}

            # Call the specs endpoint to get data collection metadata
            specs_url = (
                f"{settings.fastapi.url}/depictio/api/v1/datacollections/specs/{data_collection_id}"
            )
            headers = {"Authorization": f"Bearer {token}"}

            logger.info(f"Fetching data collection specs from: {specs_url}")
            response = httpx.get(specs_url, headers=headers, timeout=30.0)
            response.raise_for_status()

            existing_dc = response.json()
            logger.info(
                f"Retrieved data collection specs: {existing_dc.get('data_collection_tag', 'unknown')}"
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"success": False, "message": "Data collection not found"}
            else:
                return {
                    "success": False,
                    "message": f"Failed to retrieve data collection info: {e.response.status_code}",
                }
        except Exception as e:
            logger.error(f"Error fetching data collection specs: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to retrieve data collection info: {str(e)}",
            }

        # Get existing schema from delta table metadata or read from actual delta table
        existing_schema = existing_dc.get("delta_table_schema")

        # If no stored schema, try to read it from the actual Delta table
        if not existing_schema:
            try:
                # Construct S3 path for the Delta table
                s3_path = f"s3://{settings.minio.bucket}/{data_collection_id}"

                # Configure S3 storage options for reading Delta table
                storage_options = {
                    "AWS_ENDPOINT_URL": settings.minio.url,
                    "AWS_ACCESS_KEY_ID": settings.minio.root_user,
                    "AWS_SECRET_ACCESS_KEY": settings.minio.root_password,
                    "AWS_REGION": "us-east-1",
                    "AWS_ALLOW_HTTP": "true",
                    "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
                }

                # Read a small sample to get schema
                logger.info(f"Reading schema from Delta table at: {s3_path}")
                df_sample = pl.read_delta(s3_path, storage_options=storage_options).limit(1)

                # Build schema dictionary from DataFrame
                existing_schema = {}
                for col_name in df_sample.columns:
                    col_type = str(df_sample[col_name].dtype)
                    existing_schema[col_name] = {"type": col_type}

                logger.info(f"Retrieved schema from Delta table: {existing_schema}")

            except Exception as e:
                logger.warning(f"Could not read schema from Delta table: {str(e)}")
                return {
                    "success": False,
                    "message": f"Cannot validate schema: unable to retrieve existing data collection schema ({str(e)})",
                }

        # Build polars kwargs for file reading
        polars_kwargs = {"has_header": has_header}

        if file_format in ["csv", "tsv"]:
            polars_kwargs["separator"] = separator
        if compression != "none":
            polars_kwargs["compression"] = compression

        # Read and validate new file schema
        try:
            if file_format == "csv" or file_format == "tsv":
                df = pl.read_csv(temp_file_path, **polars_kwargs)
            elif file_format == "parquet":
                df = pl.read_parquet(temp_file_path)
            elif file_format == "feather":
                df = pl.read_ipc(temp_file_path)
            elif file_format in ["xls", "xlsx"]:
                df = pl.read_excel(temp_file_path, **polars_kwargs)
            else:
                return {"success": False, "message": f"Unsupported file format: {file_format}"}

            logger.info(f"Read file with shape: {df.shape}")

        except Exception as e:
            return {"success": False, "message": f"Failed to read file: {str(e)}"}

        # Validate schema matches existing data collection
        # Exclude system-generated columns from comparison
        system_columns = {"depictio_run_id", "aggregation_time"}
        new_columns = set(df.columns)
        existing_columns = (
            set(existing_schema.keys()) if isinstance(existing_schema, dict) else set()
        )

        # Remove system columns from existing schema for comparison
        existing_user_columns = existing_columns - system_columns

        if new_columns != existing_user_columns:
            missing_cols = existing_user_columns - new_columns
            extra_cols = new_columns - existing_user_columns
            error_msg = "Schema mismatch: "
            if missing_cols:
                error_msg += f"Missing columns: {list(missing_cols)}. "
            if extra_cols:
                error_msg += f"Extra columns: {list(extra_cols)}. "
            return {"success": False, "message": error_msg}

        # Validate column types if possible
        try:
            for col in df.columns:
                new_type = str(df[col].dtype)
                existing_type = (
                    existing_schema.get(col, {}).get("type")
                    if isinstance(existing_schema, dict)
                    else None
                )

                # Basic type compatibility check
                if existing_type and not _are_types_compatible(new_type, existing_type):
                    logger.warning(
                        f"Type mismatch for column '{col}': new={new_type}, existing={existing_type}"
                    )
                    # Don't fail on type mismatch, just warn - polars can handle most conversions

        except Exception as e:
            logger.warning(f"Could not validate column types: {e}")

        # Proceed with overwrite - reuse existing data collection processing logic
        # Connect to MongoDB for token lookup
        client = pymongo.MongoClient(MONGODB_URL)
        db = client[settings.mongodb.db_name]
        tokens_collection = db["tokens"]
        users_collection = db["users"]

        # Get admin user and token for CLI processing
        admin_user = users_collection.find_one({"is_admin": True})
        if not admin_user:
            return {"success": False, "message": "No admin user found"}

        token_doc = tokens_collection.find_one({"user_id": admin_user["_id"]})
        if not token_doc:
            return {"success": False, "message": "No admin token found"}

        # Get the project containing this data collection
        projects_collection = db["projects"]
        project = projects_collection.find_one(
            {"workflows.data_collections._id": ObjectId(data_collection_id)}
        )
        if not project:
            return {"success": False, "message": "Project not found"}

        project_obj = Project.from_mongo(project)

        # Find the workflow containing this data collection
        target_workflow = None
        for workflow in project_obj.workflows:
            for dc in workflow.data_collections:
                if str(dc.id) == data_collection_id:
                    target_workflow = workflow
                    break
            if target_workflow:
                break

        if not target_workflow:
            return {"success": False, "message": "Parent workflow not found"}

        # For overwrite, directly write to Delta table instead of using CLI processing pipeline
        # This avoids issues with existing file metadata and scan configurations

        try:
            # Prepare the new dataframe with system columns for Delta table
            # Add system columns that are expected in the Delta table
            from datetime import datetime

            # Get the data collection for run_tag
            target_dc = None
            for dc in target_workflow.data_collections:
                if str(dc.id) == data_collection_id:
                    target_dc = dc
                    break

            if not target_dc:
                return {"success": False, "message": "Target data collection not found in workflow"}

            # Add system columns to match existing Delta table schema
            df_with_system_cols = df.with_columns(
                [
                    pl.lit(f"{target_dc.data_collection_tag}-overwrite").alias("depictio_run_id"),
                    pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")).alias("aggregation_time"),
                ]
            )

            # Construct S3 path for the Delta table
            s3_path = f"s3://{settings.minio.bucket}/{data_collection_id}"

            # Configure S3 storage options for writing Delta table
            storage_options = {
                "AWS_ENDPOINT_URL": settings.minio.url,
                "AWS_ACCESS_KEY_ID": settings.minio.root_user,
                "AWS_SECRET_ACCESS_KEY": settings.minio.root_password,
                "AWS_REGION": "us-east-1",
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }

            logger.info(f"Overwriting Delta table at: {s3_path}")
            logger.info(f"New data shape: {df_with_system_cols.shape}")

            # Write the new data to Delta table (overwrite mode)
            df_with_system_cols.write_delta(
                target=s3_path,
                mode="overwrite",  # This completely replaces the existing data
                storage_options=storage_options,
            )

            logger.info("Data collection overwrite completed successfully")
            return {
                "success": True,
                "message": f"Data collection overwritten successfully with {df.shape[0]} rows",
            }

        except Exception as e:
            logger.error(f"Failed to write to Delta table: {str(e)}")
            return {"success": False, "message": f"Failed to overwrite data: {str(e)}"}

    except Exception as e:
        logger.error(f"Error overwriting data collection: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "message": f"Internal error: {str(e)}"}

    finally:
        # Always cleanup temp directory
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Cleaned up temporary directory: {temp_dir}")


def _are_types_compatible(new_type: str, existing_type: str) -> bool:
    """Check if two data types are compatible for schema validation."""
    # Basic type compatibility mapping
    numeric_types = ["Int64", "Float64", "Int32", "Float32", "int", "float", "numeric"]
    string_types = ["Utf8", "String", "str", "string", "text"]
    boolean_types = ["Boolean", "bool", "boolean"]
    date_types = ["Date", "Datetime", "date", "datetime", "timestamp"]

    # Normalize type names
    new_type_lower = new_type.lower()
    existing_type_lower = existing_type.lower()

    # Check if both are in the same type family
    for type_family in [numeric_types, string_types, boolean_types, date_types]:
        if new_type_lower in [t.lower() for t in type_family] and existing_type_lower in [
            t.lower() for t in type_family
        ]:
            return True

    return False


@validate_call(validate_return=True)
def api_call_check_project_permission(
    project_id: str,
    token: str,
    required_permission: str = "editor",
) -> bool:
    """
    Check if the current user has required permission on a project.

    This function provides defense-in-depth permission checking for dashboard
    operations at the Dash callback layer, complementing the API-level checks.

    Args:
        project_id: The project ID to check permissions for
        token: Authentication token
        required_permission: Required permission level ("owner", "editor", or "viewer")

    Returns:
        bool: True if user has required permission or project is public, False otherwise

    Example:
        >>> has_permission = api_call_check_project_permission(
        ...     project_id="507f1f77bcf86cd799439011",
        ...     token=user_token,
        ...     required_permission="editor"
        ... )
        >>> if not has_permission:
        ...     logger.warning("User attempted unauthorized edit")
        ...     raise PreventUpdate  # Block the operation
    """
    try:
        logger.debug(f"Checking {required_permission} permission for project {project_id}")

        # Get current user from token
        current_user = api_call_fetch_user_from_token(token)
        if not current_user:
            logger.warning("Invalid token - permission denied")
            return False

        # Admin users have all permissions
        if current_user.is_admin:
            logger.debug(f"Admin user {current_user.email} - permission granted")
            return True

        # Fetch project data to check permissions
        project = api_call_fetch_project_by_id(project_id, token)
        if not project:
            logger.warning(f"Project {project_id} not found")
            return False

        # Check if project is public (viewers only)
        if required_permission == "viewer" and project.get("is_public", False):
            logger.debug("Public project - viewer permission granted")
            return True

        # Get permissions from project
        permissions = project.get("permissions", {})
        user_id_str = str(current_user.id)

        # Check based on required permission level
        if required_permission == "owner":
            # Only owners can perform owner-level actions
            owner_ids = [
                str(owner.get("id", owner.get("_id", "")))
                for owner in permissions.get("owners", [])
            ]
            has_permission = user_id_str in owner_ids

        elif required_permission == "editor":
            # Editors and owners can perform editor-level actions
            owner_ids = [
                str(owner.get("id", owner.get("_id", "")))
                for owner in permissions.get("owners", [])
            ]
            editor_ids = [
                str(editor.get("id", editor.get("_id", "")))
                for editor in permissions.get("editors", [])
            ]
            has_permission = user_id_str in owner_ids or user_id_str in editor_ids

        else:  # viewer
            # Viewers, editors, and owners can perform viewer-level actions
            owner_ids = [
                str(owner.get("id", owner.get("_id", "")))
                for owner in permissions.get("owners", [])
            ]
            editor_ids = [
                str(editor.get("id", editor.get("_id", "")))
                for editor in permissions.get("editors", [])
            ]
            viewer_ids = [
                str(viewer.get("id", viewer.get("_id", "")))
                for viewer in permissions.get("viewers", [])
                if isinstance(viewer, dict)
            ]
            has_wildcard = "*" in permissions.get("viewers", [])
            has_permission = (
                user_id_str in owner_ids
                or user_id_str in editor_ids
                or user_id_str in viewer_ids
                or has_wildcard
            )

        if has_permission:
            logger.debug(
                f"User {current_user.email} has {required_permission} permission on project {project_id}"
            )
        else:
            logger.warning(
                f"User {current_user.email} lacks {required_permission} permission on project {project_id}"
            )

        return has_permission

    except Exception as e:
        logger.error(f"Error checking project permission: {e}")
        # Fail secure - deny permission on error
        return False


@validate_call(validate_return=True)
def api_call_fetch_multiqc_report(data_collection_id: str, token: str) -> dict[str, Any] | None:
    """
    Fetch MultiQC report metadata for a specific data collection.

    Args:
        data_collection_id: Data collection ID to fetch MultiQC report for
        token: Authentication token

    Returns:
        MultiQC report metadata or None if not found
    """
    try:
        logger.debug(f"Fetching MultiQC report for data collection: {data_collection_id}")

        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/multiqc/{data_collection_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.performance.api_request_timeout,
        )

        if response.status_code == 200:
            multiqc_data = response.json()
            logger.debug(f"MultiQC report fetched successfully for {data_collection_id}")
            return multiqc_data
        elif response.status_code == 404:
            logger.debug(f"No MultiQC report found for data collection {data_collection_id}")
            return None
        else:
            logger.warning(
                f"Failed to fetch MultiQC report for {data_collection_id}: {response.status_code}"
            )
            return None

    except Exception as e:
        logger.error(f"Error fetching MultiQC report for {data_collection_id}: {e}")
        return None
