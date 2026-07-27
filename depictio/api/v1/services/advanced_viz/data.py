"""Load the tidy column payload an advanced visualisation is built from.

Extracted from ``POST /advanced_viz/data`` so the export service can reach the
same data without going back through HTTP. The route keeps auth and link-filter
resolution and calls this for the rest.

Output is column-oriented (``{col: [values]}``) because that is what the React
renderers consume, and keeping one shape means the Python figure builders and
the TypeScript ones start from identical input.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.logging_init import logger

#: Advanced viz render client-side and Plotly degrades badly past this; recipes
#: are the right place to pre-reduce. Mirrors the cap in the data route.
DEFAULT_LIMIT_ROWS = 100_000


def _resolve_init_data(dc_oid: ObjectId, dc_id: str) -> dict[str, dict]:
    """Resolve the delta-table location straight from MongoDB.

    Handing ``init_data`` to ``load_deltatable_lite`` keeps it off the legacy
    ``GET /deltatables/get/{dc_id}`` fallback, which needs an auth token we do not
    carry across worker boundaries and would 401 here.
    """
    from depictio.api.v1.db import deltatables_collection

    dt_doc = deltatables_collection.find_one({"data_collection_id": dc_oid})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        logger.warning("advanced_viz data: no materialised delta table for dc_id=%s", dc_id)
        raise HTTPException(
            status_code=404,
            detail="Data collection has no materialised Delta table yet.",
        )
    return {
        dc_id: {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": (dt_doc.get("flexible_metadata") or {}).get("deltatable_size_bytes", 0),
        }
    }


def _available_columns(init_entry: dict) -> set[str] | None:
    """Read the DC's column names, or ``None`` if introspection fails."""
    try:
        from depictio.api.v1.deltatables_utils import _create_delta_scan

        scan = _create_delta_scan(init_entry["delta_location"], init_entry.get("dc_type"))
        return set(scan.collect_schema().names())
    except Exception as exc:
        logger.warning("advanced_viz data: schema introspection failed: %s", exc)
        return None


def _prune_filters(
    filter_metadata: list[dict], available_cols: set[str] | None, dc_id: str
) -> tuple[list[dict], set[str]]:
    """Drop filters this DC cannot satisfy and collect the columns the rest need.

    Two classes get dropped:

    * Filters with no ``column_name`` at all. Link resolution can synthesise these
      when both the resolved value and ``link_config.target_field`` are absent;
      keeping one crashes the filter-hash sort on ``None < str``.
    * Filters naming a column this DC does not have — a cross-DC link filter that
      does not apply here. Passing it to ``.select()`` would fail at ``collect()``.
    """
    kept: list[dict] = []
    filter_cols: set[str] = set()

    for f in filter_metadata:
        nested = f.get("metadata") if isinstance(f, dict) else None
        col = (f.get("column_name") if isinstance(f, dict) else None) or (
            (nested or {}).get("column_name") if nested else None
        )
        if not col:
            logger.warning(
                "advanced_viz data: dropping filter with no column_name (dc_id=%s)", dc_id
            )
            continue
        if available_cols is not None and col not in available_cols:
            logger.info(
                "advanced_viz data: dropping cross-DC filter on column %r — not in DC %s",
                col,
                dc_id,
            )
            continue
        filter_cols.add(col)
        kept.append(f)

    return kept, filter_cols


def load_tidy_columns(
    *,
    wf_id: str,
    dc_id: str,
    columns: list[str],
    filter_metadata: list[dict] | None = None,
    limit_rows: int | None = None,
) -> dict[str, Any]:
    """Project ``columns`` from a data collection with filters applied.

    Filter columns are merged into the projection: without that, scan-level column
    projection prunes a filtered column before the filter runs and the filter
    silently no-ops.

    Returns:
        ``{"columns", "rows", "row_count", "filter_applied"}``. ``columns`` echoes
        only the requested columns that survived projection — a caller that bound
        an optional column the recipe never emitted gets it omitted rather than an
        error.
    """
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    if not wf_id or not dc_id:
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")
    if not columns or not isinstance(columns, list):
        raise HTTPException(status_code=400, detail="columns must be a non-empty list")

    try:
        wf_oid = ObjectId(str(wf_id))
        dc_oid = ObjectId(str(dc_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid wf_id/dc_id: {exc}")

    init_data = _resolve_init_data(dc_oid, str(dc_id))
    available_cols = _available_columns(init_data[str(dc_id)])

    kept_filters, filter_cols = _prune_filters(
        list(filter_metadata or []), available_cols, str(dc_id)
    )

    projection = list(dict.fromkeys([*columns, *filter_cols]))
    if available_cols is not None:
        projection = [c for c in projection if c in available_cols]

    try:
        df = load_deltatable_lite(
            workflow_id=wf_oid,
            data_collection_id=str(dc_oid),
            metadata=kept_filters or None,
            limit_rows=DEFAULT_LIMIT_ROWS if limit_rows is None else limit_rows,
            select_columns=projection,
            init_data=init_data,
        )
    except Exception as exc:
        logger.warning(
            "advanced_viz data: load_deltatable_lite failed for dc_id=%s: %s",
            dc_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to load data collection: {exc}"
        ) from exc

    present = [c for c in columns if c in df.columns]
    return {
        "columns": present,
        "rows": {c: df.get_column(c).to_list() for c in present},
        "row_count": int(df.height),
        "filter_applied": bool(kept_filters),
    }
