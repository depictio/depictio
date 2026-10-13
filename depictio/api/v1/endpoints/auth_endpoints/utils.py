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
from depictio.models.models.google_oauth import GoogleUserInfo, OAuthStateBeanie
from depictio.models.models.users import UserBeanie

# How long a user has to finish the Google consent screen before the state
# minted for their login attempt stops being accepted.
OAUTH_STATE_EXPIRY_MINUTES = 10


async def generate_oauth_state() -> str:
    """Mint a secure random state parameter for OAuth CSRF protection.

    The nonce is persisted so the callback — which may be served by any
    worker or replica — can recognise it. Expired rows are reaped by the
    collection's TTL index, so there is nothing to clean up here.
    """
    state = secrets.token_urlsafe(32)
    expiry = datetime.now() + timedelta(minutes=OAUTH_STATE_EXPIRY_MINUTES)
    await OAuthStateBeanie(state=state, expire_datetime=expiry).save()
    logger.debug(f"Generated OAuth state, expires at: {expiry}")
    return state


async def validate_oauth_state(state: str) -> bool:
    """Consume an OAuth state: it is valid once, and only before it expires.

    The lookup and the delete are a single atomic operation, so two callbacks
    racing on the same nonce cannot both be accepted — exactly one wins.
    """
    # find_one_and_delete rather than Beanie's read-then-delete: the latter
    # leaves a window in which a replayed callback could pass validation.
    consumed = await OAuthStateBeanie.get_pymongo_collection().find_one_and_delete({"state": state})

    if consumed is None:
        logger.warning("OAuth state not found: already used, expired, or never issued")
        return False

    if consumed["expire_datetime"] <= datetime.now():
        logger.warning("OAuth state has expired")
        return False

    logger.debug("OAuth state validated successfully")
    return True


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


async def create_or_get_user(
    google_user: GoogleUserInfo, *, allow_create: bool = True
) -> tuple[UserBeanie | None, bool]:
    """Create new user or get existing user from Google OAuth info.

    Args:
        google_user: Verified Google account info.
        allow_create: When False, never provision a new account — return
            ``(None, False)`` for an unknown email. Used to honour
            ``registration_disabled`` so OAuth is a login-only door for
            pre-provisioned accounts, not a registration bypass.

    Returns:
        Tuple of (user, created) where created is True if user was newly
        created. ``user`` is None when the email is unknown and
        ``allow_create`` is False.
    """
    # Check if user already exists
    existing_user = await UserBeanie.find_one({"email": google_user.email})

    if existing_user:
        logger.info(f"Existing user found for OAuth login: {google_user.email}")
        return existing_user, False

    if not allow_create:
        logger.warning(
            f"OAuth login rejected for unregistered email (registration disabled): "
            f"{google_user.email}"
        )
        return None, False

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
