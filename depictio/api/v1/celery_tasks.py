"""FastAPI-side Celery tasks.

Each task wraps the heavy body of a preview / render endpoint so it executes
on the Celery worker process instead of pinning a FastAPI worker.

Tasks intentionally take and return JSON-serializable dicts only — Celery is
configured for the JSON serializer by default. Endpoints stay thin: they
validate input cheaply, then `await offload_or_run(...)` to dispatch the task
and unwrap its result.

Tasks are auto-discovered when this module is imported by the Celery worker
(see `depictio.dash.celery_worker`).
"""

from __future__ import annotations

import json
import time
from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.celery_app import celery_app


def _ensure_mantine_templates() -> None:
    """Worker-side Plotly template registration. Mirrors the helper in
    `figure_endpoints.routes`. Without this, plotly express raises
    ``KeyError: 'mantine_light'`` when Depictio's theme template lookup runs."""
    import plotly.io as pio

    if "mantine_light" not in pio.templates or "mantine_dark" not in pio.templates:
        try:
            import dash_mantine_components as dmc

            dmc.add_figure_templates()
        except Exception as e:
            logger.warning(f"celery_tasks: failed to register mantine templates: {e}")


@celery_app.task(name="depictio.figure.build_preview", soft_time_limit=120, time_limit=180)
def build_figure_preview(payload: dict) -> dict:
    """Heavy body of figure preview AND figure render — same code path.

    Input shape (validated by caller):
        {
          "metadata": {                 # full figure stored_metadata or component dict
            "wf_id", "dc_id",
            "dc_config",                # optional, with delta_location fallback
            "visu_type", "dict_kwargs",
            "mode" ("ui" | "code"), "code_content",
            "selection_enabled" (optional, render only),
            "selection_column"  (optional, render only),
          },
          "filter_metadata": [...],     # cleaned filters list
          "theme": "light" | "dark"
        }

    Returns:
        {"figure": <plotly fig dict>, "metadata": {"visu_type": str, "filter_applied": bool}}
    """
    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    metadata = payload.get("metadata") or {}
    filter_metadata = payload.get("filter_metadata") or []
    theme = payload.get("theme") or "light"

    wf_id = metadata.get("wf_id")
    dc_id = metadata.get("dc_id")

    dc_config = metadata.get("dc_config") or {}
    init_data: dict[str, dict] = {}
    delta_loc = dc_config.get("delta_location")
    if not delta_loc:
        dt = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
        if dt:
            delta_loc = dt.get("delta_table_location")
    if delta_loc:
        init_data[str(dc_id)] = {
            "delta_location": delta_loc,
            "dc_type": dc_config.get("type") or "table",
            "size_bytes": dc_config.get("size_bytes", 0),
        }

    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)) if not isinstance(wf_id, ObjectId) else wf_id,
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)

    _ensure_mantine_templates()

    from depictio.dash.modules.figure_component.callbacks.core import (
        _create_figure_from_data,
        _process_code_mode_figure,
    )

    visu_type = metadata.get("visu_type", "scatter")
    dict_kwargs = metadata.get("dict_kwargs") or {}
    mode = metadata.get("mode", "ui")
    code_content = metadata.get("code_content", "")
    selection_enabled = bool(metadata.get("selection_enabled", False))
    selection_column = metadata.get("selection_column")

    build_started = time.monotonic()
    code_error: str | None = None
    if mode == "code":
        ok, fig, detected = _process_code_mode_figure(code_content, df, theme, "viewer")
        if not ok:
            # `_process_code_mode_figure` returns `(False, error_fig, None)` when
            # the user code raises (e.g. unknown column name). The error_fig
            # carries a user-facing annotation with the actual Plotly error.
            # Surface that to the preview rather than masking it as a generic
            # 500 — the React side will render the annotation just like a
            # normal figure, so the user sees what went wrong.
            if fig is None:
                raise RuntimeError("Code-mode figure failed: no code provided.")
            # Pull the human-readable error out of the annotation the helper
            # embedded so the React Code-mode Status alert can flip to red
            # with the actual message instead of falsely claiming success.
            try:
                annotations = fig.layout.annotations or ()
                for ann in annotations:
                    text = getattr(ann, "text", "") or ""
                    if "Code execution error" in text:
                        code_error = text.split("Code execution error:", 1)[-1].strip()
                        break
                if not code_error and annotations:
                    code_error = str(annotations[0].text)
            except Exception:
                code_error = "Code execution failed."
            logger.info(
                f"celery_tasks.build_figure_preview: code-mode execution failed: {code_error}"
            )
        if detected:
            visu_type = detected
    else:
        # Render path uses `selection_*`; preview path doesn't pass them. The
        # underlying helper takes both as kwargs with safe defaults, so always
        # forwarding is fine and keeps the call site type-checkable.
        fig = _create_figure_from_data(
            df=df,
            visu_type=visu_type,
            dict_kwargs=dict_kwargs,
            theme=theme,
            selection_enabled=selection_enabled,
            selection_column=selection_column,
        )
    build_ms = int((time.monotonic() - build_started) * 1000)

    if hasattr(fig, "to_json"):
        fig_dict = json.loads(fig.to_json())
    else:
        fig_dict = fig
    if isinstance(fig_dict, dict) and "layout" in fig_dict:
        fig_dict["layout"].setdefault("uirevision", "persistent")

    logger.info(
        f"celery_tasks.build_figure_preview wf={wf_id} dc={dc_id} mode={mode} "
        f"visu={visu_type} load_ms={load_ms} build_ms={build_ms}"
    )

    response_metadata: dict[str, Any] = {
        "visu_type": visu_type,
        "filter_applied": bool(filter_metadata),
    }
    if code_error:
        # Surface the underlying Plotly error to the React Code-mode Status
        # alert so it flips to red. The error figure is still in `figure` so
        # the preview pane shows the in-figure annotation as well.
        response_metadata["error"] = code_error
    return {"figure": fig_dict, "metadata": response_metadata}


