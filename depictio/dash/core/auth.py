"""
Authentication handling for the Depictio Dash application.
"""

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import check_token_validity
from depictio.dash.layouts.app_layout import (handle_authenticated_user,
                                              handle_unauthenticated_user)
from depictio.models.models.users import TokenBase


def process_authentication(pathname, local_data):
    """
    Process authentication and return appropriate page content.

    Args:
        pathname (str): Current URL pathname
        local_data (dict): Local storage data containing authentication information

    Returns:
        tuple: (page_content, header, pathname, local_data)
    """
    # trigger = pathname  # For logging purposes
    logger.debug(f"URL Pathname: {pathname}")
    logger.debug(f"Local Data: {local_data}")

    # Check if user is authenticated
    if (
        not local_data
        or not local_data.get("logged_in")
        or not check_token_validity(TokenBase(**local_data))
    ):
        logger.debug("User not logged in")
        logger.debug("Redirect to /auth")
        return handle_unauthenticated_user(pathname)

    # Default to /dashboards if pathname is None or "/"
    if pathname is None or pathname == "/" or pathname == "/auth":
        logger.debug("Pathname is None or /")
        logger.debug("Redirect to /dashboards")
        pathname = "/dashboards"

    logger.debug(f"Pathname: {pathname}")
    logger.debug(f"Local Data: {local_data}")
    logger.debug(f"Access Token: {local_data['access_token']}")
    logger.debug(f"Logged In: {local_data['logged_in']}")
    logger.debug("HANDLE AUTHENTICATED USER")

    # Handle authenticated user logic
    return handle_authenticated_user(pathname, local_data)
