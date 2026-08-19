"""Deferred P.I. designation — claiming groups parked on an email address.

A sysadmin can name a group's Principal Investigator before that person has
ever signed in: the address is parked on the group as ``pending_pi_email``
(``Group.pending_pi_email``). Every path that materialises a user document —
password registration and pipeline provisioning (``_create_user_in_db``),
Google OAuth (``create_or_get_google_user``) and SAML logins
(``sso_sync.sync_sso_user``) — calls :func:`claim_pending_pi_groups`, which
promotes the matching account to P.I. + group admin and clears the parked
email.

Deliberately import-light (models + logger only): the user-creation modules
that call it are imported by ``user_endpoints.routes``, which
``groups_endpoints.utils`` imports in turn — anything heavier here would close
that cycle.
"""

from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.users import GroupBeanie, UserBeanie


async def claim_pending_pi_groups(user: UserBeanie) -> list[str]:
    """Promote ``user`` to P.I. of every group parked on their email.

    Idempotent: a claimed group no longer carries the email, so replaying a
    login is a no-op. Returns the names of the groups claimed (empty list when
    there was nothing to claim), which callers may log.

    SSO-managed groups are only claimed once the user is a member of them —
    see the inline note below.
    """
    email = (user.email or "").strip().lower()
    if not email or user.id is None:
        return []

    groups = await GroupBeanie.find({"pending_pi_email": email}).to_list()
    claimed: list[str] = []
    for group in groups:
        # On SSO-managed groups the IdP owns membership: claiming a
        # non-member here would only be undone by the next assertion. Keep the
        # designation parked instead — group sync runs before this hook, so
        # the login that first asserts the group also claims it.
        if group.sso_managed and str(user.id) not in {str(uid) for uid in group.users_ids}:
            logger.debug(
                f"Pending P.I. '{email}' left parked on sso_managed group "
                f"'{group.name}' — not a member per the IdP assertion"
            )
            continue
        group.pi_id = user.id
        group.pending_pi_email = None
        if str(user.id) not in {str(admin_id) for admin_id in group.admin_ids}:
            group.admin_ids.append(user.id)
        if str(user.id) not in {str(member_id) for member_id in group.users_ids}:
            group.users_ids.append(user.id)
        await group.save()
        claimed.append(group.name)
        logger.info(f"Pending P.I. claimed: {email} is now P.I. of group '{group.name}'")
    return claimed
