"""
Google OAuth authentication endpoints for Depictio.

This module implements Google OAuth 2.0 authentication flow including:
- OAuth login initiation
- OAuth callback handling
- User registration/login via Google account
"""

from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.auth_endpoints.utils import (
    cleanup_expired_states,
    create_or_get_user,
    exchange_code_for_token,
    fetch_google_user_info,
    generate_oauth_state,
    validate_oauth_state,
)
from depictio.api.v1.endpoints.user_endpoints.core_functions import _add_token
from depictio.models.models.google_oauth import (
    GoogleOAuthLoginResponse,
    GoogleOAuthResponse,
)
from depictio.models.models.users import TokenData

# Router for Google OAuth endpoints
google_oauth_router = APIRouter()


@google_oauth_router.get("/login", response_model=GoogleOAuthLoginResponse)
async def google_oauth_login() -> GoogleOAuthLoginResponse:
    """
    Initiate Google OAuth login flow.

    Returns:
        GoogleOAuthLoginResponse: Contains authorization URL and state parameter
    """
    # Check if Google OAuth is enabled
    if not settings.auth.google_oauth_enabled:
        raise HTTPException(status_code=403, detail="Google OAuth is not enabled")

    # Validate OAuth configuration
    if not all(
        [
            settings.auth.google_oauth_client_id,
            settings.auth.google_oauth_client_secret,
            settings.auth.google_oauth_redirect_uri,
        ]
    ):
        raise HTTPException(status_code=500, detail="Google OAuth configuration incomplete")

    # Clean up expired states
    cleanup_expired_states()

    # Generate state parameter for CSRF protection
    state = generate_oauth_state()

    # Build Google OAuth authorization URL
    auth_params = {
        "client_id": settings.auth.google_oauth_client_id,
        "redirect_uri": settings.auth.google_oauth_redirect_uri,
        "scope": "openid email profile",
        "response_type": "code",
        "state": state,
        "access_type": "offline",  # Request refresh token
        "prompt": "consent",  # Force consent screen for refresh token
    }

    authorization_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(auth_params)}"

    logger.info(f"Generated OAuth login URL with state: {state}")

    return GoogleOAuthLoginResponse(authorization_url=authorization_url, state=state)


@google_oauth_router.get("/callback", response_model=GoogleOAuthResponse)
async def google_oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    error: str | None = Query(None, description="Error parameter if OAuth failed"),
) -> GoogleOAuthResponse:
    """
    Handle Google OAuth callback and complete authentication.

    Args:
        code: Authorization code from Google OAuth
        state: State parameter for CSRF protection
        error: Error parameter if OAuth failed

    Returns:
        GoogleOAuthResponse: Contains authentication result and user/token data
    """
    # Check if Google OAuth is enabled
    if not settings.auth.google_oauth_enabled:
        raise HTTPException(status_code=403, detail="Google OAuth is not enabled")

    # Handle OAuth errors
    if error:
        logger.warning(f"OAuth callback received error: {error}")
        raise HTTPException(status_code=400, detail=f"OAuth authentication failed: {error}")

    # Validate required parameters
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Validate state parameter (CSRF protection)
    if not validate_oauth_state(state):
        logger.warning(f"Invalid or expired OAuth state: {state}")
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter")

    try:
        # Step 1: Exchange authorization code for access token
        logger.info("Exchanging authorization code for access token")
        token_data = await exchange_code_for_token(code)

        # Step 2: Fetch user information from Google
        logger.info("Fetching user information from Google")
        google_user = await fetch_google_user_info(token_data["access_token"])

        # Step 3: Create or get existing user
        logger.info(f"Processing user: {google_user.email}")
        user, user_created = await create_or_get_user(google_user)

        # Step 4: Create authentication token for the user
        logger.info(f"Creating authentication token for user: {user.id}")
        token_name = f"google_oauth_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        token_data_obj = TokenData(name=token_name, token_lifetime="short-lived", sub=user.id)

        auth_token = await _add_token(token_data_obj)

        if not auth_token:
            logger.error("Failed to create authentication token")
            raise HTTPException(status_code=500, detail="Failed to create authentication token")

        # Prepare response
        response_data = GoogleOAuthResponse(
            success=True,
            message="OAuth login successful",
            user_created=user_created,
            user={
                "id": str(user.id),
                "email": user.email,
                "is_admin": user.is_admin,
                "is_verified": user.is_verified,
            },
            token={
                "access_token": auth_token.access_token,
                "refresh_token": auth_token.refresh_token,
                "token_type": auth_token.token_type,
                "expire_datetime": auth_token.expire_datetime.isoformat(),
                "refresh_expire_datetime": auth_token.refresh_expire_datetime.isoformat(),
                "logged_in": True,
                "user_id": str(user.id),
            },
            redirect_url="/dashboards",  # Redirect to main app after successful auth
        )

        logger.info(f"OAuth authentication successful for user: {user.email}")
        return response_data

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error in OAuth callback: {e}")
        raise HTTPException(status_code=500, detail=f"OAuth authentication failed: {str(e)}")
