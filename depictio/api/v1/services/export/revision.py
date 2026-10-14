"""Cache validation and provenance for exported components.

Answers three questions an embedding site has to ask:

* **Did this change?** — an ``ETag`` over the inputs that determine the output, so
  a consumer can poll cheaply with ``If-None-Match`` and get ``304`` when nothing
  moved.
* **What am I looking at?** — provenance stamped into ``meta`` (the dashboard
  version from the version ledger, the export contract's own version), so a
  figure saved to disk can still say where it came from.
* **Can I pin it?** — ``?expect_revision=`` fails loudly with **409** when the
  component has moved past the revision the caller was built against, instead
  of silently serving something different.

What "moved" means is two things, and both have to be in the revision:

* **the definition** — the family's latest entry in the dashboard version ledger
  (``dashboard_versions``), whose ``content_hash`` changes on every content
  edit and on nothing else. The document's own ``version`` counter and
  ``last_saved_ts`` look like candidates and are not: ``version`` counts
  imports (a UI save never bumps it) and ``last_saved_ts`` is rewritten by the
  screenshot task. Both are in ``SNAPSHOT_VOLATILE_FIELDS`` for that reason.
* **the data** — the latest ``aggregation_hash`` of every data collection the
  component reads, which changes on re-ingest. Without it a re-ingested table
  revalidates as 304 and the host keeps the stale figure.

Why an ETag rather than a plain ``Last-Modified``: filters, theme and format all
change the bytes while the dashboard stays put, so a timestamp alone would serve
a light-theme figure to a dark-theme request out of cache. Everything that varies
the output goes into the hash.

The ETag is deliberately **weak** (``W/"..."``). Two builds of the same component
are semantically identical but not byte-identical: ``meta.generated_at`` is a
fresh timestamp on every call. A strong validator would be a lie, and the HTTP
spec reserves strong ones for byte-range requests, which do not apply here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

#: Version of the export *contract*, not of Depictio. Bump when the response
#: shape changes in a way a consumer could notice — a renamed key, a different
#: trace structure. Stamped into `meta` so a saved figure records which contract
#: produced it, and included in the ETag so a deploy that changes the shape
#: invalidates every cached copy rather than serving a stale mixture.
#:
#: 2: `meta.revision` / `expect_revision` replace `dashboard_version` /
#:    `expect_version`, and `meta.view` names the advanced-viz view drawn.
EXPORT_CONTRACT_VERSION = "2"


def _digest(material: Any, length: int = 16) -> str:
    blob = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:length]


def _ledger_entry(dashboard_doc: dict) -> dict[str, Any] | None:
    """The family's latest version record, or ``None`` (no ledger, or no entry yet)."""
    try:
        from depictio.api.v1.endpoints.dashboards_endpoints import version_store
        from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
            resolve_family_id,
        )

        family_id = resolve_family_id(dashboard_doc)
        if family_id is None:
            return None
        return version_store.latest_version(str(family_id))
    except Exception:
        return None


def _definition_fallback(dashboard_doc: dict) -> str:
    """Content hash of the document itself, for a family with no ledger entry yet.

    A family gets its first entry on its first save; one imported and never
    edited has none. Its stored content (volatile fields excluded) is then the
    definition.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
        SNAPSHOT_VOLATILE_FIELDS,
    )

    return _digest(
        {k: v for k, v in dashboard_doc.items() if k not in SNAPSHOT_VOLATILE_FIELDS},
        length=32,
    )


def component_dc_ids(component: dict | None) -> list[str]:
    """Every data collection a component's output depends on directly.

    Its own ``dc_id``, any ``*_dc_id`` an advanced-viz config names (an MA table,
    a tree), and each live value of a text tile.
    """
    if not component:
        return []
    found: list[Any] = [component.get("dc_id")]
    for key, value in (component.get("config") or {}).items():
        if key.endswith("_dc_id"):
            found.append(value)
    for spec in (component.get("values") or {}).values():
        if isinstance(spec, dict):
            found.append(spec.get("dc_id"))
    return sorted({str(dc) for dc in found if dc})


def _data_revision(component: dict | None) -> dict[str, str | None]:
    from depictio.api.v1.deltatables_utils import _get_aggregation_hash

    return {dc: _get_aggregation_hash(dc) for dc in component_dc_ids(component)}


def dashboard_revision(dashboard_doc: dict, component: dict | None = None) -> dict[str, Any]:
    """Provenance for one component of one dashboard, as it stands now.

    Returns ``revision`` (what ``expect_revision`` pins and the ETag covers),
    the ledger's ``dashboard_version_id`` / ``dashboard_version_seq`` when the
    family has one, ``last_saved_ts`` for humans, and the contract version.
    """
    entry = _ledger_entry(dashboard_doc)
    definition = (entry or {}).get("content_hash") or _definition_fallback(dashboard_doc)
    revision = _digest(
        {
            "dashboard": str(dashboard_doc.get("dashboard_id", "")),
            "definition": definition,
            "data": _data_revision(component),
        }
    )

    raw_ts = dashboard_doc.get("last_saved_ts")
    if isinstance(raw_ts, datetime):
        last_saved = raw_ts.isoformat()
    else:
        last_saved = str(raw_ts) if raw_ts else ""
    return {
        "revision": revision,
        "dashboard_version_id": (entry or {}).get("version_id"),
        "dashboard_version_seq": (entry or {}).get("seq"),
        "last_saved_ts": last_saved,
        "export_contract": EXPORT_CONTRACT_VERSION,
    }


def build_etag(
    *,
    revision: str,
    component_id: str,
    export_format: str,
    theme: str,
    filters: list[dict] | None,
    controls: dict | None = None,
) -> str:
    """Weak ETag over everything that varies the response body.

    ``revision`` is :func:`dashboard_revision`'s, which already covers the
    definition and the data. Filters and controls are serialised with
    ``sort_keys`` so two equivalent sets that differ only in key order do not
    produce different tags and defeat the cache. ``controls`` has to be in here:
    a ROC and a PR curve come from the same component at the same revision, and
    omitting it would serve one from cache when the caller asked for the other.
    """
    digest = _digest(
        {
            "revision": revision,
            "contract": EXPORT_CONTRACT_VERSION,
            "component": str(component_id),
            "format": export_format,
            "theme": theme,
            "filters": filters or [],
            "controls": controls or {},
        },
        length=32,
    )
    return f'W/"{digest}"'


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """Whether the client's ``If-None-Match`` covers this ETag.

    Handles the two forms a client may send: a comma-separated list, and ``*``.
    Comparison is by weak-comparison rules — ``W/"x"`` and ``"x"`` match — which
    is what RFC 9110 requires for anything other than a byte-range request.
    """
    if not if_none_match:
        return False
    candidates = [c.strip() for c in if_none_match.split(",")]
    if "*" in candidates:
        return True

    def normalise(value: str) -> str:
        return value[2:] if value.startswith("W/") else value

    return normalise(etag) in {normalise(c) for c in candidates}