@celery_app.task(name="depictio.figure.analyze_code", soft_time_limit=10, time_limit=20)
def analyze_figure_code(code: str) -> dict:
    """Heavy body of `POST /figure/analyze_code` — wraps `analyze_constrained_code`."""
    from depictio.dash.modules.figure_component.code_mode import analyze_constrained_code

    code = (code or "").strip()
    if not code:
        return {"is_valid": False, "error": "Empty code."}

    try:
        result = analyze_constrained_code(code)
    except Exception as e:
        return {"is_valid": False, "error": f"Analysis failed: {e}"}

    if isinstance(result, dict):
        return {
            "is_valid": bool(result.get("is_valid", True)),
            "error": result.get("error"),
            "visu_type": result.get("visu_type"),
            "dict_kwargs": result.get("dict_kwargs") or {},
            "warnings": result.get("warnings") or [],
        }
    if isinstance(result, tuple):
        is_valid = bool(result[0])
        return {
            "is_valid": is_valid,
            "error": None if is_valid else "Code structure failed validation.",
            "visu_type": result[1] if len(result) > 1 else None,
            "dict_kwargs": (result[2] if len(result) > 2 else {}) or {},
            "warnings": result[3] if len(result) > 3 else [],
        }
    return {"is_valid": True, "dict_kwargs": {}, "visu_type": None, "warnings": []}


@celery_app.task(name="depictio.multiqc.build_preview", soft_time_limit=120, time_limit=180)
def build_multiqc_preview(payload: dict) -> dict:
    """Heavy body of `POST /multiqc/preview`.

    Input shape:
        {
          "s3_locations": [...],
          "module": str, "plot": str,
          "dataset": str | None,
          "theme": "light" | "dark",
          "dc_id": str | None
        }
    """
    from depictio.api.cache import get_cache
    from depictio.api.v1.services import multiqc_prerender_store
    from depictio.dash.modules.figure_component.multiqc_vis import (
        MULTIQC_CACHE_TTL_SECONDS,
        _generate_figure_cache_key,
        create_multiqc_plot,
    )

    s3_locations = payload.get("s3_locations") or []
    module = str(payload.get("module"))
    plot = str(payload.get("plot"))
    dataset = payload.get("dataset")
    theme = payload.get("theme") or "light"
    dc_id = payload.get("dc_id")

    started = time.monotonic()

    # Compute the bare cache key once for non-general_stats DC requests — used
    # by the Redis/disk read paths AND the cold-build writeback below so the
    # next click on the same plot hits the warm cache instead of rebuilding.
    cache = get_cache()
    bare_key: str | None = None
    if dc_id and module != "general_stats" and plot != "general_stats":
        bare_key = _generate_figure_cache_key(
            s3_locations,
            module,
            plot,
            str(dataset) if dataset else None,
            theme,
            dc_id=str(dc_id),
        )

        # Short-circuit if the prerender pipeline has already produced this
        # exact (dc, module, plot, dataset, theme) figure. The dashboard render
        # endpoint does the same Redis-then-disk lookup.
        cached_fig = cache.get(bare_key)
        if cached_fig is not None:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                f"celery_tasks.build_multiqc_preview cache_hit=redis dc={dc_id} "
                f"module={module} plot={plot} elapsed_ms={elapsed_ms}"
            )
            if isinstance(cached_fig, dict) and "layout" in cached_fig:
                cached_fig["layout"].setdefault("uirevision", "persistent")
            return {
                "figure": cached_fig,
                "metadata": {"module": module, "plot": plot, "dataset_id": dataset},
            }
        disk_fig = multiqc_prerender_store.read_figure(str(dc_id), bare_key)
        if disk_fig is not None:
            try:
                cache.set(bare_key, disk_fig, ttl=MULTIQC_CACHE_TTL_SECONDS)
            except Exception:
                pass
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                f"celery_tasks.build_multiqc_preview cache_hit=disk dc={dc_id} "
                f"module={module} plot={plot} elapsed_ms={elapsed_ms}"
            )
            if isinstance(disk_fig, dict) and "layout" in disk_fig:
                disk_fig["layout"].setdefault("uirevision", "persistent")
            return {
                "figure": disk_fig,
                "metadata": {"module": module, "plot": plot, "dataset_id": dataset},
            }

    # General Stats Table preview branch — ``general_stats`` is not a real
    # MultiQC module so ``create_multiqc_plot`` would raise. Mirror the Dash
    # design callback (multiqc_component/callbacks/design.py:299): build the
    # JSON payload and return its violin figure so the React preview renders
    # the same Plotly trace the runtime ``MultiQCGeneralStats`` shows.
    if module == "general_stats" or plot == "general_stats":
        from depictio.dash.modules.figure_component.multiqc_vis import _get_local_path_for_s3
        from depictio.dash.modules.multiqc_component.general_stats import (
            build_general_stats_payload,
        )

        if not s3_locations:
            raise ValueError("No s3_locations resolved for general_stats preview.")
        parquet_path = _get_local_path_for_s3(s3_locations[0])
        gs_payload = build_general_stats_payload(parquet_path=parquet_path, show_hidden=True)
        violin = gs_payload.get("modes", {}).get("mean", {}).get("violin_figure") or {
            "data": [],
            "layout": {},
        }
        if isinstance(violin, dict) and "layout" in violin:
            violin["layout"].setdefault("uirevision", "persistent")
        build_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            f"celery_tasks.build_multiqc_preview general_stats "
            f"samples={len(gs_payload.get('all_samples', []))} build_ms={build_ms}"
        )
        return {
            "figure": violin,
            "metadata": {
                "module": module,
                "plot": plot,
                "dataset_id": dataset,
                "is_general_stats": True,
                "sample_count": len(gs_payload.get("all_samples", [])),
            },
        }

    fig = create_multiqc_plot(
        s3_locations=s3_locations,
        module=module,
        plot=plot,
        dataset_id=str(dataset) if dataset else None,
        theme=theme,
        dc_id=str(dc_id) if dc_id else None,
    )
    build_ms = int((time.monotonic() - started) * 1000)

    fig_dict = json.loads(fig.to_json()) if hasattr(fig, "to_json") else fig
    if isinstance(fig_dict, dict) and "layout" in fig_dict:
        fig_dict["layout"].setdefault("uirevision", "persistent")

    # Writeback after a cold build so the next click for the same plot hits
    # disk/Redis instead of paying 60s again. Same bare_key used by the read
    # paths above, so the next call's cache_hit=disk lookup finds it.
    if bare_key is not None:
        try:
            multiqc_prerender_store.write_figure(str(dc_id), bare_key, fig_dict)
        except Exception as exc:
            logger.warning(
                f"build_multiqc_preview: disk writeback failed dc={dc_id} key={bare_key}: {exc}"
            )
        try:
            cache.set(bare_key, fig_dict, ttl=MULTIQC_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.warning(
                f"build_multiqc_preview: redis writeback failed dc={dc_id} key={bare_key}: {exc}"
            )

    logger.info(
        f"celery_tasks.build_multiqc_preview module={module} plot={plot} "
        f"dataset={dataset} build_ms={build_ms}"
    )

    return {
        "figure": fig_dict,
        "metadata": {"module": module, "plot": plot, "dataset_id": dataset},
    }


@celery_app.task(name="depictio.deltatables.preview", soft_time_limit=60, time_limit=120)
def preview_deltatable(payload: dict) -> dict:
    """Heavy body of `GET /deltatables/preview/{id}`.

    Input shape:
        {"delta_table_location": str, "limit": int}
    """
    import polars as pl

    from depictio.api.v1.endpoints.deltatables_endpoints.routes import sanitize_for_json
    from depictio.api.v1.s3 import polars_s3_config

    delta_loc = payload["delta_table_location"]
    limit = max(1, min(int(payload.get("limit", 100)), 1000))

    started = time.monotonic()
    df = pl.scan_delta(delta_loc, storage_options=polars_s3_config).head(limit).collect()
    total_rows, total_cols = (
        pl.scan_delta(delta_loc, storage_options=polars_s3_config).collect().shape
    )
    rows = sanitize_for_json(df.to_dicts())
    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        f"celery_tasks.preview_deltatable rows={limit}/{total_rows} cols={total_cols} "
        f"elapsed_ms={elapsed_ms}"
    )

    return {
        "columns": df.columns,
        "rows": rows,
        "total_rows": total_rows,
        "total_columns": total_cols,
    }


