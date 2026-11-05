"""The single provisioning path of SSO logins, and the claim sync it runs.

Every OpenID Connect login, whatever the provider, goes through
:func:`provision_sso_login`:

1. the email is read from the configured claim and accepted only when the
   provider verified it (``email_verified`` true, or the provider is configured
   with ``assume_email_verified``);
2. :func:`create_or_get_sso_user` matches or creates the account, honouring
   ``registration_disabled`` and claiming pending project ownership;
3. :func:`sync_sso_user` mirrors groups and profile claims, stamps
   ``user.sso_provider`` and claims pending P.I. designations and project
   ownership;
4. the provider's picture, when it sends one, becomes the profile picture.

Claim values may be a string or a list of strings: IdPs disagree (a single
group arrives as ``"lab"`` from one and ``["lab"]`` from another), and both
mean the same thing here.
"""

from collections.abc import Mapping
from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.configs.settings_models import OIDCProviderConfig
from depictio.api.v1.endpoints.auth_endpoints.utils import (
    AmbiguousSSOAccount,
    create_or_get_sso_user,
)
from depictio.api.v1.endpoints.groups_endpoints.pending_pi import claim_pending_pi_groups
from depictio.api.v1.endpoints.projects_endpoints.pending_owner import (
    claim_pending_project_ownership_quietly,
)
from depictio.models.models.users import GroupBeanie, UserBeanie


