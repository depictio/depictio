"""Authentication of an instance pushing a project here (#1303).

Two credentials, and the credential alone names the caller (whatever the body
claims about where it comes from is display text):

- ``X-Depictio-Pairing-Key``: a configured inbound source, matched in
  constant time against every configured key;
- ``X-Depictio-Invite-Code``: an invite an admin issued here
  (``services/migration_invites.py``). The caller becomes an
  :class:`InviteSource` named ``invite:<invite id>``. It never gets a
  server-side copy: it has no allowed source bucket.

A third, narrower one only reads the status of one request:
``X-Depictio-Request-Token``, handed back once by the upload that created it,
so a source whose single-use invite is spent can still follow its import.

Inbound routes answer 404 while ``DEPICTIO_MIGRATION_INBOUND_ENABLED`` is off,
so an instance that never opted in does not reveal that the feature exists.
On, with no source configured and no valid invite, every call is a 403.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastapi import Header, HTTPException
from pydantic import SecretStr

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.settings_models import MigrationInboundSource
from depictio.api.v1.services import migration_invites

PAIRING_HEADER = "X-Depictio-Pairing-Key"
INVITE_HEADER = migration_invites.INVITE_HEADER
REQUEST_TOKEN_HEADER = "X-Depictio-Request-Token"

#: Daily upload quota of one invite (a lineage invite may be re-pushed).
INVITE_MAX_PER_DAY = 20


class InviteSource(MigrationInboundSource):
    """The caller of an inbound route who presented an invite code.

    Built with ``model_construct``: it has no pairing key, and the invite
    document is carried for the routes that apply its policy.
    """

    invite_id: str = ""
    invite: dict[str, Any] = {}
    invite_state: str = "active"


def _str_or_none(value: Any) -> str | None:
    # Called directly (tests, other modules), an omitted Header() default is
    # the Header object itself, not None.
    return value if isinstance(value, str) else None


def match_inbound_source(key: str | None) -> MigrationInboundSource | None:
    """The configured source whose key is ``key``, compared in constant time.

    Every source is compared even after a match, so the time taken does not
    tell which entry (or how many) exist.
    """
    if not key:
        return None
    presented = key.encode()
    found: MigrationInboundSource | None = None
    for source in settings.migration.inbound_sources:
        if hmac.compare_digest(presented, source.pairing_key.get_secret_value().encode()):
            found = source
    return found


def invite_source(invite: dict[str, Any]) -> InviteSource:
    return InviteSource.model_construct(
        name=migration_invites.invite_source_name(invite["_id"]),
        pairing_key=SecretStr(""),
        allowed_source_buckets=[],
        max_pending=1,
        max_per_day=INVITE_MAX_PER_DAY,
        max_bundle_bytes=None,
        invite_id=str(invite["_id"]),
        invite=invite,
        invite_state=migration_invites.invite_state(invite),
    )


def _authenticate(
    pairing_key: str | None, invite_code: str | None, *, allow_spent_invite: bool
) -> MigrationInboundSource:
    if not settings.migration.inbound_enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    pairing_key, invite_code = _str_or_none(pairing_key), _str_or_none(invite_code)
    if pairing_key:
        source = match_inbound_source(pairing_key)
        if source is None:
            raise HTTPException(status_code=403, detail="Invalid pairing key")
        return source
    if invite_code:
        invite = migration_invites.find_invite(invite_code)
        if invite is None:
            raise HTTPException(status_code=403, detail="Invalid invite code")
        state = migration_invites.invite_state(invite)
        if state == "revoked" or (state != "active" and not allow_spent_invite):
            raise HTTPException(status_code=403, detail=f"This invite code is {state}")
        return invite_source(invite)
    raise HTTPException(status_code=403, detail="Invalid pairing key")


def require_inbound_source(
    x_depictio_pairing_key: str | None = Header(default=None, alias=PAIRING_HEADER),
    x_depictio_invite_code: str | None = Header(default=None, alias=INVITE_HEADER),
) -> MigrationInboundSource:
    """FastAPI dependency: the authenticated caller, or 404/403.

    An invite must be usable now (not spent, expired or revoked).
    """
    return _authenticate(x_depictio_pairing_key, x_depictio_invite_code, allow_spent_invite=False)


def require_inbound_reader(
    x_depictio_pairing_key: str | None = Header(default=None, alias=PAIRING_HEADER),
    x_depictio_invite_code: str | None = Header(default=None, alias=INVITE_HEADER),
    x_depictio_request_token: str | None = Header(default=None, alias=REQUEST_TOKEN_HEADER),
) -> MigrationInboundSource | str:
    """Who may read a request's status: a source, a spent (not revoked) invite,
    or the bearer of that request's token (returned as the token string; the
    route checks it against the request)."""
    token = _str_or_none(x_depictio_request_token)
    if (
        token
        and not _str_or_none(x_depictio_pairing_key)
        and not _str_or_none(x_depictio_invite_code)
    ):
        if not settings.migration.inbound_enabled:
            raise HTTPException(status_code=404, detail="Not Found")
        return token
    return _authenticate(x_depictio_pairing_key, x_depictio_invite_code, allow_spent_invite=True)


def hash_request_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def request_token_matches(doc: dict[str, Any], token: str) -> bool:
    stored = str(doc.get("status_token_sha256") or "")
    return bool(stored) and hmac.compare_digest(stored, hash_request_token(token))


def source_max_bundle_bytes(source: MigrationInboundSource) -> int:
    return int(source.max_bundle_bytes or settings.migration.max_bundle_bytes)
