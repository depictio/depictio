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
import os
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
        "label": "Embedding / clustering",
        "description": (
            "2D/3D sample embedding (PCA / UMAP / t-SNE / PCoA) — accepts a "
            "pre-computed DC (dim_1, dim_2 columns) or runs the reduction "
            "live on a wide sample×feature matrix DC via Celery."
        ),
        "icon": "tabler:atom",
    },
    "manhattan": {
        "label": "GWAS Manhattan (tool)",
        "description": "chr / pos / score scatter — works for true GWAS, peak qvalues, and variant AF.",
        "icon": "tabler:chart-histogram",
        "category": "tool",
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
        "label": "ANCOM-BC differential abundance (tool)",
        "description": "Ranked signed-LFC horizontal bar of differentially-abundant features for the selected contrast.",
        "icon": "tabler:chart-bar",
        "category": "tool",
    },
    "da_barplot": {
        "label": "Differential-abundance bars (tool, per contrast)",
        "description": "Faceted top-N differentially-abundant features, one panel per contrast.",
        "icon": "tabler:chart-bar-popular",
        "category": "tool",
    },
    "enrichment": {
        "label": "GSEA / pathway enrichment (tool)",
        "description": "Dot plot: term on y, NES on x, dot size = gene-set size, colour = -log10(padj).",
        "icon": "tabler:chart-dots",
        "category": "tool",
    },
    "complex_heatmap": {
        "label": "ComplexHeatmap (clustered)",
        "description": "Clustered heatmap with dendrograms + annotation tracks. Server-side clustering via plotly-complexheatmap, dispatched as a Celery task.",
        "icon": "tabler:grid-pattern",
    },
    "upset_plot": {
        "label": "UpSet plot",
        "description": "Set-intersection visualisation (alternative to Venn diagrams). Server-side compute via plotly-upset, dispatched as a Celery task.",
        "icon": "tabler:chart-bar-popular",
    },
    "ma": {
        "label": "MA plot",
        "description": "Mean log intensity vs log2 fold change — same hits as a volcano, classic DE / proteomics layout.",
        "icon": "tabler:chart-bell",
    },
    "dot_plot": {
        "label": "Dot plot",
        "description": "scanpy / Seurat marker dot plot: cluster × gene with size = fraction expressing, colour = mean expression.",
        "icon": "tabler:circle-dot",
    },
    "lollipop": {
        "label": "Lollipop / needle plot",
        "description": "Variant tracks along genes: vertical stems coloured by consequence, marker size = effect.",
        "icon": "tabler:chart-arcs",
    },
    "qq": {
        "label": "QQ plot",
        "description": "Quantile-quantile of -log10(p) vs uniform null — standard p-value distribution QC.",
        "icon": "tabler:chart-line",
    },
    "sunburst": {
        "label": "Sunburst",
        "description": "Hierarchical taxonomy / pathway viewer — concentric rings from root to leaf.",
        "icon": "tabler:sun",
    },
    "oncoplot": {
        "label": "Oncoplot",
        "description": "Sample × gene mutation matrix with discrete mutation-type colours and frequency strips.",
        "icon": "tabler:grid-pattern",
    },
    "coverage_track": {
        "label": "Coverage track",
        "description": "Read depth / signal along a coordinate axis. Optional per-sample faceting and categorical annotation lane (gene region, peak class, …).",
        "icon": "tabler:chart-area-line",
    },
    "sankey": {
        "label": "Sankey (categorical flow)",
        "description": "Flow across N ordered categorical levels (e.g. sample → lineage → clade). Server-side aggregation, client-side colour / opacity tweaks.",
        "icon": "tabler:chart-sankey",
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
            # Entries without an explicit category are pure visualisations.
            "category": meta.get("category", "plot"),
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


_CACHE_KEY_VERSION = "v3"


def _compute_cache_key(payload: dict) -> str:
    """Stable key for the compute_results cache.

    Hashes the full payload sort-stably so every tunable (embedding params,
    UpSet sort_by/min_size/colour_by, ComplexHeatmap normalize/cluster_*,
    filter_metadata) participates in the key. Bump ``_CACHE_KEY_VERSION``
    when the task contract changes in a way that invalidates prior entries
    (e.g. fixing a bug that produced stuck "pending" docs).
    """
    import hashlib
    import json as _json

    blob = _json.dumps({"_v": _CACHE_KEY_VERSION, "p": payload}, sort_keys=True, default=str)
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

    from depictio.api.v1.celery_tasks import compute_embedding as compute_task
    from depictio.api.v1.db import db

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
    # Race-safe: handle a concurrent dispatch with the same cache_key by
    # falling through to the cache-hit return path.
    from pymongo.errors import DuplicateKeyError

    try:
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
    except DuplicateKeyError:
        existing = cache.find_one({"_id": cache_key}) or {}
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }

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

    from depictio.api.v1.celery_tasks import compute_complex_heatmap as compute_task
    from depictio.api.v1.db import db

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

    # Race-safe insert: two concurrent dispatches with the same key (e.g.
    # React StrictMode double-mount in dev) both pass the find_one check.
    # Use upsert + insert-only path to dedupe — second caller falls into
    # the find_one branch.
    from pymongo.errors import DuplicateKeyError

    try:
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
    except DuplicateKeyError:
        existing = cache.find_one({"_id": cache_key}) or {}
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }
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
                {
                    "$set": {
                        "status": "done",
                        "result": result,
                        "completed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {"job_id": job_id, "status": "done", "result": result}
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


@advanced_viz_endpoint_router.post("/compute_upset")
def dispatch_compute_upset(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Dispatch an UpSet-plot Celery task. Same dispatch + poll + cache
    contract as ``compute_complex_heatmap`` (cache namespace = upset_plot)."""
    import time
    from datetime import datetime, timezone

    from depictio.api.v1.celery_tasks import compute_upset as compute_task
    from depictio.api.v1.db import db

    if not payload.get("wf_id") or not payload.get("dc_id"):
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")

    cache = db["compute_results"]
    payload_for_key = dict(payload)
    payload_for_key.setdefault("method", "upset_plot")
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

    from pymongo.errors import DuplicateKeyError

    try:
        cache.insert_one(
            {
                "_id": cache_key,
                "status": "pending",
                "method": "upset_plot",
                "created_at": datetime.now(timezone.utc),
                "payload": {
                    "wf_id": str(payload["wf_id"]),
                    "dc_id": str(payload["dc_id"]),
                    "method": "upset_plot",
                },
            }
        )
    except DuplicateKeyError:
        existing = cache.find_one({"_id": cache_key}) or {}
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }
    started = time.monotonic()
    async_result = compute_task.apply_async(args=[payload])
    cache.update_one({"_id": cache_key}, {"$set": {"celery_task_id": async_result.id}})
    logger.info(
        "compute_upset dispatched: cache_key=%s task_id=%s (%.2fs)",
        cache_key,
        async_result.id,
        time.monotonic() - started,
    )
    return {"job_id": cache_key, "status": "pending", "from_cache": False}


@advanced_viz_endpoint_router.get("/compute_upset/{job_id}")
def poll_compute_upset(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched UpSet compute."""
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
                {
                    "$set": {
                        "status": "done",
                        "result": result,
                        "completed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {"job_id": job_id, "status": "done", "result": result}
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


def _dispatch_compute(
    payload: dict,
    method_name: str,
    compute_task,
) -> dict[str, Any]:
    """Shared dispatch helper for Celery-backed advanced viz endpoints.

    Encapsulates the cache-key lookup + race-safe insert + apply_async +
    cache-id mirror pattern used by every compute_*  endpoint here. Kept
    private to this module — the endpoints themselves stay thin wrappers
    so they remain discoverable via FastAPI's normal route registration.
    """
    import time
    from datetime import datetime, timezone

    from pymongo.errors import DuplicateKeyError

    from depictio.api.v1.db import db

    if not payload.get("wf_id") or not payload.get("dc_id"):
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")

    cache = db["compute_results"]
    cache_key = _compute_cache_key({**payload, "method": payload.get("method", method_name)})

    def _from_cache(existing: dict) -> dict[str, Any]:
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }

    existing = cache.find_one({"_id": cache_key})
    if existing:
        return _from_cache(existing)

    try:
        cache.insert_one(
            {
                "_id": cache_key,
                "status": "pending",
                "method": method_name,
                "created_at": datetime.now(timezone.utc),
                "payload": {
                    "wf_id": str(payload["wf_id"]),
                    "dc_id": str(payload["dc_id"]),
                    "method": method_name,
                },
            }
        )
    except DuplicateKeyError:
        return _from_cache(cache.find_one({"_id": cache_key}) or {})

    started = time.monotonic()
    async_result = compute_task.apply_async(args=[payload])
    cache.update_one({"_id": cache_key}, {"$set": {"celery_task_id": async_result.id}})
    logger.info(
        "%s dispatched: cache_key=%s task_id=%s (%.2fs)",
        method_name,
        cache_key,
        async_result.id,
        time.monotonic() - started,
    )
    return {"job_id": cache_key, "status": "pending", "from_cache": False}


def _poll_compute(job_id: str) -> dict[str, Any]:
    """Shared poll helper — mirror of the per-endpoint poll body."""
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
                {
                    "$set": {
                        "status": "done",
                        "result": result,
                        "completed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {"job_id": job_id, "status": "done", "result": result}
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


@advanced_viz_endpoint_router.post("/compute_coverage_track")
def dispatch_compute_coverage_track(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Dispatch a coverage-track aggregation Celery task."""
    from depictio.api.v1.celery_tasks import compute_coverage_track as compute_task

    return _dispatch_compute(payload, "coverage_track", compute_task)


@advanced_viz_endpoint_router.get("/compute_coverage_track/{job_id}")
def poll_compute_coverage_track(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched coverage-track compute."""
    return _poll_compute(job_id)


@advanced_viz_endpoint_router.post("/compute_sankey")
def dispatch_compute_sankey(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Dispatch a Sankey / categorical-flow Celery task."""
    from depictio.api.v1.celery_tasks import compute_sankey as compute_task

    return _dispatch_compute(payload, "sankey", compute_task)


@advanced_viz_endpoint_router.get("/compute_sankey/{job_id}")
def poll_compute_sankey(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched Sankey compute."""
    return _poll_compute(job_id)


@advanced_viz_endpoint_router.get(
    "/phylogeny/{data_collection_id}/newick", response_class=PlainTextResponse
)
def get_phylogeny_newick(
    data_collection_id: PyObjectId,
    current_user=Depends(get_user_or_anonymous),
) -> str:
    """Return the raw Newick string for a phylogeny DC.

    Resolves the file location in two ways: (1) prefer the file registered
    by the CLI scan in ``files_collection``; (2) for reference datasets
    (seeded via db_init, never CLI-scanned), traverse the project document
    to find the matching DC under ``workflows[].data_collections[]`` and
    read its ``config.scan.scan_parameters.filename``. DCs are stored
    embedded in the project — there is no top-level ``data_collections``
    document for them — so we can't ``find_one({"_id": dc_oid})`` directly.

    Returns local file contents directly; stream S3-hosted trees via boto3.
    """
    from depictio.api.v1.db import files_collection, projects_collection

    try:
        dc_oid = ObjectId(str(data_collection_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid dc_id: {exc}") from exc

    # Build a list of candidate paths and try each. The CLI scan records the
    # *host* path it saw when the user ran depictio-cli on their laptop
    # (``/Users/.../depictio/...``); the backend in Docker can't read that.
    # The project's scan_parameters.filename is the canonical container path
    # (``/app/depictio/...``), so we prefer files_collection when its path is
    # readable and fall through to the project doc otherwise.
    candidates: list[str] = []

    file_doc = files_collection.find_one({"data_collection_id": dc_oid})
    if file_doc and file_doc.get("file_location"):
        candidates.append(str(file_doc["file_location"]))

    project_doc = projects_collection.find_one(
        {"workflows.data_collections._id": dc_oid},
    )
    if project_doc:
        for wf in project_doc.get("workflows", []) or []:
            for dc in wf.get("data_collections", []) or []:
                dc_id_in_doc = dc.get("_id") or dc.get("id")
                if dc_id_in_doc != dc_oid:
                    continue
                scan_cfg = ((dc.get("config") or {}).get("scan") or {}).get("scan_parameters") or {}
                fname = scan_cfg.get("filename")
                if fname and fname not in candidates:
                    candidates.append(str(fname))

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail="Phylogeny file not registered (no entry in files_collection and no scan_parameters.filename in the project's DC config).",
        )

    # Resolve to the first existing local path (or any s3:// URL — those go
    # through boto3 below). Records the chosen path for the read block.
    file_path: str | None = None
    for c in candidates:
        if c.startswith("s3://"):
            file_path = c
            break
        try:
            if os.path.exists(c):
                file_path = c
                break
        except OSError:
            continue

    if not file_path:
        raise HTTPException(
            status_code=404,
            detail=(
                "Phylogeny file location resolved but none of the candidate paths "
                f"exist on the backend filesystem: {candidates}"
            ),
        )

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
