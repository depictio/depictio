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
          "theme": "light" | "dark"
        }
    """
    from depictio.dash.modules.figure_component.multiqc_vis import create_multiqc_plot

    s3_locations = payload.get("s3_locations") or []
    module = str(payload.get("module"))
    plot = str(payload.get("plot"))
    dataset = payload.get("dataset")
    theme = payload.get("theme") or "light"

    started = time.monotonic()

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
    )
    build_ms = int((time.monotonic() - started) * 1000)

    fig_dict = json.loads(fig.to_json()) if hasattr(fig, "to_json") else fig
    if isinstance(fig_dict, dict) and "layout" in fig_dict:
        fig_dict["layout"].setdefault("uirevision", "persistent")

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


# Future tasks (render endpoints) will be added in a later step.
__all__: list[str] = [
    "build_figure_preview",
    "analyze_figure_code",
    "build_multiqc_preview",
    "preview_deltatable",
]