@celery_app.task(
    name="depictio.advanced_viz.compute_embedding",
    soft_time_limit=600,
    time_limit=900,
)
def compute_embedding(payload: dict) -> dict:
    """Live dim-reduction for the Embedding advanced viz.

    Loads a wide sample×feature matrix DC, projects it via run_pca /
    run_umap / run_tsne / run_pcoa from depictio.recipes.lib.dimreduction,
    and returns the 2D coords in the canonical embedding shape (column-
    oriented dict).

    Input payload (JSON-serialisable):
        {
          "wf_id": str,
          "dc_id": str,                # the feature-matrix DC
          "feature_id_col": str,       # sample-id column in the matrix
          "method": "pca" | "umap" | "tsne" | "pcoa",
          "params": dict,              # per-method tunables
          "filter_metadata": [...],    # sidebar filters (optional)
        }

    Output:
        {
          "sample_ids": [str],
          "dim_1": [float],
          "dim_2": [float],
          "dim_3": [float],  # only when params.n_components == 3
        }
    """
    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite
    from depictio.recipes.lib.dimreduction import run_pca, run_pcoa, run_tsne, run_umap

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    feature_id_col = payload.get("feature_id_col") or "sample_id"
    method = (payload.get("method") or "pca").lower()
    params = payload.get("params") or {}
    filter_metadata = payload.get("filter_metadata") or []
    # Columns to pass through unchanged from the feature DC alongside the
    # computed (dim_1, dim_2). Used by the renderer to overlay cluster /
    # colour annotations on the live embedding without an extra round-trip.
    extra_cols: list[str] = list(payload.get("extra_cols") or [])

    if not wf_id or not dc_id:
        raise ValueError("compute_embedding: wf_id and dc_id are required")
    if method not in {"pca", "umap", "tsne", "pcoa"}:
        raise ValueError(f"compute_embedding: unsupported method {method!r}")

    # Resolve delta location via Mongo (same pattern as build_figure_preview
    # — keeps the Celery worker self-contained, no HTTP fallbacks).
    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_embedding: feature DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_embedding[%s]: loaded %d rows in %dms", method, df.height, load_ms)

    # Stash any pass-through columns the renderer asked for (e.g. cluster /
    # group labels for colour-coding the embedding) before reducing to the
    # numeric feature matrix.
    import polars as pl

    passthrough: dict[str, list] = {}
    if extra_cols:
        present_extras = [c for c in extra_cols if c in df.columns]
        for col in present_extras:
            passthrough[col] = df.get_column(col).to_list()

    # Reduce to sample_id + numeric features. Polars dtype check filters
    # out string/bool columns so the dim-reduction helpers don't crash on
    # non-numeric input.
    numeric_dtypes = {
        pl.Float32,
        pl.Float64,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    }
    feature_cols = [c for c in df.columns if c != feature_id_col and df[c].dtype in numeric_dtypes]
    if not feature_cols:
        raise ValueError("compute_embedding: no numeric feature columns found in the matrix")
    df = df.select([feature_id_col] + feature_cols)

    # Renderer requests `n_components` (2 or 3) via the params dict; clamped
    # to [2, 3] because that's what the renderer can plot.
    n_components = int(params.get("n_components", 2))
    if n_components not in (2, 3):
        n_components = 2

    runners = {
        "pca": (run_pca, {"n_components": n_components, "scale": True}),
        "umap": (
            run_umap,
            {
                "n_components": n_components,
                "n_neighbors": int(params.get("n_neighbors", 15)),
                "min_dist": float(params.get("min_dist", 0.1)),
                "metric": str(params.get("metric", "euclidean")),
            },
        ),
        "tsne": (
            run_tsne,
            {
                "n_components": n_components,
                "perplexity": float(params.get("perplexity", 30.0)),
                "n_iter": int(params.get("n_iter", 1000)),
                "metric": str(params.get("metric", "euclidean")),
            },
        ),
        "pcoa": (
            run_pcoa,
            {"n_components": n_components, "distance": str(params.get("distance", "bray_curtis"))},
        ),
    }
    runner, kwargs = runners[method]

    compute_started = time.monotonic()
    if method == "pcoa":
        # PCoA's Bray-Curtis distance requires non-negative values; shift
        # the matrix into the positive orthant if any negatives are present.
        import polars as pl

        mins = [df.get_column(c).min() for c in feature_cols]
        global_min = min(float(m if m is not None else 0.0) for m in mins)
        if global_min < 0:
            df = df.with_columns([(pl.col(c) - global_min).alias(c) for c in feature_cols])
    coords = runner(df, **kwargs)
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info(
        "compute_embedding[%s]: produced %d coords in %dms (params=%s)",
        method,
        coords.height,
        compute_ms,
        params,
    )

    result = {
        "sample_ids": coords["sample_id"].to_list(),
        "dim_1": coords["dim_1"].to_list(),
        "dim_2": coords["dim_2"].to_list(),
        "extras": passthrough,  # {col: [values]} aligned with sample_ids
        "method": method,
        "params": params,
        "row_count": int(coords.height),
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }
    if n_components == 3 and "dim_3" in coords.columns:
        result["dim_3"] = coords["dim_3"].to_list()
    return result


