"""Authentication of an instance pushing a project here (#1303).

The source sends ``X-Depictio-Pairing-Key``. Each configured inbound source has
its own key, so the key alone names the source: whatever the body claims about
where it comes from is display text. Inbound routes answer 404 while
``DEPICTIO_MIGRATION_INBOUND_ENABLED`` is off, so an instance that never opted
in does not reveal that the feature exists.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.settings_models import MigrationInboundSource

PAIRING_HEADER = "X-Depictio-Pairing-Key"


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


def require_inbound_source(
    x_depictio_pairing_key: str | None = Header(default=None, alias=PAIRING_HEADER),
) -> MigrationInboundSource:
    """FastAPI dependency: the authenticated inbound source, or 404/403."""
    if not settings.migration.inbound_enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    source = match_inbound_source(x_depictio_pairing_key)
    if source is None:
        raise HTTPException(status_code=403, detail="Invalid pairing key")
    return source


def source_max_bundle_bytes(source: MigrationInboundSource) -> int:
    return int(source.max_bundle_bytes or settings.migration.max_bundle_bytes)
