"""Backend endpoints for the advanced visualisation component family.

Thin endpoints:

* ``POST /advanced_viz/data`` — project a small column subset from a DC,
  apply the dashboard's filter metadata, return rows in a column-oriented
  dict shape the React renderers can consume directly. Heavy filtering /
  scanning re-uses ``load_deltatable_lite``; clustering/dim-reduction is
  handled at ingest by recipes (see depictio/recipes/lib/dimreduction.py),
  not here.

* ``GET /advanced_viz/kinds`` — small metadata payload the React builder
  uses to render the viz-kind picker (label + description + required
  roles), so the TS side never falls out of sync with the Pydantic schema.
"""

from __future__ import annotations

import logging
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.components.advanced_viz.schemas import CANONICAL_SCHEMAS
from depictio.models.components.types import AdvancedVizKind

logger = logging.getLogger(__name__)

advanced_viz_endpoint_router = APIRouter()


_KIND_METADATA: dict[AdvancedVizKind, dict[str, Any]] = {
    "volcano": {
        "label": "Volcano plot",
        "description": "Effect size vs significance, threshold lines, search & top-N labels.",
        "icon": "tabler:chart-scatter",
    },
    "embedding": {
        "label": "Embedding (PCA / UMAP / t-SNE / PCoA)",
        "description": "2D sample embedding from a pre-computed (or recipe-derived) DC.",
        "icon": "tabler:atom",
    },
    "manhattan": {
        "label": "Manhattan / GWAS",
        "description": "chr / pos / score scatter — works for true GWAS, peak qvalues, and variant AF.",
        "icon": "tabler:chart-histogram",
    },
    "stacked_taxonomy": {
        "label": "Stacked taxonomy",
        "description": "Per-sample stacked relative-abundance bar with rank dropdown.",
        "icon": "tabler:chart-pie",
    },
}


@advanced_viz_endpoint_router.get("/kinds")
def list_kinds(current_user=Depends(get_user_or_anonymous)) -> list[dict[str, Any]]:
    """Return the metadata payload the React builder uses to populate the viz_kind picker."""
    return [
        {
            "viz_kind": kind,
            "label": meta["label"],
            "description": meta["description"],
            "icon": meta["icon"],
            "required_roles": list(CANONICAL_SCHEMAS[kind].keys()),
        }
        for kind, meta in _KIND_METADATA.items()
    ]


@advanced_viz_endpoint_router.post("/data")
def fetch_advanced_viz_data(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Project requested columns from a DC, apply filter metadata, return rows.

    Input shape:
        {
          "wf_id": str,
          "dc_id": str,
          "columns": [str],          # column names to project
          "filter_metadata": [...],  # optional global filters
          "limit_rows": int | None,  # optional cap (default 100k)
        }

    Output shape:
        {
          "columns": [str],          # echoed back for ordering
          "rows": {col: [values]},   # column-oriented
          "row_count": int,
          "filter_applied": bool,
        }
    """
    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    columns = payload.get("columns") or []
    filter_metadata = payload.get("filter_metadata") or []
    limit_rows = payload.get("limit_rows")

    if not wf_id or not dc_id:
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")
    if not columns or not isinstance(columns, list):
        raise HTTPException(status_code=400, detail="columns must be a non-empty list")

    # Cap at 100k rows by default — advanced viz are rendered client-side and
    # plotly chokes on huge frames. Recipes are the right place to pre-reduce.
    if limit_rows is None:
        limit_rows = 100_000

    try:
        wf_oid = ObjectId(str(wf_id))
        dc_oid = ObjectId(str(dc_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid wf_id/dc_id: {exc}")

    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    # Resolve delta-table location directly from MongoDB and hand it to
    # load_deltatable_lite via init_data so it does NOT take the legacy
    # HTTP fallback (`GET /deltatables/get/{dc_id}`) — that path needs an
    # auth token we don't carry across worker boundaries and 401s here.
    # Mirrors the pattern used by celery_tasks.build_figure_preview.
    init_data: dict[str, dict] = {}
    dt_doc = deltatables_collection.find_one({"data_collection_id": dc_oid})
    if dt_doc and dt_doc.get("delta_table_location"):
        init_data[str(dc_id)] = {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": (dt_doc.get("flexible_metadata") or {}).get("deltatable_size_bytes", 0),
        }
    else:
        logger.warning("advanced_viz/data: no materialised delta table for dc_id=%s", dc_id)
        raise HTTPException(
            status_code=404,
            detail="Data collection has no materialised Delta table yet.",
        )

    try:
        df = load_deltatable_lite(
            workflow_id=wf_oid,
            data_collection_id=str(dc_oid),
            metadata=filter_metadata or None,
            limit_rows=limit_rows,
            select_columns=columns,
            init_data=init_data,
        )
    except Exception as exc:
        logger.warning(
            "advanced_viz/data: load_deltatable_lite failed for dc_id=%s: %s",
            dc_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to load data collection: {exc}"
        ) from exc

    # Drop any requested columns that didn't survive projection (e.g. user
    # bound an optional column the recipe didn't emit). The renderer
    # decides what to do with missing optional columns.
    present = [c for c in columns if c in df.columns]
    return {
        "columns": present,
        "rows": {c: df.get_column(c).to_list() for c in present},
        "row_count": int(df.height),
        "filter_applied": bool(filter_metadata),
    }
