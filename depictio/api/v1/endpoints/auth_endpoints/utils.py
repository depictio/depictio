"""
Utility functions for Google OAuth authentication.

This module contains helper functions for managing OAuth state, token exchange,
and user creation for Google OAuth 2.0 authentication flow.
"""

import secrets
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.google_oauth import GoogleUserInfo
from depictio.models.models.users import UserBeanie

# In-memory state storage (in production, use Redis or database)
_oauth_states: dict[str, datetime] = {}


def generate_oauth_state() -> str:
    """Generate a secure random state parameter for OAuth CSRF protection."""
    from depictio.api.v1.configs.logging_init import logger

    state = secrets.token_urlsafe(32)
    # Store state with expiration (10 minutes)
    expiry = datetime.now() + timedelta(minutes=10)
    _oauth_states[state] = expiry
    logger.debug(f"Generated OAuth state: {state}, expires at: {expiry}")
    return state


def validate_oauth_state(state: str) -> bool:
    """Validate OAuth state parameter and remove if valid."""
    import os

    from depictio.api.v1.configs.logging_init import logger

    # In development mode, skip state validation due to multi-worker issues
    if os.getenv("DEV_MODE", "false").lower() == "true":
        logger.debug(f"DEV_MODE: Skipping OAuth state validation for: {state}")
        return True

    logger.debug(f"Validating OAuth state: {state}")
    logger.debug(f"Current stored states: {list(_oauth_states.keys())}")

    if state not in _oauth_states:
        logger.warning(f"State {state} not found in stored states")
        return False

    # Check if state is expired
    if _oauth_states[state] < datetime.now():
        logger.warning(f"State {state} has expired")
        del _oauth_states[state]
        return False

    # Remove used state
    del _oauth_states[state]
    logger.debug(f"State {state} validated successfully")
    return True


def cleanup_expired_states() -> None:
    """Clean up expired OAuth states."""
    now = datetime.now()
    expired_states = [state for state, expiry in _oauth_states.items() if expiry < now]
    for state in expired_states:
        del _oauth_states[state]


async def exchange_code_for_token(code: str) -> dict[str, Any]:
    """Exchange authorization code for access token with Google."""
    token_url = "https://oauth2.googleapis.com/token"

    data = {
        "client_id": settings.auth.google_oauth_client_id,
        "client_secret": settings.auth.google_oauth_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.auth.google_oauth_redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)

        if response.status_code != 200:
            logger.error(f"Token exchange failed: {response.status_code} {response.text}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to exchange authorization code for token: {response.json()}",
            )

        return response.json()


async def fetch_google_user_info(access_token: str) -> GoogleUserInfo:
    """Fetch user information from Google API using access token."""
    user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        response = await client.get(user_info_url, headers=headers)

        if response.status_code != 200:
            logger.error(f"User info fetch failed: {response.status_code} {response.text}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to fetch user information from Google: {response.json()}",
            )

        user_data = response.json()

        # Validate that email is verified
        if not user_data.get("verified_email", False):
            raise HTTPException(
                status_code=400,
                detail="Google account email is not verified. Please verify your email with Google.",
            )

        return GoogleUserInfo(**user_data)


async def create_or_get_user(google_user: GoogleUserInfo) -> tuple[UserBeanie, bool]:
    """Create new user or get existing user from Google OAuth info.

    Returns:
        Tuple of (user, created) where created is True if user was newly created
    """
    # Check if user already exists
    existing_user = await UserBeanie.find_one({"email": google_user.email})

    if existing_user:
        logger.info(f"Existing user found for OAuth login: {google_user.email}")
        return existing_user, False

    # Create new user
    logger.info(f"Creating new user from OAuth: {google_user.email}")

    new_user = UserBeanie(
        email=google_user.email,
        password="$2b$12$oauth.user.no.password",  # OAuth users don't have passwords
        is_admin=False,
        is_active=True,
        is_verified=True,  # Google email is already verified
    )

    await new_user.save()
    logger.info(f"Created new OAuth user: {new_user.id}")

    return new_user, True