@celery_app.task(
    name="depictio.advanced_viz.compute_complex_heatmap",
    soft_time_limit=300,
    time_limit=600,
)
def compute_complex_heatmap(payload: dict) -> dict:
    """Build a ComplexHeatmap figure server-side via plotly-complexheatmap.

    Input payload:
        {
          "wf_id": str,
          "dc_id": str,                # the matrix DC
          "index_column": str,         # row-label column
          "value_columns": [str] | null,
          "row_annotation_cols": [str],
          "cluster_rows": bool,
          "cluster_cols": bool,
          "cluster_method": str,       # ward / single / complete / average
          "cluster_metric": str,       # euclidean / correlation / cosine
          "normalize": str,            # none / row_z / col_z / log1p
          "colorscale": str | null,
          "filter_metadata": [...],
        }

    Output:
        {
          "figure": <plotly figure dict>,   # straight to react-plotly.js
          "row_count": int,
          "col_count": int,
          "load_ms": int,
          "compute_ms": int,
        }
    """
    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    index_column = payload.get("index_column") or "sample_id"
    value_columns = payload.get("value_columns")
    row_annotation_cols = list(payload.get("row_annotation_cols") or [])
    cluster_rows = bool(payload.get("cluster_rows", True))
    cluster_cols = bool(payload.get("cluster_cols", True))
    cluster_method = str(payload.get("cluster_method") or "ward")
    cluster_metric = str(payload.get("cluster_metric") or "euclidean")
    normalize = str(payload.get("normalize") or "none")
    colorscale = payload.get("colorscale")
    filter_metadata = payload.get("filter_metadata") or []

    if not wf_id or not dc_id:
        raise ValueError("compute_complex_heatmap: wf_id and dc_id are required")

    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_complex_heatmap: DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    logger.info(
        "compute_complex_heatmap: dispatch dc_id=%s filter_count=%d filter_summary=%s",
        dc_id,
        len(filter_metadata),
        [
            {
                "col": (f.get("metadata") or {}).get("column_name") or f.get("column_name"),
                "type": (f.get("metadata") or {}).get("interactive_component_type")
                or f.get("interactive_component_type"),
                "value": f.get("value"),
            }
            for f in filter_metadata
        ],
    )
    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_complex_heatmap: loaded %d rows in %dms", df.height, load_ms)

    # Convert polars → pandas for plotly-complexheatmap (it accepts both but
    # pandas is its primary input). Drop non-numeric columns from the value
    # set if value_columns wasn't supplied.
    import polars as pl

    numeric_dtypes = {
        pl.Float32,
        pl.Float64,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    }
    if value_columns is None:
        value_columns = [
            c
            for c in df.columns
            if c != index_column and c not in row_annotation_cols and df[c].dtype in numeric_dtypes
        ]
    if not value_columns:
        raise ValueError("compute_complex_heatmap: no numeric value columns found")

    pdf = df.select([index_column] + value_columns + row_annotation_cols).to_pandas()

    # Translate depictio normalize vocab → plotly-complexheatmap normalize_data
    # vocab. The renderer/config offers row_z / col_z / log1p / none; the
    # library only knows row / column / global / none. log1p has no library
    # equivalent — apply it to the value matrix here and pass "none" through.
    import math

    normalize_for_lib = {"none": "none", "row_z": "row", "col_z": "column"}.get(normalize, "none")
    if normalize == "log1p":
        for _col in value_columns:
            pdf[_col] = pdf[_col].astype(float).apply(math.log1p)

    compute_started = time.monotonic()
    # Import here so the worker startup doesn't pay the cost unless this
    # task is actually invoked.
    from plotly_complexheatmap import ComplexHeatmap

    hm_kwargs: dict = {
        "index_column": index_column,
        "value_columns": value_columns,
        "cluster_rows": cluster_rows,
        "cluster_cols": cluster_cols,
        "cluster_method": cluster_method,
        "cluster_metric": cluster_metric,
        "normalize": normalize_for_lib,
    }
    if row_annotation_cols:
        # Stable categorical colour map per annotation column — keyed on the
        # FULL distinct-value universe (unfiltered) so a sidebar filter that
        # narrows the heatmap to a single cluster doesn't reshuffle the
        # annotation track's colour for that cluster. Matches the frontend
        # ``stableColorMap`` behaviour used by the scatter / rarefaction /
        # taxonomy renderers.
        # Set2 pastel — same palette family used by ``compute_upset`` annotation
        # tracks. Numeric columns are left untouched (library auto-picks bars).
        _STABLE_PALETTE = [
            "#66c2a5",
            "#fc8d62",
            "#8da0cb",
            "#e78ac3",
            "#a6d854",
            "#ffd92f",
            "#e5c494",
            "#b3b3b3",
        ]
        # Load the UNFILTERED annotation columns once via a lazy scan so the
        # universe stays invariant under sidebar filtering. Cheap — single
        # column read, no materialisation beyond unique().
        try:
            from depictio.api.v1.s3 import polars_s3_config

            unfiltered_lazy = pl.scan_delta(
                dt_doc["delta_table_location"], storage_options=polars_s3_config
            )
            anno_universes: dict[str, list[str]] = {}
            for ann_col in row_annotation_cols:
                if ann_col not in pdf.columns:
                    continue
                series = pdf[ann_col]
                if series.dtype.kind not in ("U", "S", "O"):
                    continue
                uniq_pl = (
                    unfiltered_lazy.select(pl.col(ann_col)).unique().collect()[ann_col].to_list()
                )
                anno_universes[ann_col] = sorted(str(v) for v in uniq_pl if v not in ("", None))
        except Exception as exc:  # pragma: no cover - logged + falls back
            logger.warning(
                "compute_complex_heatmap: unique-value lookup for annotations failed (%s); "
                "colours may shift under filtering",
                exc,
            )
            anno_universes = {}

        annotations_spec: dict[str, dict[str, Any]] = {}
        for ann_col in row_annotation_cols:
            if ann_col in anno_universes:
                universe = anno_universes[ann_col]
                # Library silently drops ``colors`` when ``type`` is omitted
                # (the dict path falls through to ``_infer`` which doesn't pass
                # colors). Force ``type="categorical"`` so our stable palette
                # actually reaches CategoricalTrack.
                annotations_spec[ann_col] = {
                    "type": "categorical",
                    "colors": {
                        v: _STABLE_PALETTE[i % len(_STABLE_PALETTE)] for i, v in enumerate(universe)
                    },
                }
            else:
                # Numeric / unknown — let the library auto-pick the track type.
                annotations_spec[ann_col] = {}
        hm_kwargs["row_annotations"] = annotations_spec
    if colorscale:
        hm_kwargs["colorscale"] = colorscale

    hm = ComplexHeatmap.from_dataframe(pdf, **hm_kwargs)
    fig = hm.to_plotly()
    # Round-trip through plotly's JSON serializer so numpy ndarrays in trace
    # arrays / shape coords become plain lists/numbers. Without this, Celery's
    # JSON result backend chokes with "Object of type ndarray is not JSON
    # serializable" and the task can't store its result.
    import json as _json

    import plotly.io as _pio

    fig_dict = _json.loads(_pio.to_json(fig))
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info(
        "compute_complex_heatmap: %d×%d in %dms",
        len(value_columns),
        len(pdf),
        compute_ms,
    )

    return {
        "figure": fig_dict,
        "row_count": len(pdf),
        "col_count": len(value_columns),
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }


