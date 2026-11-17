"""Shared helpers of the browser SSO flow: login state store, SSO user mapping.

- :func:`store_oauth_state` / :func:`consume_oauth_state`: the single-use record
  a login carries from ``/login`` to ``/callback`` (``OAuthStateBeanie``).
- :func:`create_or_get_sso_user`: the one place an identity-provider-verified
  email becomes a Depictio account. Every SSO login reaches it through
  ``sso_sync.provision_sso_login``.
"""

import re
import secrets
from datetime import timedelta

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.groups_endpoints.pending_pi import (
    claim_pending_pi_groups,
)
from depictio.api.v1.endpoints.projects_endpoints.pending_owner import (
    claim_pending_project_ownership_quietly,
)
from depictio.models.models.oauth_state import OAuthState, OAuthStateBeanie
from depictio.models.models.users import UserBeanie
from depictio.models.timestamps import utc_now_naive

# How long a user has to finish the provider's sign-in page before the state
# minted for their login attempt stops being accepted.
OAUTH_STATE_EXPIRY_MINUTES = 10


async def store_oauth_state(
    *,
    provider: str,
    nonce: str,
    code_verifier: str,
    return_to: str,
) -> str:
    """Mint and persist the ``state`` of a new login; return it.

    The record is shared by every worker and replica, so the callback may land
    anywhere. Expired rows are reaped by the collection's TTL index.
    """
    state = secrets.token_urlsafe(32)
    expiry = utc_now_naive() + timedelta(minutes=OAUTH_STATE_EXPIRY_MINUTES)
    await OAuthStateBeanie(
        state=state,
        expire_datetime=expiry,
        provider=provider,
        nonce=nonce,
        code_verifier=code_verifier,
        return_to=return_to,
    ).save()
    return state


async def consume_oauth_state(state: str) -> OAuthState | None:
    """Consume a login state: valid once, and only before it expires.

    The lookup and the delete are a single atomic ``find_one_and_delete``, so
    two callbacks racing on the same state cannot both be accepted: exactly one
    wins, and a replayed callback finds nothing. An expired state is burned too.
    """
    if not state or not isinstance(state, str):
        return None
    consumed = await OAuthStateBeanie.get_pymongo_collection().find_one_and_delete({"state": state})
    if consumed is None:
        logger.warning("OIDC state not found: already used, expired, or never issued")
        return None
    if consumed["expire_datetime"] <= utc_now_naive():
        logger.warning("OIDC state has expired")
        return None
    consumed.pop("_id", None)
    return OAuthState.model_validate(consumed)


async def _find_user_by_email(email: str) -> UserBeanie | None:
    """The account for ``email``, matched exactly first, then ignoring case.

    Email addresses are compared case-insensitively: accounts created by the
    former SAML and Google integrations (or by registration) may be stored
    with a mixed-case local part, and the provider may send another casing.
    When the case-insensitive match is ambiguous (two accounts differing only
    by case), nothing is returned rather than guessing which one to sign in.
    """
    exact = await UserBeanie.find_one({"email": email})
    if exact is not None:
        return exact
    pattern = {"$regex": f"^{re.escape(email)}$", "$options": "i"}
    matches = await UserBeanie.find({"email": pattern}).limit(2).to_list()
    if len(matches) > 1:
        logger.error(
            f"SSO login for {email}: several accounts match ignoring case; refusing to "
            "pick one. Merge or rename them."
        )
        raise AmbiguousSSOAccount(email)
    return matches[0] if matches else None


class AmbiguousSSOAccount(Exception):
    """Several accounts match the SSO email once case is ignored."""


async def create_or_get_sso_user(
    email: str, *, allow_create: bool = True
) -> tuple[UserBeanie | None, bool]:
    """Create or fetch a user for an IdP-verified email.

    Existing accounts are matched by email, whatever provider (or none) created
    them, so accounts made by the former SAML and Google integrations keep
    signing in.

    Args:
        email: Email address already verified by the identity provider.
        allow_create: When False, never provision a new account: return
            ``(None, False)`` for an unknown email. Used to honour
            ``registration_disabled`` so SSO is a login-only door for
            pre-provisioned accounts, not a registration bypass.

    Returns:
        Tuple of (user, created) where created is True if user was newly
        created. ``user`` is None when the email is unknown and
        ``allow_create`` is False.
    """
    from depictio.api.v1.endpoints.user_endpoints.core_functions import _hash_password

    email = email.strip()
    existing_user = await _find_user_by_email(email)

    if existing_user:
        logger.info(f"Existing user found for SSO login: {email}")
        # The IdP verified this address, so projects parked on it are theirs.
        await claim_pending_project_ownership_quietly(existing_user)
        return existing_user, False

    if not allow_create:
        logger.warning(
            f"SSO login rejected for unregistered email (registration disabled): {email}"
        )
        return None, False

    logger.info(f"Creating new user from SSO: {email}")

    new_user = UserBeanie(
        email=email.lower(),
        # SSO users have no usable password; a hash of an unguessable random
        # secret keeps password login structurally valid but never satisfiable.
        password=_hash_password(secrets.token_urlsafe(32)),
        is_admin=False,
        is_active=True,
        is_verified=True,  # Email is verified by the identity provider
    )

    await new_user.save()
    logger.info(f"Created new SSO user: {new_user.id}")
    # Apply any group P.I. designation parked on this address. Best-effort for
    # the same reason as in _create_user_in_db: the account exists, and an
    # unclaimed designation stays parked for a later login.
    try:
        await claim_pending_pi_groups(new_user)
    except Exception as claim_error:
        logger.error(
            f"Pending P.I. claim failed for {new_user.email} (designation stays parked): "
            f"{claim_error}"
        )
    await claim_pending_project_ownership_quietly(new_user)

    return new_user, True
