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

    payload: dict[str, Any] = {
        **(component.get("config") or {}),
        "wf_id": str(component.get("wf_id")),
        "dc_id": str(component.get("dc_id")),
        "filter_metadata": list(filter_metadata or []),
    }
    _apply_link_filters_to_payload(payload, access_token, kind)
    if kind == "complex_heatmap":
        _resolve_annotation_join(payload)
    return getattr(celery_tasks, task_name).run(payload)