@celery_app.task(
    name="depictio.advanced_viz.compute_upset",
    soft_time_limit=300,
    time_limit=600,
)
def compute_upset(payload: dict) -> dict:
    """Build an UpSet plot figure server-side via plotly-upset.

    Input payload:
        {
          "wf_id": str, "dc_id": str,
          "set_columns": [str] | null,
          "sort_by": "cardinality" | "degree" | "degree-cardinality" | "input",
          "sort_order": "descending" | "ascending",
          "min_size": int, "max_degree": int | null,
          "show_set_sizes": bool,
          "color_intersections_by": "none" | "set" | "degree",
          "filter_metadata": [...],
        }
    """
    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    set_columns = payload.get("set_columns")
    sort_by = str(payload.get("sort_by") or "cardinality")
    sort_order = str(payload.get("sort_order") or "descending")
    min_size = int(payload.get("min_size", 1))
    max_degree = payload.get("max_degree")
    show_set_sizes = bool(payload.get("show_set_sizes", True))
    show_values = bool(payload.get("show_values", False))
    color_intersections_by = payload.get("color_intersections_by") or "none"
    # Extra annotation tracks (per-intersection summaries). User-selected
    # non-set columns from the DC schema; library auto-detects numeric vs
    # categorical and renders a track per column above the intersection bars.
    annotation_cols = payload.get("annotation_cols") or []
    filter_metadata = payload.get("filter_metadata") or []

    if not wf_id or not dc_id:
        raise ValueError("compute_upset: wf_id and dc_id are required")

    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_upset: DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_upset: loaded %d rows in %dms", df.height, load_ms)

    pdf = df.to_pandas()
    compute_started = time.monotonic()
    from plotly_upset import UpSetPlot

    kwargs: dict = {
        "sort_by": sort_by,
        "sort_order": sort_order,
        "min_size": min_size,
        "show_set_sizes": show_set_sizes,
        "show_values": show_values,
    }
    if max_degree is not None:
        kwargs["max_degree"] = int(max_degree)
    if color_intersections_by in ("set", "degree"):
        kwargs["color_intersections_by"] = color_intersections_by

    # Distinct categorical palette for annotation tracks — picked to avoid
    # collision with the library's default UPSET_PALETTE that drives the
    # set + intersection-bar colouring. Without this, the first feature_group
    # category and the first set (contrastA) draw from the same first colour
    # and the two legends look like they describe the same partition.
    # Source: matplotlib Set2 (pastel qualitative).
    _ANNOTATION_PALETTE = [
        "#66c2a5",
        "#fc8d62",
        "#8da0cb",
        "#e78ac3",
        "#a6d854",
        "#ffd92f",
        "#e5c494",
        "#b3b3b3",
    ]

    # Route through from_dataframe when set_columns and/or annotation_cols
    # are specified — that path resolves annotation specs and wires them
    # into an UpSetAnnotation container. Falls back to the bare constructor
    # for the legacy "binary-only DataFrame" case.
    if annotation_cols or set_columns:
        annotations_spec: dict | list | None
        if annotation_cols:
            # Build {col: {"column": col, "colors": {value: hex}}} for
            # categorical columns so the library uses our pastel palette
            # instead of the default UPSET_PALETTE. Numeric columns get
            # an empty spec — the library auto-picks "box" or "bar" type.
            annotations_spec = {}
            for col in annotation_cols:
                if col not in pdf.columns:
                    continue
                series = pdf[col]
                spec: dict = {"column": col}
                # Treat object/string columns and small-cardinality ints as
                # categorical — matches the library's _infer_type heuristic.
                is_string = series.dtype.kind in ("U", "S", "O")
                is_small_int = series.dtype.kind == "i" and series.nunique() <= 10
                if is_string or is_small_int:
                    cats = sorted(str(v) for v in series.dropna().unique() if v not in ("", None))
                    spec["colors"] = {
                        cat: _ANNOTATION_PALETTE[i % len(_ANNOTATION_PALETTE)]
                        for i, cat in enumerate(cats)
                    }
                annotations_spec[col] = spec
        else:
            annotations_spec = None

        upset = UpSetPlot.from_dataframe(
            pdf,
            set_columns=list(set_columns) if set_columns else None,
            annotations=annotations_spec,
            **kwargs,
        )
    else:
        upset = UpSetPlot(pdf, **kwargs)
    # Same ndarray-safety dance as compute_complex_heatmap: round-trip
    # through plotly.io.to_json so numpy arrays serialise for the Celery
    # JSON result backend.
    import json as _json

    import plotly.io as _pio

    fig_dict = _json.loads(_pio.to_json(upset.to_plotly()))
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info("compute_upset: built figure in %dms", compute_ms)

    return {
        "figure": fig_dict,
        "row_count": len(pdf),
        "set_count": len(set_columns) if set_columns else None,
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }


