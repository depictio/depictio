"""
Shared authentication module for multi-app Depictio architecture.

This module provides token validation and refresh logic that can be used
by all Dash apps (Management, Viewer, Editor) to ensure consistent
authentication handling.
"""

from datetime import datetime
from typing import Dict, Optional, Tuple

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_create_temporary_user,
    api_call_get_anonymous_user_session,
    check_token_validity,
    refresh_access_token,
)
from depictio.models.models.users import TokenBase


def get_anonymous_user_session() -> Dict:
    """
    Fetch the anonymous user session data using the API.

    Returns:
        dict: Session data compatible with authenticated user expectations

    Raises:
        Exception: If anonymous user session fetch fails
    """
    session_data = api_call_get_anonymous_user_session()
    if not session_data:
        raise Exception("Failed to fetch anonymous user session via API")

    return session_data


def get_temporary_user_session(expiry_hours: int = 24, expiry_minutes: int = 0) -> Dict:
    """
    Create a temporary user session with automatic expiration.

    Args:
        expiry_hours: Number of hours until the user expires (default: 24)
        expiry_minutes: Additional minutes until expiration

    Returns:
        dict: Session data for the temporary user

    Raises:
        Exception: If temporary user creation fails
    """
    session_data = api_call_create_temporary_user(
        expiry_hours=expiry_hours,
        expiry_minutes=expiry_minutes,  # type: ignore[unknown-argument]
    )
    if not session_data:
        raise Exception("Failed to create temporary user session via API")

    return session_data


def validate_and_refresh_token(local_data: Optional[Dict]) -> Tuple[Optional[Dict], bool, str]:
    """
    Validate authentication token and refresh if needed.

    This is the core authentication function used by all apps. It handles:
    1. Unauthenticated mode (anonymous users)
    2. Token validation
    3. Automatic token refresh
    4. Session validation

    Args:
        local_data: Local storage data containing authentication information

    Returns:
        tuple: (updated_local_data, is_authenticated, reason)
            - updated_local_data: Updated token data (may include refreshed token)
            - is_authenticated: Whether user is authenticated
            - reason: Human-readable reason for authentication status
                     ("valid", "refreshed", "anonymous", "no_session", "invalid_token", etc.)
    """
    # Handle unauthenticated mode
    if settings.auth.unauthenticated_mode:
        logger.debug("SHARED_AUTH: Unauthenticated mode is enabled")

        # Check if we already have valid local_data (e.g. temporary user session)
        if local_data and local_data.get("access_token") and local_data.get("logged_in"):
            logger.debug("SHARED_AUTH: Found existing session data in local store")
            return local_data, True, "existing_session"

        # Fetch anonymous user session
        try:
            logger.debug("SHARED_AUTH: No existing session - fetching anonymous user")
            anonymous_local_data = get_anonymous_user_session()
            return anonymous_local_data, True, "anonymous"
        except Exception as e:
            logger.error(f"SHARED_AUTH: Failed to fetch anonymous user session: {e}")
            return None, False, "anonymous_fetch_failed"

    # Authenticated mode validation
    if not local_data or not local_data.get("logged_in"):
        logger.debug("SHARED_AUTH: User not logged in or no local data")
        return None, False, "no_session"

    # Check required fields for refresh token model
    required_fields = [
        "user_id",
        "access_token",
        "refresh_token",
        "expire_datetime",
        "refresh_expire_datetime",
    ]
    missing_fields = [field for field in required_fields if field not in local_data]

    if missing_fields:
        logger.warning(f"SHARED_AUTH: Missing required token fields: {missing_fields}")
        return None, False, "missing_fields"

    try:
        # Convert datetime fields if they are strings
        expire_datetime = local_data["expire_datetime"]
        if isinstance(expire_datetime, str):
            expire_datetime = datetime.fromisoformat(expire_datetime.replace("Z", "+00:00"))

        refresh_expire_datetime = local_data["refresh_expire_datetime"]
        if isinstance(refresh_expire_datetime, str):
            refresh_expire_datetime = datetime.fromisoformat(
                refresh_expire_datetime.replace("Z", "+00:00")
            )

        # Create token with explicit field assignment
        token = TokenBase(
            user_id=local_data["user_id"],
            access_token=local_data["access_token"],
            refresh_token=local_data["refresh_token"],
            expire_datetime=expire_datetime,
            refresh_expire_datetime=refresh_expire_datetime,
            **{k: v for k, v in local_data.items() if k not in required_fields},
        )
        validation_result = check_token_validity(token)

        logger.debug(f"SHARED_AUTH: Token validation result: {validation_result}")

        # Handle different scenarios
        if validation_result["action"] == "valid":
            # Access token is valid, continue normally
            logger.debug("SHARED_AUTH: Access token valid - proceeding")
            return local_data, True, "valid"

        elif validation_result["action"] == "refresh":
            # Access token expired but refresh token valid
            logger.info(
                "SHARED_AUTH: Access token expired but refresh token valid - attempting refresh"
            )

            refreshed_data = refresh_access_token(local_data["refresh_token"])

            if refreshed_data:
                # Update local_data with new access token
                local_data.update(refreshed_data)
                logger.info("SHARED_AUTH: Token refreshed successfully")
                return local_data, True, "refreshed"
            else:
                logger.warning("SHARED_AUTH: Token refresh failed - forcing logout")
                return None, False, "refresh_failed"

        elif validation_result["action"] == "logout":
            # Both tokens expired or invalid
            logger.warning(
                "SHARED_AUTH: Both access and refresh tokens expired/invalid - forcing logout"
            )
            return None, False, "tokens_expired"

        else:
            logger.error(f"SHARED_AUTH: Unknown validation action: {validation_result['action']}")
            return None, False, "unknown_action"

    except Exception as e:
        logger.error(f"SHARED_AUTH: Error in token validation: {e}")
        return None, False, "validation_error"


def extract_theme_from_store(theme_store) -> str:
    """
    Extract theme string from theme store data.

    Args:
        theme_store: Theme store data (can be dict or string)

    Returns:
        str: Theme string ("light" or "dark")
    """
    theme = "light"  # Default theme
    if theme_store:
        if isinstance(theme_store, dict):
            theme = theme_store.get("colorScheme", "light")
        elif isinstance(theme_store, str):
            theme = theme_store

    return theme


def should_redirect_to_dashboards(pathname: Optional[str]) -> bool:
    """
    Check if pathname should redirect to /dashboards.

    Args:
        pathname: Current URL pathname

    Returns:
        bool: True if should redirect to /dashboards
    """
    return pathname is None or pathname in ("/", "/auth")


def get_access_token_from_local_data(local_data: Optional[Dict]) -> Optional[str]:
    """
    Safely extract access token from local data.

    Args:
        local_data: Local storage data

    Returns:
        str or None: Access token if available
    """
    if not local_data:
        return None

    return local_data.get("access_token")


def get_user_id_from_local_data(local_data: Optional[Dict]) -> Optional[str]:
    """
    Safely extract user ID from local data.

    Args:
        local_data: Local storage data

    Returns:
        str or None: User ID if available
    """
    if not local_data:
        return None

    return local_data.get("user_id")
