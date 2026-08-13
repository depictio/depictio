"""SSO attribute synchronisation for SAML logins.

On every SAML login the IdP assertion can carry group memberships and profile
attributes. :func:`sync_sso_user` mirrors those into Depictio: SSO-managed
groups are created/joined/left to match the assertion, and profile fields
(title, display name, login) are refreshed. The mapping between SAML attribute
names and Depictio fields is configured via ``settings.auth.saml_attribute_*``
(env vars ``DEPICTIO_AUTH_SAML_ATTRIBUTE_*``); each mapping left unset simply
disables that part of the sync, so the function is safe to call
unconditionally from the ACS handler.

No python3-saml dependency here on purpose — the module only consumes the
already-extracted ``dict[str, list[str]]`` attribute payload.
"""

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.users import GroupBeanie, UserBeanie


async def sync_sso_user(user: UserBeanie, attributes: dict[str, list[str]] | None) -> None:
    """Synchronise a user's groups and profile from SAML assertion attributes.

    INTEGRATION (PR #968): in saml_routes.py's ACS handler, after
    ``user, created = await create_or_get_sso_user(...)`` and before
    ``_create_magic_link_ticket(...)``, add:

        from depictio.api.v1.endpoints.auth_endpoints.sso_sync import sync_sso_user

        await sync_sso_user(user, auth.get_attributes())

    Idempotent and safe to run on every login. When ``attributes`` is None or
    empty the whole sync is a no-op (a broken/attribute-less assertion never
    wipes state). Each step is independently skipped when its
    ``settings.auth.saml_attribute_*`` mapping is unset.

    Group sync (``saml_attribute_groups``):
        The attribute's value list is taken verbatim as group names (whitespace
        stripped, empties dropped) — IdPs may send full DNs or plain names; no
        parsing is attempted, the raw value is the group name. For each
        incoming name the group is created if missing (``sso_managed=True``,
        no admins, no P.I. — a sysadmin designates the P.I. later) and the
        user is added to ``users_ids``. The user is then removed from every
        ``sso_managed`` group NOT named in the assertion (including
        ``admin_ids``, and ``pi_id`` is cleared if it was them). Manually
        created groups (``sso_managed=False``) are never touched.

        NOTE: when ``saml_attribute_groups`` is configured but the attribute
        is absent from this assertion, it is treated as an empty list — the
        user is removed from ALL sso-managed groups. The IdP assertion is the
        source of truth for SSO-managed membership.

    Profile sync (``saml_attribute_title`` / ``saml_attribute_display_name``
    / ``saml_attribute_login``):
        For each configured mapping whose attribute is present, the first
        value is stripped and written to ``user.title`` /
        ``user.display_name`` / ``user.login`` when non-empty and different.
        ``user.sso_provider`` is stamped ``"saml"``. The user document is
        saved once, and only if something actually changed.
    """
    if not attributes:
        logger.debug(f"SSO sync: no attributes in assertion for {user.email} — skipping")
        return

    await _sync_groups(user, attributes)
    await _sync_profile(user, attributes)


async def _sync_groups(user: UserBeanie, attributes: dict[str, list[str]]) -> None:
    """Mirror the assertion's group list onto sso_managed GroupBeanie docs."""
    attr_name = settings.auth.saml_attribute_groups
    if attr_name is None:
        return

    user_id_str = str(user.id)
    # Absent attribute => empty list => user leaves all sso_managed groups.
    incoming_names = [v.strip() for v in attributes.get(attr_name, []) if v and v.strip()]
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


async def _sync_profile(user: UserBeanie, attributes: dict[str, list[str]]) -> None:
    """Refresh user profile fields from configured SAML attribute mappings."""
    field_mappings: list[tuple[str | None, str]] = [
        (settings.auth.saml_attribute_title, "title"),
        (settings.auth.saml_attribute_display_name, "display_name"),
        (settings.auth.saml_attribute_login, "login"),
    ]
    if all(attr_name is None for attr_name, _ in field_mappings):
        return

    changed = False
    for attr_name, field in field_mappings:
        if attr_name is None:
            continue
        values = attributes.get(attr_name)
        if not values:
            continue
        value = values[0].strip()
        if value and getattr(user, field) != value:
            setattr(user, field, value)
            changed = True

    if user.sso_provider != "saml":
        user.sso_provider = "saml"
        changed = True

    if changed:
        await user.save()
        logger.info(f"SSO sync: updated profile attributes for {user.email}")
