from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import check_token_validity, refresh_access_token
from depictio.dash.layouts.app_layout import handle_authenticated_user, handle_unauthenticated_user
from depictio.models.models.users import TokenBase


# Enhanced process_authentication with refresh logic
def process_authentication(pathname, local_data):
    """
    Process authentication with refresh token support.

    Args:
        pathname (str): Current URL pathname
        local_data (dict): Local storage data containing authentication information

    Returns:
        tuple: (page_content, header, pathname, local_data)
    """
    logger.debug(f"URL Pathname: {pathname}")
    logger.debug(f"Local Data keys: {list(local_data.keys()) if local_data else None}")
    logger.debug("Processing authentication...")

    # Basic validation
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
        # Create token object and validate
        token = TokenBase(**local_data)
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

    # Default to /dashboards if pathname is None or "/"
    if pathname is None or pathname == "/" or pathname == "/auth":
        logger.debug("Pathname is None or / - redirect to /dashboards")
        pathname = "/dashboards"

    logger.debug(f"Final pathname: {pathname}")
    logger.debug(f"Access Token: {local_data['access_token'][:10]}...")
    logger.debug("HANDLE AUTHENTICATED USER")

    # Handle authenticated user logic
    return handle_authenticated_user(pathname, local_data)
