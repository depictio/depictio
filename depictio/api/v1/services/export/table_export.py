"""Export a table component as its rows, rather than as a rendered grid.

A ``table`` has no Plotly specification, which is why ``format=json`` refuses it.
For a long time that was also the end of the sentence, and a host page that wanted
a Depictio table had exactly one option: frame the rendered component. That works,
and it is a poor trade for a small table. Framing ships a full Depictio bundle
(several MB, its own React tree, its own AG Grid) so the host can display rows it
could have styled itself in a dozen lines, and the result is a scroll container the
host cannot theme, search, or lay out with the rest of its page.

Nothing about the data required that. ``render_table_endpoint`` already returns
``{columns, rows, total}``, and the embed builder already calls it to inline the
same rows into the frame. The rows were always there; only a way to ask for them
was missing. ``format=data`` is that way.

It is deliberately a third format rather than a second meaning for ``json``. A
caller that asks for ``json`` expects something it can hand to Plotly, and
returning rows under that name would break the promise to save inventing a word.

Paging is the caller's job and is not hidden: the response carries ``total``
alongside the ``start``/``limit`` it was served for, so a host can render the first
page immediately and decide for itself whether to ask for more. Returning an entire
delta table in one response would be the easier contract to write and the one that
falls over on the first large collection.
"""

from __future__ import annotations

from typing import Any

from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.users import User

__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "build_table_export"]

#: Rows returned when a caller names no limit. One screenful of a grid with room
#: to scroll, not a whole collection.
DEFAULT_LIMIT = 100

#: Ceiling on a single page. A host that wants more pages for more; a host that
#: asks for a million rows in one response gets this instead, with ``total`` in
#: the body saying how much it did not receive.
MAX_LIMIT = 5000


def clamp_window(start: int | None, limit: int | None) -> tuple[int, int]:
    """Normalise a requested page into one this endpoint will serve.

    Returned rather than raised: a negative offset or an oversized page is a
    caller being loose, not a caller being wrong, and the response says which
    window it actually served.
    """
    resolved_start = max(0, int(start or 0))
    resolved_limit = DEFAULT_LIMIT if limit is None else int(limit)
    resolved_limit = max(1, min(resolved_limit, MAX_LIMIT))
    return resolved_start, resolved_limit


def build_table_export(
    *,
    dashboard_id: Any,
    component_id: str,
    filters: list[dict],
    start: int,
    limit: int,
    current_user: User,
    access_token: str | None,
) -> dict[str, Any]:
    """One page of a table component's rows, plus the column definitions.

    Args:
        dashboard_id: the dashboard the component belongs to.
        component_id: the component's dashboard-internal index.
        filters: already bound by ``bind_filters``, as for every other format.
        start: row offset, already clamped by ``clamp_window``.
        limit: page size, already clamped by ``clamp_window``.
        current_user: resolved by the route's embed dependency.
        access_token: forwarded so the render path sees the same permissions.

    Returns:
        ``{"columns", "rows", "total", "start", "limit", "meta"}``. ``meta`` is
        filled in further by the route, which owns provenance and the ETag.
    """
    from fastapi import Response

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import render_table_endpoint

    result = render_table_endpoint(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters, "start": start, "limit": limit},
        # The handler uses this only to set diagnostic X-Link-* headers about
        # cross-DC translation. They belong on the response the *viewer* gets;
        # here there is nowhere for them to go, so a throwaway absorbs them.
        response=Response(),
        current_user=current_user,
        access_token=access_token,
    )

    columns = result.get("columns") or []
    rows = result.get("rows") or []
    total = result.get("total") or 0

    logger.info(
        "export: served component=%s format=data rows=%d of %s",
        component_id,
        len(rows),
        total,
    )

    return {
        "columns": columns,
        "rows": rows,
        "total": total,
        "start": start,
        "limit": limit,
        "meta": {
            "component_type": "table",
            "row_count": len(rows),
            # Says whether this page is the whole table, so a host can skip its
            # paging UI without having to compare arithmetic itself.
            "complete": start == 0 and len(rows) >= total,
            "filter_applied": bool(filters),
        },
    }
