"""
Utility functions for SSO authentication (Google OAuth, shared SSO user mapping).

This module contains helper functions for managing OAuth state, token exchange,
and user creation for browser SSO flows.
"""

import secrets
from typing import Any

import httpx
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.auth_endpoints.state_store import (
    consume_auth_state,
    store_auth_state,
)
from depictio.models.models.google_oauth import GoogleUserInfo
from depictio.models.models.users import UserBeanie


def generate_oauth_state() -> str:
    """Generate a secure random state parameter for OAuth CSRF protection."""
    state = secrets.token_urlsafe(32)
    store_auth_state("oauth", state)
    logger.debug(f"Generated OAuth state: {state}")
    return state


def validate_oauth_state(state: str) -> bool:
    """Validate an OAuth state parameter, consuming it so it cannot be replayed."""
    if consume_auth_state("oauth", state) is None:
        logger.warning(f"OAuth state unknown, already used, or expired: {state}")
        return False
    logger.debug(f"State {state} validated successfully")
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


async def create_or_get_sso_user(
    email: str, *, allow_create: bool = True
) -> tuple[UserBeanie | None, bool]:
    """Create or fetch a user for an IdP-verified email (Google OAuth, SAML).

    Args:
        email: Email address already verified by the identity provider.
        allow_create: When False, never provision a new account — return
            ``(None, False)`` for an unknown email. Used to honour
            ``registration_disabled`` so SSO is a login-only door for
            pre-provisioned accounts, not a registration bypass.

    Returns:
        Tuple of (user, created) where created is True if user was newly
        created. ``user`` is None when the email is unknown and
        ``allow_create`` is False.
    """
    from depictio.api.v1.endpoints.user_endpoints.core_functions import _hash_password

    existing_user = await UserBeanie.find_one({"email": email})

    if existing_user:
        logger.info(f"Existing user found for SSO login: {email}")
        return existing_user, False

    if not allow_create:
        logger.warning(
            f"SSO login rejected for unregistered email (registration disabled): {email}"
        )
        return None, False

    logger.info(f"Creating new user from SSO: {email}")

    new_user = UserBeanie(
        email=email,
        # SSO users have no usable password; a hash of an unguessable random
        # secret keeps password login structurally valid but never satisfiable.
        password=_hash_password(secrets.token_urlsafe(32)),
        is_admin=False,
        is_active=True,
        is_verified=True,  # Email is verified by the identity provider
    )

    await new_user.save()
    logger.info(f"Created new SSO user: {new_user.id}")

    return new_user, True


async def create_or_get_user(
    google_user: GoogleUserInfo, *, allow_create: bool = True
) -> tuple[UserBeanie | None, bool]:
    """Create new user or get existing user from Google OAuth info."""
    return await create_or_get_sso_user(google_user.email, allow_create=allow_create)
