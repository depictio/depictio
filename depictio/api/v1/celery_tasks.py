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
        pl.Float32, pl.Float64,
        pl.Int8, pl.Int16, pl.Int32, pl.Int64,
        pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
    }
    feature_cols = [
        c for c in df.columns if c != feature_id_col and df[c].dtype in numeric_dtypes
    ]
    if not feature_cols:
        raise ValueError("compute_embedding: no numeric feature columns found in the matrix")
    df = df.select([feature_id_col] + feature_cols)

    runners = {
        "pca": (run_pca, {"n_components": 2, "scale": True}),
        "umap": (
            run_umap,
            {
                "n_components": 2,
                "n_neighbors": int(params.get("n_neighbors", 15)),
                "min_dist": float(params.get("min_dist", 0.1)),
                "metric": str(params.get("metric", "euclidean")),
            },
        ),
        "tsne": (
            run_tsne,
            {
                "n_components": 2,
                "perplexity": float(params.get("perplexity", 30.0)),
                "n_iter": int(params.get("n_iter", 1000)),
                "metric": str(params.get("metric", "euclidean")),
            },
        ),
        "pcoa": (
            run_pcoa,
            {"n_components": 2, "distance": str(params.get("distance", "bray_curtis"))},
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
            df = df.with_columns(
                [(pl.col(c) - global_min).alias(c) for c in feature_cols]
            )
    coords = runner(df, **kwargs)
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info(
        "compute_embedding[%s]: produced %d coords in %dms (params=%s)",
        method,
        coords.height,
        compute_ms,
        params,
    )

    return {
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
        pl.Float32, pl.Float64,
        pl.Int8, pl.Int16, pl.Int32, pl.Int64,
        pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
    }
    if value_columns is None:
        value_columns = [
            c for c in df.columns
            if c != index_column and c not in row_annotation_cols and df[c].dtype in numeric_dtypes
        ]
    if not value_columns:
        raise ValueError("compute_complex_heatmap: no numeric value columns found")

    pdf = df.select([index_column] + value_columns + row_annotation_cols).to_pandas()

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
        "normalize": normalize,
    }
    if row_annotation_cols:
        hm_kwargs["row_annotations"] = row_annotation_cols
    if colorscale:
        hm_kwargs["colorscale"] = colorscale

    hm = ComplexHeatmap.from_dataframe(pdf, **hm_kwargs)
    fig = hm.to_plotly()
    fig_dict = fig.to_dict()
    compute_ms = int((time.monotonic() - compute_started) * 1000)
    logger.info(
        "compute_complex_heatmap: %d×%d in %dms", len(value_columns), len(pdf), compute_ms,
    )

    return {
        "figure": fig_dict,
        "row_count": len(pdf),
        "col_count": len(value_columns),
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
]
