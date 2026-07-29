"""Cache validation and provenance for exported components.

Answers three questions an embedding site has to ask, which the export API could
not answer before:

* **Did this change?** — an ``ETag`` over the inputs that determine the output, so
  a consumer can poll cheaply with ``If-None-Match`` and get ``304`` when nothing
  moved.
* **What am I looking at?** — provenance stamped into ``meta`` (dashboard version,
  last save time, the export contract's own version), so a figure saved to disk
  can still say where it came from.
* **Can I pin it?** — ``?expect_version=`` fails loudly with **409** when the
  dashboard has moved past the version the caller was built against, instead of
  silently serving something different.

Why an ETag rather than a plain ``Last-Modified``: the response depends on more
than the dashboard's save time. Filters, theme and format all change the bytes
while ``last_saved_ts`` stays put, so a timestamp alone would serve a light-theme
figure to a dark-theme request out of cache. Everything that varies the output
goes into the hash.

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
EXPORT_CONTRACT_VERSION = "1"


def dashboard_revision(dashboard_doc: dict) -> dict[str, Any]:
    """Provenance fields for one dashboard, as stored.

    ``version`` is the dashboard document's own counter, incremented on save.
    ``last_saved_ts`` is stored offset-naive in UTC, matching the rest of the API.
    """
    raw_ts = dashboard_doc.get("last_saved_ts")
    if isinstance(raw_ts, datetime):
        last_saved = raw_ts.isoformat()
    else:
        last_saved = str(raw_ts) if raw_ts else ""
    return {
        "dashboard_version": dashboard_doc.get("version"),
        "last_saved_ts": last_saved,
        "export_contract": EXPORT_CONTRACT_VERSION,
    }


def build_etag(
    *,
    dashboard_doc: dict,
    component_id: str,
    export_format: str,
    theme: str,
    filters: list[dict] | None,
) -> str:
    """Weak ETag over everything that varies the response body.

    Filters are serialised with ``sort_keys`` so two equivalent filter sets that
    differ only in key order do not produce different tags and defeat the cache.
    """
    revision = dashboard_revision(dashboard_doc)
    material = json.dumps(
        {
            "dashboard": str(dashboard_doc.get("dashboard_id", "")),
            "version": revision["dashboard_version"],
            "saved": revision["last_saved_ts"],
            "contract": EXPORT_CONTRACT_VERSION,
            "component": str(component_id),
            "format": export_format,
            "theme": theme,
            "filters": filters or [],
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(material.encode()).hexdigest()[:32]
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
