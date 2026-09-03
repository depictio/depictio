"""Prove a filled component renders, before the generated draft is saved.

The generator's checking stage. `dashboard_gen` already validates a component
offline (`validate_envelope`, the loader `depictio-cli dashboard import` uses)
and against its collection's columns (`check_against_schema`). Those two catch
a component that is malformed or bound to a column that is not there. Neither
catches a component that is well formed, correctly bound and still 500s on
render, which is exactly the shape of the `rarefaction` advanced viz that
reached a saved penguins dashboard: every role bound to a real float column,
two of them bound to the *same* real float column, and `/advanced_viz/data`
raising `ComputeError: the name 'bill_depth_mm' ... is duplicate`. Only calling
the render path finds that.

Three properties are load-bearing, and each cost something to learn:

* `probe_component` never raises. Every probe body runs inside one try/except
  and an unexpected exception becomes a returned message. A probe that raised
  would abort the whole generation over one component the generator was about
  to report on and repair anyway.
* Every probe calls the render path IN PROCESS. It never issues an HTTP request
  back at this API. The AI package already documents why on `init_data_for_dc`
  in context.py: a self-call made from inside a request handler cannot be
  served while the caller holds the event loop, so it does not 401, it times
  out after httpx's default five seconds and surfaces as a generic read error.
* The module stays free of FastAPI. It imports functions that happen to live in
  route modules, but it takes no `Request` and no access token: it runs in the
  generation's worker thread with the `User` object in hand and no dashboard id
  yet. Where a route body writes response headers, it is handed a stand-in
  namespace with a plain dict.

Heavy route and Delta modules are imported inside the probe bodies, the way the
rest of ai_endpoints does it, so importing this module stays cheap.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

from bson import ObjectId

logger = logging.getLogger(__name__)

# How many rows a probe may pull. One row exercises the projection, the
# filters and the renderer's own column handling; the frame the real render
# needs is loaded (and cached) when someone opens the dashboard.
PROBE_ROW_LIMIT = 1

# Reasons are quoted into a repair prompt, so they are trimmed to something a
# model can act on rather than a full traceback message.
MAX_REASON_CHARS = 300

# Interactive widgets that fetch a list of values before they can be drawn.
VALUE_LISTING_WIDGETS: frozenset[str] = frozenset(
    {"MultiSelect", "Select", "SegmentedControl", "TextInput"}
)
# Widgets that need the column's bounds instead of its values.
RANGE_WIDGETS: frozenset[str] = frozenset(
    {"Slider", "RangeSlider", "DatePicker", "DateRangePicker", "Timeline", "TimelineSlider"}
)
# Widgets that fetch nothing at all, so there is nothing to probe.
NO_FETCH_WIDGETS: frozenset[str] = frozenset({"Checkbox", "Switch"})

# Component types deliberately left unprobed, and why. None of them has a cheap
# in-process call that is worth its cost here:
#   * text has no data source at all.
#   * map's render endpoint does an unprojected full load of the collection,
#     which is more expensive than the component it would be vetting.
#   * image resolves and fetches objects from S3.
#   * multiqc reads the ingested report parquet rather than a Delta table.
# The door is left open: give one of them a probe by writing the function and
# adding it to `_PROBES` below. Nothing else has to change.
NO_PROBE_TYPES: frozenset[str] = frozenset({"text", "image", "map", "multiqc"})

# Advanced-viz config fields holding a list of columns rather than a single
# one. They have no `<role>_col` spelling, so `role_config_key` does not reach
# them (see `depictio/models/components/advanced_viz/catalog.py`), but the
# renderer projects them all the same.
_LIST_CONFIG_KEYS: tuple[str, ...] = (
    "rank_cols",
    "step_cols",
    "value_columns",
    "row_annotation_cols",
)


def probe_component(component: dict[str, Any], ctx: Any | None, user: Any) -> str | None:
    """None when the component renders (or has no cheap probe), else a short reason.

    `component` is the filled lite component dict, as the generator holds it
    after `validate_component`: `component_type` plus that type's own fields.
    `ctx` is the component's `DataContext` (context.py), which carries the
    `data_collection_id` and `workflow_id` the render path needs; `user` is the
    requesting user object, passed to the route bodies in place of the
    dependency FastAPI would have injected.

    A probe answering None means "nothing here says this component is broken",
    never "this component is perfect": several types have no probe, and the
    probes that exist read one row. That asymmetry is the point. A false
    negative costs a broken tile the generator would have shipped anyway; a
    false positive would throw away a component that renders.
    """
    component_type = str((component or {}).get("component_type") or "")
    if component_type in NO_PROBE_TYPES:
        return None
    probe = _PROBES.get(component_type)
    if probe is None:
        # An unknown type, or one the generator learns to emit before this
        # module learns to probe it. Silence is the safe answer.
        return None
    if ctx is None or not getattr(ctx, "data_collection_id", None):
        # Nothing to probe against: every probe below reads a data collection.
        return None
    try:
        return probe(component, ctx, user)
    except Exception as exc:  # noqa: BLE001, the contract is that this never raises
        logger.warning(
            "dashboard probe: %s component %r failed: %s",
            component_type,
            (component or {}).get("tag"),
            exc,
            exc_info=True,
        )
        return _reason(component_type, exc)


def _reason(component_type: str, exc: BaseException) -> str:
    """Turn an exception into the one line the repair prompt gets to read."""
    # An HTTPException-shaped error carries the message the endpoint would have
    # returned to the viewer; read it by duck typing so FastAPI stays out of
    # this module's imports.
    detail = getattr(exc, "detail", None)
    text = str(detail) if detail else f"{type(exc).__name__}: {exc}"
    text = " ".join(text.split())
    if len(text) > MAX_REASON_CHARS:
        text = text[: MAX_REASON_CHARS - 3].rstrip() + "..."
    return f"{component_type} did not render: {text}"


def _run_sync(make_coroutine: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Run one coroutine to completion from this synchronous module.

    The generation's checking stage runs in a worker thread with no event loop,
    where `asyncio.run` is exactly right. A caller probing from inside a running
    loop would instead make `asyncio.run` raise, and the wrapper above would
    report that as the component failing to render, so that case gets its own
    loop on its own thread. The argument is a factory rather than a coroutine
    so the unused one is never created and Python never warns about a coroutine
    that was never awaited.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coroutine())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(make_coroutine())).result()


def _advanced_viz_columns(kind: str, config: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """The columns an advanced viz projects, and its role -> column map.

    Roles are read through `role_config_key`, the single mapping the React
    builder, the catalog preview and the lite model's `use:` expansion all
    spell bindings through, so a catalog-sourced component and a ranked one are
    read identically.

    The column list is deliberately NOT deduplicated. It is what the renderer
    sends, and a renderer that projects one column into two roles sends it
    twice: that is precisely the payload `/advanced_viz/data` used to raise on,
    so a probe that quietly collapsed it would pass a component the viewer
    cannot draw.
    """
    from depictio.models.components.advanced_viz.catalog import role_config_key
    from depictio.models.components.advanced_viz.schemas import role_dtype_specs

    roles: dict[str, str] = {}
    columns: list[str] = []
    for role in role_dtype_specs(kind):  # type: ignore[arg-type]
        value = config.get(role_config_key(kind, role))
        if isinstance(value, str) and value:
            roles[role] = value
            columns.append(value)
    for key in _LIST_CONFIG_KEYS:
        for value in config.get(key) or []:
            if isinstance(value, str) and value:
                columns.append(value)
    return columns, roles


def _column_specs(data_collection_id: str, column: str) -> dict[str, Any] | None:
    """The latest aggregation's stored spec for one column, or None when absent.

    Read straight from the `deltatables` document the ingest writes, so no
    frame is loaded. `None` means the collection has no aggregation or does not
    know that column at all, which are different from a known column with no
    bounds.
    """
    from depictio.api.v1.db import deltatables_collection

    doc = deltatables_collection.find_one(
        {"data_collection_id": ObjectId(data_collection_id)},
        {"aggregation.aggregation_columns_specs": 1},
    )
    aggregations = (doc or {}).get("aggregation") or []
    if not aggregations:
        return None
    for spec in (aggregations[-1] or {}).get("aggregation_columns_specs") or []:
        if isinstance(spec, dict) and spec.get("name") == column:
            return spec.get("specs") or {}
    return None


def _probe_figure(component: dict[str, Any], ctx: Any, user: Any) -> str | None:
    """Build the figure through the exact body the preview and render share.

    `build_figure_preview` is a Celery task; calling the task object runs its
    body in this process, no broker involved, which is what the probe wants.
    It projects to the bound columns and caps the rows it loads, and its Delta
    read goes through the same Redis-backed cache the dashboard will hit.

    One gap worth naming: a code-mode figure whose code raises does not raise
    here. `build_figure_preview` catches it and returns a figure carrying the
    error as an annotation, because that is how the builder's Code-mode status
    alert learns what went wrong. Such a figure renders, so this probe passes
    it; catching it would mean teaching the probe to read annotations.
    """
    from depictio.api.v1.celery_tasks import build_figure_preview

    build_figure_preview(
        {
            "metadata": {
                "component_type": "figure",
                "wf_id": str(ctx.workflow_id),
                "dc_id": str(ctx.data_collection_id),
                "visu_type": component.get("visu_type") or "scatter",
                "dict_kwargs": component.get("dict_kwargs") or {},
                "mode": component.get("mode") or "ui",
                "code_content": component.get("code_content") or "",
            },
            "filter_metadata": [],
            "theme": "light",
        }
    )
    return None


def _probe_advanced_viz(component: dict[str, Any], ctx: Any, user: Any) -> str | None:
    """Fetch one row through `/advanced_viz/data`, the call that fails today.

    The endpoint body is called directly with the bound columns, the viz kind
    and the role map, under an explicit `limit_rows` so no sampling policy is
    chosen and the Delta read is one row wide. `response` is a stand-in for the
    FastAPI `Response` the route writes its timing headers to, and
    `access_token` is None because the probe carries no token: it is only used
    to resolve cross-DC link filters, and there are no filters here.
    """
    from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import fetch_advanced_viz_data

    config = component.get("config") or {}
    kind = str(component.get("viz_kind") or config.get("viz_kind") or "")
    if not kind:
        return "advanced_viz: no viz_kind to render"
    columns, roles = _advanced_viz_columns(kind, config)
    if not columns:
        # A kind that binds no single-column role (upset_plot enumerates its own
        # binary columns at compute time, sankey validates its steps there).
        # `/data` would 400 on an empty column list, which says nothing at all
        # about the component.
        return None

    fetch_advanced_viz_data(
        response=SimpleNamespace(headers={}),
        payload={
            "wf_id": str(ctx.workflow_id),
            "dc_id": str(ctx.data_collection_id),
            "columns": columns,
            "viz_kind": kind,
            "roles": roles,
            "limit_rows": PROBE_ROW_LIMIT,
        },
        current_user=user,
        access_token=None,
    )
    return None


def _probe_table(component: dict[str, Any], ctx: Any, user: Any) -> str | None:
    """Read the Delta schema, then one sorted page of the visible columns.

    `schema_deltatable_lite` reads the Delta log alone (no rows, no cache
    interaction), so the missing-column case is answered before anything is
    loaded. The paged `load_sorted_deltatable_lite` then exercises the sort and
    projection the AG Grid block fetch will make, one row deep.
    """
    from depictio.api.v1.deltatables_utils import (
        load_sorted_deltatable_lite,
        schema_deltatable_lite,
    )
    from depictio.api.v1.endpoints.ai_endpoints.context import init_data_for_dc

    dc_id = str(ctx.data_collection_id)
    wf_oid = ObjectId(str(ctx.workflow_id))
    init_data = init_data_for_dc(dc_id)

    schema = schema_deltatable_lite(wf_oid, dc_id, init_data=init_data)
    if not schema:
        return "table: the data collection's Delta schema could not be read"

    columns = [c for c in (component.get("columns") or []) if isinstance(c, str) and c]
    missing = [c for c in columns if c not in schema]
    if missing:
        return f"table: column(s) {', '.join(missing)} are not in the data collection"

    load_sorted_deltatable_lite(
        workflow_id=wf_oid,
        data_collection_id=dc_id,
        sort_by=columns[0] if columns else next(iter(schema)),
        select_columns=columns or None,
        init_data=init_data,
        page=(0, PROBE_ROW_LIMIT),
    )
    return None


def _probe_interactive(component: dict[str, Any], ctx: Any, user: Any) -> str | None:
    """Fetch what the widget needs before it can draw itself, and nothing else.

    A value-listing widget (MultiSelect, Select, SegmentedControl, a TextInput
    autocomplete) fetches its options, so the probe fetches one option through
    `get_unique_values`, which is Redis-cached under a key that includes the
    limit, so this entry cannot displace the viewer's own. A Slider,
    RangeSlider or date picker needs the column's bounds instead, and those are
    already precomputed in the collection's stored column specs, so the probe
    reads Mongo rather than the frame. Checkbox and Switch fetch nothing.
    """
    widget = str(component.get("interactive_component_type") or "")
    column = str(component.get("column_name") or "")
    if not column:
        return "interactive: no column_name to filter on"
    if widget in NO_FETCH_WIDGETS:
        return None

    if widget in RANGE_WIDGETS:
        specs = _column_specs(str(ctx.data_collection_id), column)
        if specs is None:
            return (
                f"interactive: '{column}' has no stored column spec in the data collection, "
                f"so {widget} cannot resolve its range"
            )
        if specs.get("min") is None or specs.get("max") is None:
            return f"interactive: {widget} on '{column}' has no min/max in the collection specs"
        return None

    if widget and widget not in VALUE_LISTING_WIDGETS:
        # A widget flavour this module does not know yet. Say nothing rather
        # than guess which of the two fetches it makes.
        return None

    from depictio.api.v1.endpoints.deltatables_endpoints.routes import get_unique_values

    dc_oid = ObjectId(str(ctx.data_collection_id))
    filter_expr = component.get("filter_expr") or None
    _run_sync(
        lambda: get_unique_values(
            dc_oid,  # type: ignore[arg-type]
            column=column,
            limit=PROBE_ROW_LIMIT,
            filter_expr=filter_expr,
            current_user=user,
        )
    )
    return None


def _probe_card(component: dict[str, Any], ctx: Any, user: Any) -> str | None:
    """Run the card's aggregation through the one path that needs no dashboard id.

    `get_card_metric` is the builder's live preview: it permission-checks the
    collection, opens the Delta scan, projects to the columns the layout reads
    and refuses with a 404 when the hero column is not among them. The card's
    own `secondary_layout` is used when it is one this endpoint computes, so
    the probe exercises the real payload builder; otherwise the preview-only
    `hero` pseudo-layout computes the hero scalar alone.

    A `None` value coming back is not a failure. `hero_value` answers None for
    the aggregations that have no lazy expression form (`mode`,
    `box_plot_stats`), which the saved card computes by another route.
    """
    from depictio.api.v1.endpoints.deltatables_endpoints.routes import get_card_metric
    from depictio.api.v1.services.card_metrics import NUMERIC_LAYOUTS

    column = str(component.get("column_name") or "")
    if not column:
        return "card: no column_name to aggregate"

    layout = str(component.get("secondary_layout") or "")
    request: dict[str, Any] = {
        "layout": layout if layout in NUMERIC_LAYOUTS else "hero",
        "column": column,
        "aggregation": component.get("aggregation") or "count",
    }
    for key in ("attrition_cols", "trend_col", "threshold_value", "threshold_direction"):
        if component.get(key) is not None:
            request[key] = component[key]

    dc_oid = ObjectId(str(ctx.data_collection_id))
    _run_sync(
        lambda: get_card_metric(
            dc_oid,  # type: ignore[arg-type]
            request,
            user,
        )
    )
    return None


# Declared last so every probe above is defined. Add a type here to probe it;
# anything absent (including every member of NO_PROBE_TYPES) answers None.
_PROBES: dict[str, Callable[[dict[str, Any], Any, Any], str | None]] = {
    "figure": _probe_figure,
    "advanced_viz": _probe_advanced_viz,
    "table": _probe_table,
    "interactive": _probe_interactive,
    "card": _probe_card,
}
