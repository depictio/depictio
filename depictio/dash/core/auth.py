"""
Authentication Module - Dash Frontend Authentication Processing.

This module handles authentication flow for the Dash frontend, including:
- Token validation and refresh logic
- Anonymous and temporary user session management
- Theme extraction from store data
- Pathname normalization for routing

The module supports three authentication modes:
1. Authenticated mode: Full user authentication with token validation
2. Unauthenticated mode: Anonymous user access with read-only permissions
3. Temporary user mode: Time-limited access for interactive features

All authentication state is managed through Dash's local storage mechanism.
"""

from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_create_temporary_user,
    api_call_get_anonymous_user_session,
    check_token_validity,
    refresh_access_token,
)
from depictio.dash.layouts.app_layout import handle_authenticated_user, handle_unauthenticated_user
from depictio.models.models.users import TokenBase


def _extract_theme(theme_store: dict[str, Any] | str | None) -> str:
    """
    Extract the theme value from theme store data.

    Args:
        theme_store: Theme store data, can be dict with colorScheme, string, or None.

    Returns:
        str: The theme value ("light" or "dark"), defaults to "light".
    """
    if theme_store is None:
        return "light"
    if isinstance(theme_store, dict):
        return str(theme_store.get("colorScheme", "light"))
    if isinstance(theme_store, str):
        return theme_store
    return "light"


def _normalize_pathname(pathname: str | None) -> str:
    """
    Normalize pathname, redirecting root and auth paths to /dashboards.

    Args:
        pathname: Current URL pathname, can be None.

    Returns:
        str: Normalized pathname, defaults to "/dashboards" for root paths.
    """
    if pathname is None or pathname == "/" or pathname == "/auth":
        logger.debug("Pathname is None or / - redirect to /dashboards")
        return "/dashboards"
    return pathname


