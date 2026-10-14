"""Resolve a data collection's Delta table location for offline/export renders.

``load_deltatable_lite`` takes an ``init_data`` hint naming the Delta location. Pass
it and the loader reads MinIO directly; omit it and the loader falls back to a
deprecated in-process ``GET /deltatables/get/{dc_id}`` call, which needs a bearer
token the export path does not carry and so fails with a bare
``Exception("Error loading deltatable")``.

That failure mode is quiet — the export still returns 200 with an empty value list —
so this lives in one module rather than being re-derived per call site. Both the
Plotly export and the offline embed payload use it.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger


def delta_location_for(dc_id: Any, dc_config: dict | None = None) -> str | None:
    """Best-known Delta table location for a data collection, or ``None``.

    Prefers the component's own ``dc_config`` snapshot and falls back to the
    ``deltatables`` collection, which is authoritative but costs a query. Older
    stored metadata predates ``delta_location`` being persisted, so the fallback is
    load-bearing rather than defensive.
    """
    delta_location = (dc_config or {}).get("delta_location")
    if delta_location:
        return delta_location

    from depictio.api.v1.db import deltatables_collection

    try:
        doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    except Exception as exc:  # malformed id, or Mongo unreachable
        logger.warning("export: delta-table lookup failed for dc=%s: %s", dc_id, exc)
        return None
    return (doc or {}).get("delta_table_location")


def init_data_for(dc_id: Any, dc_config: dict | None = None) -> dict[str, dict]:
    """``init_data`` hint keeping ``load_deltatable_lite`` off its legacy HTTP path.

    Returns ``{}`` when the data collection has no materialised Delta table. That
    is not an error here: the caller decides whether an unmaterialised DC is fatal
    (a figure export) or merely empty (a control's value universe).
    """
    delta_location = delta_location_for(dc_id, dc_config)
    if not delta_location:
        return {}

    dc_config = dc_config or {}
    return {
        str(dc_id): {
            "delta_location": delta_location,
            "dc_type": dc_config.get("type") or "table",
            "size_bytes": dc_config.get("size_bytes", 0),
        }
    }
