"""Run an advanced-viz compute inline, prepared exactly as its dispatch route would.

The live viewer reaches the Celery-backed kinds through a dispatch + poll pair
(``advanced_viz_endpoints/routes.py``). An export cannot poll, so it runs the
task body synchronously — but the payload has to be prepared the way the
dispatcher prepares it first, or the export quietly differs from the dashboard:

* link-resolved filters (a filter set on ``metadata`` reaching a canonical DC
  keyed on ``sample_id``), applied by every dispatcher;
* the complex heatmap's annotation join, which turns the column names in
  ``col_annotation_cols`` into the data collection they live in. Without it the
  heatmap renders with no annotation bars at all.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

#: ``kind -> Celery task name``. ``contact_map`` and ``group_compare`` are absent
#: on purpose: their renderers dispatch per interaction (a zoom window, two
#: lasso selections), so no single precomputed result stands for the component.
COMPUTE_TASKS: dict[str, str] = {
    "complex_heatmap": "compute_complex_heatmap",
    "upset_plot": "compute_upset",
    "sankey": "compute_sankey",
    "embedding": "compute_embedding",
    "coverage_track": "compute_coverage_track",
}


def needs_compute(kind: str | None, config: dict) -> bool:
    """Whether the renderer of ``kind`` reads a compute result rather than tidy rows.

    An embedding computes only in live mode (``compute_method`` set); a
    precomputed one reads its coordinates as rows like any other kind.
    """
    if kind == "embedding":
        return bool(config.get("compute_method"))
    return kind in COMPUTE_TASKS


def _embedding_payload(config: dict, base: dict) -> dict:
    """The payload EmbeddingRenderer dispatches, at the config's own settings.

    The renderer builds it from the config plus slider state; an export has no
    sliders, so the config's values (the renderer's starting point) stand in.
    """
    method = config.get("compute_method")
    params: dict[str, Any] = {"n_components": 2}
    if method == "umap":
        params["n_neighbors"] = config.get("umap_n_neighbors", 15)
        params["min_dist"] = config.get("umap_min_dist", 0.1)
    elif method == "tsne":
        params["perplexity"] = config.get("tsne_perplexity", 30.0)
        params["n_iter"] = config.get("tsne_n_iter", 1000)
    elif method == "pcoa":
        params["distance"] = config.get("pcoa_distance") or "bray_curtis"
    extras = [c for c in (config.get("cluster_col"), config.get("color_col")) if c]
    return {
        **base,
        "feature_id_col": config.get("sample_id_col") or "sample_id",
        "method": method,
        "params": params,
        "extra_cols": extras,
    }


def run_compute(
    kind: str,
    component: dict,
    filter_metadata: list[dict],
    access_token: str | None,
) -> Any:
    """Return the task's result for one component, as its poll route would.

    Raises:
        HTTPException: 422 for a kind with no inline compute.
    """
    from depictio.api.v1 import celery_tasks
    from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import (
        _apply_link_filters_to_payload,
        _resolve_annotation_join,
    )

    task_name = COMPUTE_TASKS.get(kind)
    if task_name is None:
        raise HTTPException(status_code=422, detail=f"{kind} has no inline compute.")

    config = component.get("config") or {}
    base: dict[str, Any] = {
        "wf_id": str(component.get("wf_id")),
        "dc_id": str(component.get("dc_id")),
        "filter_metadata": list(filter_metadata or []),
    }
    payload = _embedding_payload(config, base) if kind == "embedding" else {**config, **base}
    _apply_link_filters_to_payload(payload, access_token, kind)
    if kind == "complex_heatmap":
        _resolve_annotation_join(payload)
    return getattr(celery_tasks, task_name).run(payload)


def embedding_rows(result: dict, config: dict) -> dict[str, list[Any]]:
    """A live embedding's compute result as the rows its renderer draws."""
    rows: dict[str, list[Any]] = {
        config.get("sample_id_col") or "sample_id": list(result.get("sample_ids") or []),
        config.get("dim_1_col") or "dim_1": list(result.get("dim_1") or []),
        config.get("dim_2_col") or "dim_2": list(result.get("dim_2") or []),
    }
    for column, values in (result.get("extras") or {}).items():
        rows[column] = list(values or [])
    return rows