def _validate_and_refresh_token(
    local_data: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Validate token and refresh if necessary.

    Args:
        local_data: Local storage data containing token information.

    Returns:
        Tuple of (updated_local_data, error_message).
        If validation succeeds, error_message is None.
        If validation fails, updated_local_data is None.
    """
    from datetime import datetime

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
        return (None, f"Missing required token fields: {missing_fields}")

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

        logger.debug(f"Token validation result: {validation_result}")

        # Handle different scenarios
        if validation_result["action"] == "valid":
            logger.debug("Access token valid - proceeding")
            return (local_data, None)

        elif validation_result["action"] == "refresh":
            logger.info("Access token expired but refresh token valid - attempting refresh")
            refreshed_data = refresh_access_token(local_data["refresh_token"])

            if refreshed_data:
                local_data.update(refreshed_data)
                logger.info("Token refreshed successfully")
                return (local_data, None)
            else:
                return (None, "Token refresh failed")

        elif validation_result["action"] == "logout":
            return (None, "Both access and refresh tokens expired/invalid")

        else:
            return (None, f"Unknown validation action: {validation_result['action']}")

    except Exception as e:
        return (None, f"Error in token validation: {e}")


def get_anonymous_user_session() -> dict[str, Any]:
    """
    Fetch the anonymous user session data using the API.

    Returns:
        dict: Session data compatible with authenticated user expectations
    """
    session_data = api_call_get_anonymous_user_session()
    if not session_data:
        raise Exception("Failed to fetch anonymous user session via API")

    return session_data


def get_temporary_user_session(expiry_hours: int = 24) -> dict[str, Any]:
    """
    Create a temporary user session with automatic expiration.

    Args:
        expiry_hours: Number of hours until the user expires (default: 24).

    Returns:
        dict: Session data for the temporary user.
    """
    session_data = api_call_create_temporary_user(expiry_hours=expiry_hours)
    if not session_data:
        raise Exception("Failed to create temporary user session via API")

    return session_data


def _has_valid_session(local_data: dict[str, Any] | None) -> bool:
    """Check if local_data contains a valid session."""
    return bool(local_data and local_data.get("access_token") and local_data.get("logged_in"))


def _handle_unauthenticated_mode(
    pathname: str | None,
    local_data: dict[str, Any] | None,
    theme: str,
    cached_project_data: dict[str, Any] | None,
    dashboard_init_data: dict[str, Any] | None,
) -> tuple:
    """
    Handle authentication when unauthenticated mode is enabled.

    Args:
        pathname: Current URL pathname.
        local_data: Local storage data containing authentication information.
        theme: Current theme setting.
        cached_project_data: Cached project data from consolidated API.
        dashboard_init_data: Consolidated dashboard initialization data.

    Returns:
        Tuple of (page_content, header, pathname, local_data).
    """
    # Check if we already have valid local_data (e.g. temporary user session)
    if _has_valid_session(local_data):
        try:
            normalized_pathname = _normalize_pathname(pathname)
            return handle_authenticated_user(
                normalized_pathname,
                local_data,
                theme,
                cached_project_data,
                dashboard_init_data,
            )
        except Exception as e:
            logger.error(f"Failed to handle existing session data: {e}")
            # Fall through to anonymous session

    # Create session based on auth mode
    normalized_pathname = _normalize_pathname(pathname)
    try:
        if settings.auth.is_public_mode and not settings.auth.is_single_user_mode:
            # Public/demo mode: auto-create temporary user so they can create dashboards
            logger.debug("Public mode - creating temporary user session")
            session_local_data = get_temporary_user_session(
                expiry_hours=settings.auth.temporary_user_expiry_hours,
            )
        else:
            # Single-user mode: use anonymous user (admin privileges)
            logger.debug("Single-user mode - fetching anonymous user session")
            session_local_data = get_anonymous_user_session()

        return handle_authenticated_user(
            normalized_pathname,
            session_local_data,
            theme,
            cached_project_data,
            dashboard_init_data,
        )
    except Exception as e:
        logger.error(f"Failed to create user session: {e}")
        return handle_unauthenticated_user(pathname)


def process_authentication(
    pathname: str | None,
    local_data: dict[str, Any] | None,
    theme_store: dict[str, Any] | str | None,
    cached_project_data: dict[str, Any] | None = None,
    dashboard_init_data: dict[str, Any] | None = None,
) -> tuple:
    """
    Process authentication with refresh token support.

    Handles three authentication modes:
    1. Unauthenticated mode: Uses anonymous or temporary user sessions
    2. Authenticated mode with valid token: Proceeds directly
    3. Authenticated mode with expired token: Attempts refresh before proceeding

    Performance optimizations:
    - Uses cached_project_data to avoid redundant API calls
    - Uses dashboard_init_data from consolidated /dashboards/init endpoint

    Args:
        pathname: Current URL pathname.
        local_data: Local storage data containing authentication information.
        theme_store: Theme store data from theme-store component.
        cached_project_data: Cached project data from consolidated API.
        dashboard_init_data: Consolidated dashboard initialization data.

    Returns:
        Tuple of (page_content, header, pathname, local_data).
    """
    theme = _extract_theme(theme_store)
    logger.info(f"AUTH CALLBACK - Theme: {theme}")

    # Handle unauthenticated mode (includes single-user mode and public mode)
    if settings.auth.requires_anonymous_user:
        logger.debug("Anonymous user mode is enabled (single-user or public mode)")
        return _handle_unauthenticated_mode(
            pathname, local_data, theme, cached_project_data, dashboard_init_data
        )

    # Authenticated mode: validate user is logged in
    if not _has_valid_session(local_data):
        logger.debug("User not logged in or no local data")
        return handle_unauthenticated_user(pathname)

    # Validate and refresh token
    updated_local_data, error = _validate_and_refresh_token(local_data)  # type: ignore
    if error or updated_local_data is None:
        logger.warning(error or "Token validation returned no data")
        return handle_unauthenticated_user(pathname)

    # Process authenticated user
    normalized_pathname = _normalize_pathname(pathname)
    logger.debug(f"Final pathname: {normalized_pathname}")
    logger.debug(f"Access Token: {updated_local_data['access_token'][:10]}...")

    return handle_authenticated_user(
        normalized_pathname,
        updated_local_data,
        theme,
        cached_project_data,
        dashboard_init_data,
    )
