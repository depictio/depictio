"""Server-written project provenance.

``provenance``, ``published_lock`` and ``pending_owner_email`` describe where a
project came from and whether it is frozen. Clients round-trip the whole project
document through ``/projects/create`` and ``/projects/update``, so all three are
stripped from those payloads: a caller cannot claim another Depictio version,
lift a lock or park an owner by editing JSON.
"""

from __future__ import annotations

from typing import Any

from depictio.version import get_version

#: Project fields only the server writes. Never taken from a create/update body.
SERVER_OWNED_PROJECT_FIELDS: tuple[str, ...] = (
    "provenance",
    "published_lock",
    "pending_owner_email",
)


def strip_server_owned_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop every server-owned field from ``payload`` in place and return it."""
    for field in SERVER_OWNED_PROJECT_FIELDS:
        payload.pop(field, None)
    return payload


def stamp_new_project(payload: dict[str, Any]) -> dict[str, Any]:
    """Prepare a project document about to be inserted for the first time.

    Discards anything the caller sent for the server-owned fields and records
    the running Depictio version as the one that created it.
    """
    strip_server_owned_fields(payload)
    payload["provenance"] = {"created_with_version": get_version(), "imported_from": []}
    return payload


def instance_label() -> str:
    """How this instance names itself in bundles and import hops.

    ``DEPICTIO_MIGRATION_INSTANCE_LABEL`` when set, else the host of the public
    viewer URL, else ``"unknown"``.
    """
    from urllib.parse import urlsplit

    from depictio.api.v1.configs.config import settings

    migration = getattr(settings, "migration", None)
    label = getattr(migration, "instance_label", None) if migration else None
    if label:
        return str(label)
    try:
        host = urlsplit(settings.viewer.external_url).hostname
    except (AttributeError, ValueError):
        host = None
    return host or "unknown"