class SSOLoginRejected(Exception):
    """The identity is authentic but may not sign in. ``code`` goes to the browser."""

    def __init__(self, reason: str, code: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


# ---------------------------------------------------------------------------
# Claim access
# ---------------------------------------------------------------------------


def _lookup(claims: Mapping[str, Any], name: str) -> tuple[bool, Any]:
    """``(found, value)`` for a claim name: exact, then case-insensitive, then dotted path."""
    if name in claims:
        return True, claims[name]
    folded = name.casefold()
    for key, value in claims.items():
        if isinstance(key, str) and key.casefold() == folded:
            return True, value
    if "." in name:
        node: Any = claims
        for part in name.split("."):
            if not isinstance(node, Mapping):
                return False, None
            found, node = _lookup(node, part)
            if not found:
                return False, None
        return True, node
    return False, None


def claim_values(claims: Mapping[str, Any] | None, name: str) -> list[str] | None:
    """The values of claim ``name`` as a list of strings, or None if absent.

    A string becomes a one-item list, a list keeps its string items (numbers
    are stringified, anything else is dropped). Values are stripped and empty
    ones dropped. The exact name wins; otherwise the match ignores case,
    because an IdP may send ``Groups`` where a deployment configured
    ``groups`` and a mismatch would otherwise read as an empty list, which
    removes the user from every SSO-managed group. A dotted name not present
    as such is followed as a path (``realm_access.roles``).
    """
    if not claims:
        return None
    found, raw = _lookup(claims, name)
    if not found or raw is None:
        return None
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    values: list[str] = []
    for item in items:
        if isinstance(item, bool):
            continue
        if isinstance(item, (str, int, float)):
            text = str(item).strip()
            if text:
                values.append(text)
    return values


def first_claim(claims: Mapping[str, Any] | None, name: str | None) -> str | None:
    """The first value of claim ``name``, or None."""
    if not name:
        return None
    values = claim_values(claims, name)
    return values[0] if values else None


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------


def _is_email_verified(provider: OIDCProviderConfig, claims: Mapping[str, Any]) -> bool:
    if provider.assume_email_verified:
        return True
    value = claims.get("email_verified")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


async def provision_sso_login(
    provider: OIDCProviderConfig, claims: Mapping[str, Any]
) -> tuple[UserBeanie, bool]:
    """Resolve the account of a verified login and bring it up to date.

    Raises:
        SSOLoginRejected: no usable or no verified email (``code`` ``sso_failed``),
            or an unknown email while registration is disabled
            (``registration_disabled``).
    """
    email = first_claim(claims, provider.claims.email)
    if not email or "@" not in email:
        raise SSOLoginRejected(
            f"provider '{provider.id}' sent no usable '{provider.claims.email}' claim",
            "sso_failed",
        )
    if not _is_email_verified(provider, claims):
        # An unverified address could be anyone's: matching it to an account
        # would hand that account to whoever typed it at the provider.
        raise SSOLoginRejected(
            f"provider '{provider.id}' did not verify {email} (email_verified is not true)",
            "email_not_verified",
        )

    try:
        user, created = await create_or_get_sso_user(
            email, allow_create=not settings.auth.registration_disabled
        )
    except AmbiguousSSOAccount as e:
        # Two accounts differ only by the case of their email: signing in to
        # either would be a guess, and creating a third would make it worse.
        raise SSOLoginRejected(f"several accounts match {email} ignoring case", "sso_failed") from e
    if user is None:
        raise SSOLoginRejected(
            f"no account for {email} and registration is disabled", "registration_disabled"
        )

    # A failed sync must never turn a valid sign-in into an error: the user is
    # authenticated, and the next login re-syncs.
    try:
        await sync_sso_user(user, claims, provider)
    except Exception as sync_error:  # noqa: BLE001
        logger.error(f"SSO claim sync failed for {email}: {sync_error}")

    picture_claim = provider.claims.picture
    picture = first_claim(claims, picture_claim) if picture_claim else None
    if user.id is not None and picture and picture.startswith("https://"):
        from depictio.api.v1.services.avatars import set_provider_avatar

        # Never raises; an uploaded picture is left untouched, and an
        # unchanged URL is not downloaded again (see services/avatars.py).
        await set_provider_avatar(user.id, provider=provider.stored_provider_name, url=picture)

    return user, created


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


async def sync_sso_user(
    user: UserBeanie, claims: Mapping[str, Any] | None, provider: OIDCProviderConfig
) -> None:
    """Synchronise a user's groups and profile from the login's claims.

    Called by :func:`provision_sso_login`, after ``create_or_get_sso_user``
    and before the session ticket is minted.

    Idempotent and safe to run on every login. When ``claims`` is None or empty
    the whole sync is a no-op (a broken, claim-less login never wipes state).
    Each step is independently skipped when its mapping in
    ``provider.claims`` is unset.

    Group and profile sync are followed by ``claim_pending_pi_groups``: a P.I.
    designated by email before the account existed is promoted here, on the
    login that first asserts the group. Projects parked on the address are
    claimed too (``claim_pending_project_ownership_quietly``).

    Group sync (``claims.groups``):
        The claim's values are taken verbatim as group names (whitespace
        stripped, empties dropped); no parsing is attempted. For each incoming
        name the group is created if missing (``sso_managed=True``, no admins,
        no P.I.) and the user is added to ``users_ids``. The user is then
        removed from every ``sso_managed`` group NOT named in the claim
        (including ``admin_ids``, and ``pi_id`` is cleared if it was them).
        Manually created groups (``sso_managed=False``) are never touched.

        NOTE: when ``claims.groups`` is configured but the claim is absent from
        this login, it is treated as an empty list: the user is removed from
        ALL sso-managed groups. The provider is the source of truth for
        SSO-managed membership.

    Profile sync (``claims.title`` / ``claims.display_name`` / ``claims.login``):
        For each configured mapping whose claim is present, the first value
        is written to ``user.title`` / ``user.display_name`` / ``user.login``
        when non-empty and different. ``user.sso_provider`` is stamped with
        the provider's ``sso_provider`` name (its id by default). The user
        document is saved once, and only if something actually changed.
    """
    if not claims:
        logger.debug(f"SSO sync: no claims for {user.email}, skipping")
        return

    await _sync_groups(user, claims, provider)
    await _sync_profile(user, claims, provider)
    # Groups whose P.I. was designated by email before this account existed.
    # Runs after group sync so a freshly mirrored group can be claimed in the
    # same login.
    await claim_pending_pi_groups(user)
    # Projects pushed here for an address that had no account yet (#1303).
    await claim_pending_project_ownership_quietly(user)


async def _sync_groups(
    user: UserBeanie, claims: Mapping[str, Any], provider: OIDCProviderConfig
) -> None:
    """Mirror the claim's group list onto sso_managed GroupBeanie docs."""
    claim_name = provider.claims.groups
    if not claim_name:
        return

    user_id_str = str(user.id)
    # Absent claim => empty list => user leaves all sso_managed groups.
    incoming_names = list(dict.fromkeys(claim_values(claims, claim_name) or []))
    incoming_set = set(incoming_names)

    # Ensure membership in every asserted group, creating missing ones.
    for name in incoming_names:
        group = await GroupBeanie.find_one({"name": name})
        if group is None:
            group = GroupBeanie(name=name, sso_managed=True, users_ids=[user.id])
            await group.save()
            logger.info(f"SSO sync: created sso_managed group '{name}' for {user.email}")
        elif user_id_str not in {str(uid) for uid in group.users_ids}:
            group.users_ids.append(user.id)
            await group.save()
            logger.info(f"SSO sync: added {user.email} to group '{name}'")

    # Remove the user from sso_managed groups no longer asserted.
    # Manually created groups (sso_managed=False) are never touched.
    sso_groups = await GroupBeanie.find({"sso_managed": True}).to_list()
    for group in sso_groups:
        if group.name in incoming_set:
            continue
        changed = False
        if user_id_str in {str(uid) for uid in group.users_ids}:
            group.users_ids = [uid for uid in group.users_ids if str(uid) != user_id_str]
            changed = True
        if user_id_str in {str(uid) for uid in group.admin_ids}:
            group.admin_ids = [uid for uid in group.admin_ids if str(uid) != user_id_str]
            changed = True
        if group.pi_id is not None and str(group.pi_id) == user_id_str:
            group.pi_id = None
            changed = True
        if changed:
            await group.save()
            logger.info(f"SSO sync: removed {user.email} from stale group '{group.name}'")


async def _sync_profile(
    user: UserBeanie, claims: Mapping[str, Any], provider: OIDCProviderConfig
) -> None:
    """Refresh user profile fields from the provider's claim mapping."""
    field_mappings: list[tuple[str | None, str]] = [
        (provider.claims.title, "title"),
        (provider.claims.display_name, "display_name"),
        (provider.claims.login, "login"),
    ]

    changed = False
    for claim_name, field in field_mappings:
        value = first_claim(claims, claim_name)
        if value and getattr(user, field) != value:
            setattr(user, field, value)
            changed = True

    stamp = provider.stored_provider_name
    if user.sso_provider != stamp:
        user.sso_provider = stamp
        changed = True

    if changed:
        await user.save()
        logger.info(f"SSO sync: updated profile for {user.email}")
