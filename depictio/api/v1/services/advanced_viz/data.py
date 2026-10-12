"""Load the tidy column payload an advanced visualisation is built from.

The export reaches the same data the dashboard does by calling the
``POST /advanced_viz/data`` handler directly. That handler owns everything a
second copy would drift from: the access check, link-filter resolution, the
schema guard on filter columns, and the per-kind reduction policy
(``models/components/advanced_viz/sampling.py``) that keeps a volcano's tail
whole and refuses to sample a kind whose renderer sums its rows.

An earlier version of this module copied the route's loader, including the
100k-row cap it used to apply. That cap was a *prefix* of the Delta scan, not
a sample, and main has since replaced it; a copy would have kept serving the
biased subset to exports only.

Output is column-oriented (``{col: [values]}``) because that is what the React
renderers consume, and keeping one shape means the Python figure builders and
the TypeScript ones start from identical input.
"""

from __future__ import annotations

from typing import Any


def load_tidy_columns(
    *,
    wf_id: str,
    dc_id: str,
    columns: list[str],
    filter_metadata: list[dict] | None,
    current_user: Any,
    access_token: str | None = None,
    viz_kind: str | None = None,
) -> dict[str, Any]:
    """Project ``columns`` from a data collection, filtered and reduced.

    Args:
        wf_id: Workflow id of the data collection.
        dc_id: Data collection id.
        columns: Columns to project; ones the collection lacks are dropped.
        filter_metadata: Filters already in ``_build_filter_metadata`` shape.
        current_user: Caller, checked against the collection's project.
        access_token: Forwarded to link-filter resolution.
        viz_kind: Selects the reduction policy, as the renderer's own request does.

    Returns:
        The route's body: ``{columns, rows, row_count, total_rows, sampled,
        sampling, filter_applied}``.

    Raises:
        HTTPException: 400/403/404/422 exactly as the route answers them.
    """
    from fastapi import Response

    from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import (
        fetch_advanced_viz_data,
    )

    return fetch_advanced_viz_data(
        # Absorbs the route's timing headers, which mean nothing to an export.
        response=Response(),
        payload={
            "wf_id": str(wf_id),
            "dc_id": str(dc_id),
            "columns": list(columns),
            "filter_metadata": filter_metadata or [],
            "viz_kind": viz_kind,
        },
        current_user=current_user,
        access_token=access_token,
    )