@celery_app.task(
    name="depictio.advanced_viz.compute_coverage_track",
    soft_time_limit=180,
    time_limit=300,
)
def compute_coverage_track(payload: dict) -> dict:
    """Aggregate coverage values along a coordinate axis.

    Input payload:
        {
          "wf_id": str, "dc_id": str,
          "chromosome_col": str, "position_col": str, "value_col": str,
          "end_col": str | null,
          "sample_col": str | null, "category_col": str | null,
          "chromosomes_filter": [str] | null,
          "samples_filter": [str] | null,
          "smoothing_window": int (0 disables),
          "max_rows": int | null,
          "filter_metadata": [...],
        }

    Returns column-oriented arrays plus summary stats. The renderer builds
    the Plotly figure client-side so settings like y-scale / colour-by
    don't round-trip.
    """
    import polars as pl

    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    chromosome_col = payload.get("chromosome_col")
    position_col = payload.get("position_col")
    value_col = payload.get("value_col")
    end_col = payload.get("end_col")
    sample_col = payload.get("sample_col")
    category_col = payload.get("category_col")
    chromosomes_filter = payload.get("chromosomes_filter")
    samples_filter = payload.get("samples_filter")
    # Mirror the Pydantic CoverageTrackConfig bounds (0..200). The Celery task
    # is reachable from any caller — not just the validated React payload — so
    # clamp defensively rather than trust the input.
    smoothing_window = max(0, min(200, int(payload.get("smoothing_window") or 0)))
    max_rows = int(payload.get("max_rows") or 200_000)
    filter_metadata = payload.get("filter_metadata") or []

    if not wf_id or not dc_id:
        raise ValueError("compute_coverage_track: wf_id and dc_id are required")
    if not (chromosome_col and position_col and value_col):
        raise ValueError(
            "compute_coverage_track: chromosome_col, position_col, value_col are required"
        )

    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_coverage_track: DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    project_cols = [
        c for c in (chromosome_col, position_col, value_col, end_col, sample_col, category_col) if c
    ]

    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        select_columns=project_cols,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_coverage_track: loaded %d rows in %dms", df.height, load_ms)

    compute_started = time.monotonic()

    # Per-setting filtering happens after the global filter_metadata pass.
    if chromosomes_filter:
        df = df.filter(pl.col(chromosome_col).is_in(chromosomes_filter))
    if samples_filter and sample_col:
        df = df.filter(pl.col(sample_col).is_in(samples_filter))

    # Universe summaries are computed from the post-filter frame so the UI
    # MultiSelects reflect what's actually showing.
    chromosomes = sorted(df.get_column(chromosome_col).unique().to_list()) if df.height else []
    samples: list[str] = (
        sorted(df.get_column(sample_col).unique().to_list()) if sample_col and df.height else []
    )

    sort_keys = (
        [sample_col, chromosome_col, position_col] if sample_col else [chromosome_col, position_col]
    )
    df = df.sort(sort_keys)

    if smoothing_window > 1:
        group_keys = [chromosome_col, sample_col] if sample_col else [chromosome_col]
        df = df.with_columns(
            pl.col(value_col)
            .rolling_mean(window_size=smoothing_window, min_periods=1)
            .over(group_keys)
            .alias(value_col)
        )

    if df.height > max_rows:
        # Last-ditch decimation for runaway DCs — pick every Nth row inside
        # each (sample, chrom) group so each track stays continuous.
        keep_every = max(1, df.height // max_rows)
        df = df.with_row_index("__row").filter(pl.col("__row") % keep_every == 0).drop("__row")

    rows: dict[str, list] = {}
    for col in (chromosome_col, position_col, value_col, end_col, sample_col, category_col):
        if col and col not in rows:
            rows[col] = df.get_column(col).to_list()

    # Cast the value series to Float64 before reducing so Series.mean()/max()
    # always return float | None — keeps the JSON summary single-typed.
    if df.height:
        values_f64 = df.get_column(value_col).cast(pl.Float64)
        mean_value = values_f64.mean()
        max_value = values_f64.max()
    else:
        mean_value = None
        max_value = None
    summary = {
        "row_count": int(df.height),
        "chromosomes": chromosomes,
        "samples": samples,
        "n_samples": len(samples),
        "mean_value": mean_value,
        "max_value": max_value,
    }
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info(
        "compute_coverage_track: %d rows / %d samples / %d chroms in %dms",
        df.height,
        len(samples),
        len(chromosomes),
        compute_ms,
    )

    return {
        "rows": rows,
        "columns": {
            "chromosome": chromosome_col,
            "position": position_col,
            "value": value_col,
            "end": end_col,
            "sample": sample_col,
            "category": category_col,
        },
        "summary": summary,
        "row_count": int(df.height),
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }


@celery_app.task(
    name="depictio.advanced_viz.compute_sankey",
    soft_time_limit=120,
    time_limit=240,
)
def compute_sankey(payload: dict) -> dict:
    """Aggregate flow across N ordered categorical levels into a Plotly Sankey.

    Input payload:
        {
          "wf_id": str, "dc_id": str,
          "step_cols": [str] (≥2),
          "value_col": str | null  (null → row count),
          "sort_mode": "alphabetical" | "total_flow" | "input",
          "min_link_value": float,
          "step_filters": {col: [value, ...]} | null,
          "filter_metadata": [...],
        }

    Returns a Plotly figure JSON ready for react-plotly.js plus node/link
    metadata so the renderer can recolour client-side without re-dispatching.
    """
    import polars as pl

    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    step_cols = list(payload.get("step_cols") or [])
    value_col = payload.get("value_col")
    sort_mode = str(payload.get("sort_mode") or "total_flow")
    min_link_value = max(0.0, float(payload.get("min_link_value") or 0.0))
    step_filters = payload.get("step_filters") or {}
    filter_metadata = payload.get("filter_metadata") or []

    if not wf_id or not dc_id:
        raise ValueError("compute_sankey: wf_id and dc_id are required")
    if len(step_cols) < 2:
        raise ValueError("compute_sankey: step_cols must have ≥2 columns")
    if len(set(step_cols)) != len(step_cols):
        # Duplicate step columns would land in group_by(...).rename({col: ..., col: ...})
        # where the dict literal silently drops one key and polars then raises on
        # ambiguous output names. Reject up front with a clearer message.
        raise ValueError("compute_sankey: step_cols must not contain duplicates")

    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise ValueError("compute_sankey: DC has no materialised Delta table")
    init_data = {
        str(dc_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": 0,
        }
    }

    project_cols = [*step_cols, value_col] if value_col else list(step_cols)

    started = time.monotonic()
    df = load_deltatable_lite(
        workflow_id=ObjectId(str(wf_id)),
        data_collection_id=str(dc_id),
        metadata=filter_metadata or None,
        select_columns=project_cols,
        init_data=init_data,
    )
    load_ms = int((time.monotonic() - started) * 1000)
    logger.info("compute_sankey: loaded %d rows in %dms", df.height, load_ms)

    compute_started = time.monotonic()

    # Per-step filters applied AFTER global filter_metadata.
    for col, allowed in step_filters.items():
        if col in step_cols and allowed:
            df = df.filter(pl.col(col).cast(pl.Utf8).is_in(allowed))
    # Coerce NULL and empty-string categorical values to a literal "(missing)"
    # so they remain visible in the flow — Plotly Sankey can't render NaN node
    # labels. Pure polars expressions; no Python-row UDFs.
    df = df.with_columns(
        [
            pl.when(pl.col(c).cast(pl.Utf8).fill_null("") == "")
            .then(pl.lit("(missing)"))
            .otherwise(pl.col(c).cast(pl.Utf8))
            .alias(c)
            for c in step_cols
        ]
    )

    # Materialise the weight column up-front so polars can aggregate it
    # directly — `pl.lit(1.0).sum()` errors with "cannot aggregate a literal".
    # Drop rows with a null weight before summing so a single bad row can't
    # poison the aggregate into NaN (which would JSON-serialise as null and
    # break Plotly's Sankey value array).
    if value_col:
        df = df.with_columns(pl.col(value_col).cast(pl.Float64).alias("__sk_weight")).filter(
            pl.col("__sk_weight").is_not_null()
        )
    else:
        df = df.with_columns(pl.lit(1.0).alias("__sk_weight"))

    # Build per-adjacent-pair link aggregates: (src_col, src_value, tgt_value,
    # weight). Sankey doesn't care which step a node lives in, but Plotly
    # picks deterministic positions when nodes appear in a single ordered
    # list, so we keep that order below.
    link_frames: list[pl.DataFrame] = []
    for src_col, tgt_col in zip(step_cols[:-1], step_cols[1:]):
        link_frames.append(
            df.group_by([src_col, tgt_col])
            .agg(pl.col("__sk_weight").sum().alias("value"))
            .rename({src_col: "source_value", tgt_col: "target_value"})
            .with_columns(
                [pl.lit(src_col).alias("source_col"), pl.lit(tgt_col).alias("target_col")]
            )
        )

    if link_frames:
        links_df = pl.concat(link_frames, how="vertical_relaxed")
    else:
        links_df = pl.DataFrame(
            schema={
                "source_value": pl.Utf8,
                "target_value": pl.Utf8,
                "value": pl.Float64,
                "source_col": pl.Utf8,
                "target_col": pl.Utf8,
            }
        )

    if min_link_value > 0:
        links_df = links_df.filter(pl.col("value") >= min_link_value)

    # Node universe: one node per (step, value) pair, in step order. Sort
    # values within a step by chosen mode; total_flow falls back to
    # alphabetical when there are no links to rank from.
    def _step_values(step_col: str) -> list:
        if sort_mode == "input":
            return df.get_column(step_col).unique(maintain_order=True).to_list()
        if sort_mode == "total_flow" and links_df.height > 0:
            outgoing = (
                links_df.filter(pl.col("source_col") == step_col)
                .group_by("source_value")
                .agg(pl.col("value").sum().alias("total"))
                .rename({"source_value": "label"})
            )
            incoming = (
                links_df.filter(pl.col("target_col") == step_col)
                .group_by("target_value")
                .agg(pl.col("value").sum().alias("total"))
                .rename({"target_value": "label"})
            )
            totals = (
                pl.concat([outgoing, incoming], how="vertical_relaxed")
                .group_by("label")
                .agg(pl.col("total").sum())
                .sort("total", descending=True)
            )
            return totals.get_column("label").to_list()
        return sorted(df.get_column(step_col).unique().to_list())

    node_rows: list[dict] = []
    seen: dict[tuple[str, str], int] = {}
    for step_index, step_col in enumerate(step_cols):
        for v in _step_values(step_col):
            key = (step_col, str(v))
            if key in seen:
                continue
            seen[key] = len(node_rows)
            node_rows.append({"label": str(v), "step": step_col, "step_index": step_index})

    # Resolve link source/target to node indices.
    sources: list[int] = []
    targets: list[int] = []
    values: list[float] = []
    link_labels: list[str] = []
    for row in links_df.iter_rows(named=True):
        sk = (row["source_col"], str(row["source_value"]))
        tk = (row["target_col"], str(row["target_value"]))
        if sk not in seen or tk not in seen:
            continue
        sources.append(seen[sk])
        targets.append(seen[tk])
        values.append(float(row["value"]))
        link_labels.append(f"{row['source_value']} → {row['target_value']}")

    # Plotly figure — minimal layout, renderer adds template / dark mode.
    fig_dict = {
        "data": [
            {
                "type": "sankey",
                "arrangement": "snap",
                "node": {
                    "label": [n["label"] for n in node_rows],
                    "pad": 14,
                    "thickness": 18,
                },
                "link": {
                    "source": sources,
                    "target": targets,
                    "value": values,
                    "label": link_labels,
                },
            }
        ],
        "layout": {"font": {"size": 12}, "margin": {"l": 8, "r": 8, "t": 24, "b": 8}},
    }

    compute_ms = int((time.monotonic() - compute_started) * 1000)
    total_flow = float(sum(values)) if values else 0.0
    logger.info(
        "compute_sankey: %d nodes / %d links / total flow %.1f in %dms",
        len(node_rows),
        len(values),
        total_flow,
        compute_ms,
    )

    return {
        "figure": fig_dict,
        "nodes": node_rows,
        "step_cols": step_cols,
        "node_count": len(node_rows),
        "link_count": len(values),
        "total_flow": total_flow,
        "row_count": int(df.height),
        "load_ms": load_ms,
        "compute_ms": compute_ms,
    }


__all__: list[str] = [
    "build_figure_preview",
    "analyze_figure_code",
    "build_multiqc_preview",
    "preview_deltatable",
    "compute_embedding",
    "compute_complex_heatmap",
    "compute_upset",
    "compute_coverage_track",
    "compute_sankey",
]
