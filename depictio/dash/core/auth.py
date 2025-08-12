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


def get_anonymous_user_session():
    """
    Fetch the anonymous user session data using the API.

    Returns:
        dict: Session data compatible with authenticated user expectations
    """
    session_data = api_call_get_anonymous_user_session()
    if not session_data:
        raise Exception("Failed to fetch anonymous user session via API")

    return session_data


def get_temporary_user_session(expiry_hours: int = 24, expiry_minutes: int = 0):
    """
    Create a temporary user session with automatic expiration.

    Args:
        expiry_hours: Number of hours until the user expires (default: 24)

    Returns:
        dict: Session data for the temporary user
    """
    session_data = api_call_create_temporary_user(
        expiry_hours=expiry_hours,
        expiry_minutes=expiry_minutes,  # type: ignore[unknown-argument]
    )
    if not session_data:
        raise Exception("Failed to create temporary user session via API")

    return session_data


# Enhanced process_authentication with refresh logic
def process_authentication(pathname, local_data, theme_store):
    """
    Process authentication with refresh token support.

    Args:
        pathname (str): Current URL pathname
        local_data (dict): Local storage data containing authentication information
        theme_store: Theme store data from theme-store component

    Returns:
        tuple: (page_content, header, pathname, local_data)
    """
    # Extract theme from theme store properly
    theme = "light"  # Default theme
    if theme_store:
        if isinstance(theme_store, dict):
            theme = theme_store.get("colorScheme", "light")
        elif isinstance(theme_store, str):
            theme = theme_store

    # logger.info(f"AUTH CALLBACK - Theme Store: {theme_store} (type: {type(theme_store)})")
    # logger.info(f"AUTH CALLBACK - Extracted Theme: {theme}")
    # logger.info(f"AUTH CALLBACK - URL Pathname: {pathname}")
    # logger.info(
    #     f"AUTH CALLBACK - Local Data keys: {list(local_data.keys()) if local_data else None}"
    # )
    # logger.info("AUTH CALLBACK - Processing authentication...")

    # Check if unauthenticated mode is enabled
    if settings.auth.unauthenticated_mode:
        logger.debug("Unauthenticated mode is enabled")
        logger.debug(f"Local data received: {local_data}")
        logger.debug(f"Local data keys: {list(local_data.keys()) if local_data else 'None'}")

        # Check if we already have valid local_data (e.g. temporary user session or anonymous user)
        if local_data and local_data.get("access_token"):
            logger.debug(
                "Found existing session data in local store - using it instead of anonymous"
            )

            try:
                # If user has valid session data, they should be treated as authenticated
                # Check what type of user they are to determine proper behavior
                from depictio.dash.api_calls import api_call_fetch_user_from_token

                try:
                    user = api_call_fetch_user_from_token(local_data["access_token"])
                    if user:
                        # Check if user is on /auth with valid session
                        if pathname == "/auth":
                            if hasattr(user, "is_anonymous") and user.is_anonymous:
                                # Anonymous user on /auth - show login panel so they can upgrade
                                logger.debug(
                                    "Anonymous user on /auth - showing login panel for upgrade"
                                )
                                return handle_unauthenticated_user(pathname)
                            else:
                                # Real authenticated user on /auth - redirect to dashboards
                                logger.debug(
                                    "Real authenticated user on /auth - redirecting to /dashboards"
                                )
                                pathname = "/dashboards"
                    else:
                        # Invalid user token - redirect to auth
                        logger.debug("Invalid user token - redirecting to auth")
                        return handle_unauthenticated_user("/auth")
                except Exception as e:
                    logger.error(f"Error checking user in auth flow: {e}")
                    return handle_unauthenticated_user("/auth")

                # Default to /dashboards if pathname is None or "/"
                if pathname is None or pathname == "/":
                    logger.debug("Pathname is None or / - redirect to /dashboards")
                    pathname = "/dashboards"

                logger.debug("HANDLE AUTHENTICATED USER (EXISTING SESSION)")
                return handle_authenticated_user(pathname, local_data, theme)

            except Exception as e:
                logger.error(f"Failed to handle existing session data: {e}")
                # Fallback to unauthenticated user if session handling fails
                # Fetch the real anonymous user and their permanent token
                anonymous_local_data = get_anonymous_user_session()

                return handle_authenticated_user(pathname, anonymous_local_data, theme)

        else:
            logger.debug("No existing session data - fetching anonymous user session")
            try:
                # Fetch the real anonymous user and their permanent token
                anonymous_local_data = get_anonymous_user_session()

                # Check if anonymous user is on /auth - they want to login
                if pathname == "/auth":
                    logger.debug(
                        "Anonymous user on /auth - showing login panel with preserved session"
                    )
                    # Preserve anonymous session data for temporary user upgrade functionality
                    header = handle_unauthenticated_user(pathname)[
                        1
                    ]  # Get header from unauthenticated handler
                    return (
                        handle_unauthenticated_user(pathname)[0],  # Get page content
                        header,
                        "/auth",
                        anonymous_local_data,  # Keep the anonymous session data instead of wiping it
                    )

                # Default to /dashboards if pathname is None or "/"
                if pathname is None or pathname == "/":
                    logger.debug("Pathname is None or / - redirect to /dashboards")
                    pathname = "/dashboards"

                logger.debug("HANDLE AUTHENTICATED USER (ANONYMOUS MODE)")
                return handle_authenticated_user(pathname, anonymous_local_data, theme)

            except Exception as e:
                logger.error(f"Failed to fetch anonymous user session: {e}")
                # Fallback to unauthenticated user if anonymous user setup fails
                return handle_unauthenticated_user(pathname)

    # Basic validation for authenticated mode
    if not local_data or not local_data.get("logged_in"):
        logger.debug("User not logged in or no local data")
        return handle_unauthenticated_user(pathname)

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
        logger.warning(f"Missing required token fields: {missing_fields}")
        return handle_unauthenticated_user(pathname)

    try:
        from datetime import datetime
        # Create token object and validate
        # We've already validated that all required fields are present above

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
            # Access token is valid, continue normally
            logger.debug("Access token valid - proceeding")

        elif validation_result["action"] == "refresh":
            # Access token expired but refresh token valid
            logger.info("Access token expired but refresh token valid - attempting refresh")

            refreshed_data = refresh_access_token(local_data["refresh_token"])

            if refreshed_data:
                # Update local_data with new access token
                local_data.update(refreshed_data)
                logger.info("Token refreshed successfully")
                # Continue with updated token data
            else:
                logger.warning("Token refresh failed - redirecting to login")
                return handle_unauthenticated_user(pathname)

        elif validation_result["action"] == "logout":
            # Both tokens expired or invalid
            logger.warning("Both access and refresh tokens expired/invalid - forcing logout")
            return handle_unauthenticated_user(pathname)

        else:
            logger.error(f"Unknown validation action: {validation_result['action']}")
            return handle_unauthenticated_user(pathname)

    except Exception as e:
        logger.error(f"Error in token validation: {e}")
        return handle_unauthenticated_user(pathname)

    # At this point, user has valid tokens and has passed validation
    # The /auth handling was already done earlier in the flow, so no need to check again

    # Default to /dashboards if pathname is None or "/"
    if pathname is None or pathname == "/":
        logger.debug("Pathname is None or / - redirect to /dashboards")
        pathname = "/dashboards"

    logger.debug(f"Final pathname: {pathname}")
    logger.debug(f"Access Token: {local_data['access_token'][:10]}...")
    logger.debug("HANDLE AUTHENTICATED USER")

    return handle_authenticated_user(pathname, local_data, theme)
