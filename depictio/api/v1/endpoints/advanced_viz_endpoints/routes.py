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
from fastapi.responses import PlainTextResponse

from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.components.advanced_viz.schemas import CANONICAL_SCHEMAS
from depictio.models.components.types import AdvancedVizKind
from depictio.models.models.base import PyObjectId

logger = logging.getLogger(__name__)

advanced_viz_endpoint_router = APIRouter()


_KIND_METADATA: dict[AdvancedVizKind, dict[str, Any]] = {
    "phylogenetic": {
        "label": "Phylogenetic tree",
        "description": "Newick tree + tip metadata (Microreact-style): 5 layouts, tip search, subtree highlight.",
        "icon": "tabler:hierarchy-3",
    },
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
    "rarefaction": {
        "label": "Rarefaction curves",
        "description": "Alpha-diversity vs sequencing depth — one line per sample with ±SE band and group colouring.",
        "icon": "tabler:chart-line",
    },
    "ancombc_differentials": {
        "label": "ANCOM-BC differentials",
        "description": "Ranked signed-LFC horizontal bar of differentially-abundant features for the selected contrast.",
        "icon": "tabler:chart-bar",
    },
    "da_barplot": {
        "label": "DA barplot (per contrast)",
        "description": "Faceted top-N differentially-abundant features, one panel per contrast.",
        "icon": "tabler:chart-bar-popular",
    },
    "enrichment": {
        "label": "Pathway enrichment (GSEA / GO / KEGG)",
        "description": "Dot plot: term on y, NES on x, dot size = gene-set size, colour = -log10(padj).",
        "icon": "tabler:chart-dots",
    },
    "complex_heatmap": {
        "label": "ComplexHeatmap (clustered)",
        "description": "Clustered heatmap with dendrograms + annotation tracks. Server-side clustering via plotly-complexheatmap, dispatched as a Celery task.",
        "icon": "tabler:grid-pattern",
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


def _compute_cache_key(payload: dict) -> str:
    """Stable key for the compute_results cache.

    Inputs that affect the embedding output: dc_id, method, params (sorted),
    feature_id_col, filter_metadata. We hash to a fixed-length string so the
    key fits comfortably as a Mongo ``_id``.
    """
    import hashlib
    import json as _json

    blob = _json.dumps(
        {
            "dc_id": str(payload.get("dc_id", "")),
            "method": payload.get("method", ""),
            "feature_id_col": payload.get("feature_id_col", "sample_id"),
            "params": payload.get("params") or {},
            "filter_metadata": payload.get("filter_metadata") or [],
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


@advanced_viz_endpoint_router.post("/compute_embedding")
def dispatch_compute_embedding(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Dispatch a clustering / dim-reduction Celery task.

    Cache lookup first — if an identical computation already finished we
    return its result immediately. Otherwise enqueue the task and return a
    ``job_id`` the frontend can poll via ``GET /compute_embedding/{job_id}``.
    """
    import time
    from datetime import datetime, timezone

    from depictio.api.v1.db import db
    from depictio.api.v1.celery_tasks import compute_embedding as compute_task

    method = (payload.get("method") or "").lower()
    if method not in {"pca", "umap", "tsne", "pcoa"}:
        raise HTTPException(status_code=400, detail=f"Unsupported method: {method!r}")
    if not payload.get("wf_id") or not payload.get("dc_id"):
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")

    cache = db["compute_results"]
    cache_key = _compute_cache_key(payload)
    existing = cache.find_one({"_id": cache_key})

    # Cache hit (done or pending).
    if existing:
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }

    # Miss → mark pending, dispatch task, return job_id.
    cache.insert_one(
        {
            "_id": cache_key,
            "status": "pending",
            "method": method,
            "created_at": datetime.now(timezone.utc),
            "payload": {
                "wf_id": str(payload["wf_id"]),
                "dc_id": str(payload["dc_id"]),
                "method": method,
                "params": payload.get("params") or {},
            },
        }
    )

    # Dispatch via apply_async with a callback that updates the cache doc.
    # We use a lightweight inline wrapper so Celery's success / failure
    # handlers don't need a separate task.
    started = time.monotonic()
    async_result = compute_task.apply_async(args=[payload])
    cache.update_one({"_id": cache_key}, {"$set": {"celery_task_id": async_result.id}})
    logger.info(
        "compute_embedding dispatched: method=%s cache_key=%s task_id=%s (%.2fs to enqueue)",
        method,
        cache_key,
        async_result.id,
        time.monotonic() - started,
    )
    return {"job_id": cache_key, "status": "pending", "from_cache": False}


@advanced_viz_endpoint_router.get("/compute_embedding/{job_id}")
def poll_compute_embedding(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll cache for a previously-dispatched embedding compute.

    Returns ``{status: 'done', result: {...}}`` when ready,
    ``{status: 'pending'}`` while running, or
    ``{status: 'failed', error: '...'}`` on error.
    """
    from datetime import datetime, timezone

    from celery.result import AsyncResult

    from depictio.api.v1.db import db
    from depictio.dash.celery_app import celery_app

    cache = db["compute_results"]
    doc = cache.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")

    # If already terminal (done/failed), short-circuit.
    if doc.get("status") in ("done", "failed"):
        return {
            "job_id": job_id,
            "status": doc["status"],
            "result": doc.get("result"),
            "error": doc.get("error"),
        }

    # Otherwise check Celery's status for the underlying task and update
    # the cache doc if it has completed (Celery's backend isn't necessarily
    # the same Mongo collection so we mirror status here for the frontend).
    task_id = doc.get("celery_task_id")
    if not task_id:
        return {"job_id": job_id, "status": doc.get("status", "pending")}

    async_result = AsyncResult(task_id, app=celery_app)
    if async_result.ready():
        if async_result.successful():
            result = async_result.result
            cache.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "done",
                        "result": result,
                        "completed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {"job_id": job_id, "status": "done", "result": result}
        # Failed.
        err = str(async_result.result)[:500]
        cache.update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": "failed",
                    "error": err,
                    "completed_at": datetime.now(timezone.utc),
                }
            },
        )
        return {"job_id": job_id, "status": "failed", "error": err}

    return {"job_id": job_id, "status": "pending"}


@advanced_viz_endpoint_router.post("/compute_complex_heatmap")
def dispatch_compute_complex_heatmap(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Dispatch a ComplexHeatmap Celery task. Same dispatch + poll +
    cache contract as ``compute_embedding`` — different task name and
    namespace under the same ``compute_results`` collection."""
    import time
    from datetime import datetime, timezone

    from depictio.api.v1.db import db
    from depictio.api.v1.celery_tasks import compute_complex_heatmap as compute_task

    if not payload.get("wf_id") or not payload.get("dc_id"):
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")

    cache = db["compute_results"]
    # Reuse the same cache_key helper — its blob already includes a
    # `method`-style discriminator via the viz-specific payload keys
    # (value_columns, normalize, cluster_method...). We add a fixed
    # method marker to namespace these from embedding entries.
    payload_for_key = dict(payload)
    payload_for_key.setdefault("method", "complex_heatmap")
    cache_key = _compute_cache_key(payload_for_key)
    existing = cache.find_one({"_id": cache_key})
    if existing:
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }

    cache.insert_one(
        {
            "_id": cache_key,
            "status": "pending",
            "method": "complex_heatmap",
            "created_at": datetime.now(timezone.utc),
            "payload": {
                "wf_id": str(payload["wf_id"]),
                "dc_id": str(payload["dc_id"]),
                "method": "complex_heatmap",
            },
        }
    )
    started = time.monotonic()
    async_result = compute_task.apply_async(args=[payload])
    cache.update_one({"_id": cache_key}, {"$set": {"celery_task_id": async_result.id}})
    logger.info(
        "compute_complex_heatmap dispatched: cache_key=%s task_id=%s (%.2fs to enqueue)",
        cache_key,
        async_result.id,
        time.monotonic() - started,
    )
    return {"job_id": cache_key, "status": "pending", "from_cache": False}


@advanced_viz_endpoint_router.get("/compute_complex_heatmap/{job_id}")
def poll_compute_complex_heatmap(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched ComplexHeatmap compute. Returns
    {status: 'done', result: {figure, row_count, col_count, ...}} or
    {status: 'pending'} / {status: 'failed', error: '...'}."""
    from datetime import datetime, timezone

    from celery.result import AsyncResult

    from depictio.api.v1.db import db
    from depictio.dash.celery_app import celery_app

    cache = db["compute_results"]
    doc = cache.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    if doc.get("status") in ("done", "failed"):
        return {
            "job_id": job_id,
            "status": doc["status"],
            "result": doc.get("result"),
            "error": doc.get("error"),
        }
    task_id = doc.get("celery_task_id")
    if not task_id:
        return {"job_id": job_id, "status": doc.get("status", "pending")}
    async_result = AsyncResult(task_id, app=celery_app)
    if async_result.ready():
        if async_result.successful():
            result = async_result.result
            cache.update_one(
                {"_id": job_id},
                {"$set": {"status": "done", "result": result, "completed_at": datetime.now(timezone.utc)}},
            )
            return {"job_id": job_id, "status": "done", "result": result}
        err = str(async_result.result)[:500]
        cache.update_one(
            {"_id": job_id},
            {"$set": {"status": "failed", "error": err, "completed_at": datetime.now(timezone.utc)}},
        )
        return {"job_id": job_id, "status": "failed", "error": err}
    return {"job_id": job_id, "status": "pending"}


@advanced_viz_endpoint_router.get(
    "/phylogeny/{data_collection_id}/newick", response_class=PlainTextResponse
)
def get_phylogeny_newick(
    data_collection_id: PyObjectId,
    current_user=Depends(get_user_or_anonymous),
) -> str:
    """Return the raw Newick string for a phylogeny DC.

    Reads the file registered by the scan phase. If local, read from disk;
    if S3, stream via boto3.
    """
    from depictio.api.v1.db import files_collection

    try:
        dc_oid = ObjectId(str(data_collection_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid dc_id: {exc}") from exc

    file_doc = files_collection.find_one({"data_collection_id": dc_oid})
    if not file_doc:
        raise HTTPException(
            status_code=404,
            detail="Phylogeny DC has no registered file (scan may not have run).",
        )

    file_path = file_doc.get("file_location")
    if not file_path:
        raise HTTPException(status_code=404, detail="Phylogeny file location missing.")

    try:
        if file_path.startswith("s3://"):
            import boto3

            from depictio.api.v1.configs.config import settings

            s3 = boto3.client(
                "s3",
                endpoint_url=settings.minio.endpoint_url,
                aws_access_key_id=settings.minio.root_user,
                aws_secret_access_key=settings.minio.root_password,
            )
            _, _, rest = file_path.partition("s3://")
            bucket, _, key = rest.partition("/")
            obj = s3.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read().decode("utf-8")
        with open(file_path) as fh:
            return fh.read()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"Phylogeny file not found at {file_path}"
        ) from exc
    except Exception as exc:
        logger.warning("phylogeny newick read failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read phylogeny: {exc}") from exc
