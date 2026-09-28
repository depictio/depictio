"""Agent tools that read data: a component's data, a collection's profile, Polars queries.

Permission is the REST one: dashboards through ``load_viewable_dashboard``
(``check_project_permission(..., "viewer")``), data collections through
``ai_endpoints.context._resolve_dc_and_project``. Loads go through
``load_deltatable_lite`` with the viewer's filter metadata, so a filter narrows
the rows exactly as the matching dashboard filter would. Every load runs in a
worker thread under ``settings.mcp.query_timeout_s``; model-authored code runs
in the killable ``AnalysisSandbox`` child.

Cross-collection link filters are not resolved here: the render routes need
the caller's raw access token for that, and a tool only has the user. Filters
on columns the collection lacks are reported under ``filters_ignored``.
"""

from __future__ import annotations

import asyncio
import math
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from typing import Any, Literal, TypeVar

import polars as pl
from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.envelope import clean_text, untrusted
from depictio.api.v1.agents.registry import ToolError, agent_tool
from depictio.api.v1.agents.tools.discovery import (
    FIGURE_ROLE_KEYS,
    dc_index,
    dc_schema,
    find_component,
    load_viewable_dashboard,
)
from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import projects_collection
from depictio.api.v1.deltatables_utils import (
    clean_filter_payload,
    count_deltatable_lite,
    load_deltatable_lite,
    schema_deltatable_lite,
)
from depictio.api.v1.endpoints.ai_endpoints.context import (
    _resolve_dc_and_project,
    _summarize_columns,
    build_data_context,
    init_data_for_dc,
    redact_pii,
)
from depictio.api.v1.endpoints.ai_endpoints.sandbox import AnalysisSandbox, FrameSpec
from depictio.models.components.filter_expr import validate_filter_expr

T = TypeVar("T")

DEFAULT_MAX_ROWS = 50
MAX_ROWS_CAP = 500
# Columns the CLI adds to every table at ingest: bookkeeping, not data, and
# their timestamps trip the PII phone pattern.
INTERNAL_COLUMNS = frozenset({"depictio_run_id", "aggregation_time"})
MAX_SHOWN_COLUMNS = 30
MAX_GROUPS = 20
# Strings at least this long are treated as free text and wrapped as untrusted.
LONG_TEXT_CHARS = 40
MAX_CONCURRENT_QUERIES = 2
# Extra wall clock for spawning the sandbox child and loading its frame, on
# top of the per-query deadline.
SANDBOX_START_ALLOWANCE_S = 30.0
MAX_CODE_CHARS = 4000

FilterOperator = Literal[
    "eq", "ne", "gt", "ge", "lt", "le", "in", "not_in", "between", "contains", "is_null", "not_null"
]
_COMPARISONS = {"ne": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}
_NUMERIC_TYPES = ("int", "uint", "float", "double", "decimal")
_COL_RE = re.compile(r"col\(\s*['\"]([^'\"]+)['\"]\s*\)")

Scalar = str | int | float | bool


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilterIn(_Args):
    column: str = Field(description="Column to filter on.")
    operator: FilterOperator = Field(
        default="eq",
        description=(
            "eq / in keep the listed values, between keeps [low, high] inclusive, contains "
            "is a substring match, ne / gt / ge / lt / le compare, not_in excludes values, "
            "is_null / not_null ignore value."
        ),
    )
    value: Scalar | list[Scalar] | None = Field(
        default=None, description="A value, a list for in / not_in, [low, high] for between."
    )

    @model_validator(mode="after")
    def _check_value(self) -> FilterIn:
        op, value = self.operator, self.value
        if op in ("is_null", "not_null"):
            return self
        if value is None:
            raise ValueError(f"operator {op} needs a value")
        if op == "between" and not (isinstance(value, list) and len(value) == 2):
            raise ValueError("between needs [low, high]")
        if op in ("in", "not_in") and not isinstance(value, list):
            self.value = [value]
        if op not in ("in", "not_in", "between") and isinstance(value, list):
            raise ValueError(f"operator {op} takes a single value")
        values = value if isinstance(value, list) else [value]
        if any(isinstance(v, float) and not math.isfinite(v) for v in values):
            raise ValueError("values must be finite")
        return self


_FILTERS_DESCRIPTION = (
    "Filters narrow the rows the same way the dashboard's filter widgets do (AND-ed)."
)
_VIEWER_FILTERS_DESCRIPTION = (
    "Filter state in the viewer's own shape, as sent to the render routes: entries of "
    "{index, column_name, interactive_component_type (MultiSelect, RangeSlider, ...), "
    "value} or {filter_expr}."
)


class ComponentDataArgs(_Args):
    dashboard_id: str = Field(description="Dashboard tab id the component lives on.")
    index: str = Field(description="Component index, as listed by get_dashboard.")
    filters: list[FilterIn] = Field(default_factory=list, description=_FILTERS_DESCRIPTION)
    viewer_filters: list[dict[str, Any]] = Field(
        default_factory=list, description=_VIEWER_FILTERS_DESCRIPTION
    )
    use_saved_filters: bool = Field(
        default=False,
        description="Also apply the values saved on this tab's filter widgets (what a fresh visitor sees).",
    )
    columns: list[str] | None = Field(
        default=None, description="Columns to return. Default: the columns the component uses."
    )
    max_rows: int = Field(
        default=DEFAULT_MAX_ROWS,
        ge=0,
        le=MAX_ROWS_CAP,
        description=f"Rows in the head sample (max {MAX_ROWS_CAP}).",
    )


class DescribeDataCollectionArgs(_Args):
    dc_id: str = Field(description="Data collection id (from get_dashboard or get_component).")
    sample_rows: int = Field(default=5, ge=0, le=20, description="Sample rows to include.")


class QueryDataArgs(_Args):
    code: str = Field(
        min_length=1,
        max_length=MAX_CODE_CHARS,
        description=(
            "Polars code; the value of the last expression is returned. `df` is the frame, "
            "`pl` is polars. Example: df.group_by('species').agg(pl.col('x').mean())"
        ),
    )
    dc_id: str | None = Field(default=None, description="Data collection to query.")
    dashboard_id: str | None = Field(
        default=None, description="Or: the dashboard tab of the component to query."
    )
    index: str | None = Field(default=None, description="With dashboard_id: the component index.")
    filters: list[FilterIn] = Field(default_factory=list, description=_FILTERS_DESCRIPTION)

    @model_validator(mode="after")
    def _one_source(self) -> QueryDataArgs:
        by_component = self.dashboard_id is not None or self.index is not None
        if (self.dc_id is None) == (not by_component):
            raise ValueError("give either dc_id, or dashboard_id and index")
        if by_component and not (self.dashboard_id and self.index):
            raise ValueError("dashboard_id and index go together")
        return self


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def run_bounded(fn: Callable[..., T], *args: Any, extra_s: float = 0.0) -> T:
    """Run blocking ``fn`` in a thread, give up after ``query_timeout_s`` (+ ``extra_s``).

    The thread itself cannot be killed; it finishes in the background. Code
    that must be stopped runs in the sandbox child instead.
    """
    timeout = settings.mcp.query_timeout_s + extra_s
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout)
    except TimeoutError:
        raise ToolError(
            f"Timed out after {timeout:g}s. Narrow the filters or ask for fewer columns.",
            status=504,
        ) from None


def _load_error(exc: Exception) -> ToolError:
    return ToolError(f"Could not load the data: {type(exc).__name__}: {str(exc)[:300]}")


def _is_numeric_type(type_name: str | None) -> bool:
    name = (type_name or "").lower()
    return any(name.startswith(prefix) for prefix in _NUMERIC_TYPES)


def column_types(dc_id: str, wf_id: str | None, init_data: dict[str, dict]) -> dict[str, str]:
    """``{column: dtype name}``: the ingest record first, else the Delta log."""
    recorded = dc_schema(dc_id)
    if recorded:
        return {c["name"]: str(c.get("type") or "") for c in recorded}
    if not wf_id:
        return {}
    live = schema_deltatable_lite(ObjectId(wf_id), ObjectId(dc_id), init_data=init_data)
    return {name: str(dtype) for name, dtype in live.items()}


def _coerce(value: Any, type_name: str | None) -> Any:
    """Numeric strings become numbers on numeric columns (clients often send strings)."""
    if isinstance(value, str) and _is_numeric_type(type_name):
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if number.is_integer() and "int" in (type_name or "") else number
    return value


def _unknown_columns_error(missing: list[str], types: dict[str, str]) -> ToolError:
    available = ", ".join(list(types)[:60])
    return ToolError(f"Unknown column(s) {', '.join(missing)}. Available: {available}")


def filter_payload(filters: list[FilterIn], types: dict[str, str]) -> list[dict[str, Any]]:
    """Viewer-shaped filter entries for ``FilterIn`` items (unknown columns refused).

    Value filters become the widget entries the viewer sends (MultiSelect,
    RangeSlider, TextInput), which the loaders turn into dtype-aware
    predicates. Comparisons become a ``filter_expr`` checked by the same
    validator the dashboards use.
    """
    if types:
        missing = sorted({f.column for f in filters if f.column not in types})
        if missing:
            raise _unknown_columns_error(missing, types)
    out: list[dict[str, Any]] = []
    for f in filters:
        type_name = types.get(f.column)
        values = f.value if isinstance(f.value, list) else [f.value]
        values = [_coerce(v, type_name) for v in values]
        widget: str | None = None
        widget_value: Any = None
        expr: str | None = None
        col = f"col({f.column!r})"
        if f.operator in ("eq", "in"):
            widget, widget_value = "MultiSelect", [str(v) for v in values]
        elif f.operator == "between":
            widget, widget_value = "RangeSlider", values
        elif f.operator == "contains":
            widget, widget_value = "TextInput", re.escape(str(values[0]))
        elif f.operator == "is_null":
            expr = f"{col}.is_null()"
        elif f.operator == "not_null":
            expr = f"{col}.is_not_null()"
        elif f.operator == "not_in":
            expr = f"~{col}.is_in({values!r})"
        else:
            expr = f"{col} {_COMPARISONS[f.operator]} {values[0]!r}"
        if widget:
            out.append(
                {
                    "column_name": f.column,
                    "interactive_component_type": widget,
                    "value": widget_value,
                }
            )
        else:
            try:
                validate_filter_expr(expr or "")
            except ValueError as exc:
                raise ToolError(f"Filter on {f.column!r} was refused: {exc}") from exc
            out.append({"filter_expr": expr})
    return out


def _saved_filters(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The tab's filter widgets with a saved value, in the viewer's filter shape."""
    out = []
    for comp in doc.get("stored_metadata") or []:
        if comp.get("component_type") != "interactive":
            continue
        if comp.get("value") in (None, [], "") or not comp.get("column_name"):
            continue
        out.append(
            {
                "index": str(comp.get("index")),
                "value": comp.get("value"),
                "column_name": comp.get("column_name"),
                "interactive_component_type": comp.get("interactive_component_type"),
                "metadata": {"dc_id": str(comp.get("dc_id") or "")},
            }
        )
    return out


def _split_known(
    entries: list[dict[str, Any]], types: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep entries whose columns this collection has; report the rest."""
    if not types:
        return entries, []
    kept, ignored = [], []
    for entry in entries:
        meta = entry.get("metadata") or {}
        column = entry.get("column_name") or meta.get("column_name")
        expr = entry.get("filter_expr") or meta.get("filter_expr")
        missing = [c for c in _COL_RE.findall(expr or "") if c not in types]
        if column and column not in types:
            missing.append(column)
        if missing:
            ignored.append(
                {
                    "column": ", ".join(missing),
                    "reason": "not a column of this data collection",
                }
            )
        else:
            kept.append(entry)
    return kept, ignored


def _filter_columns(entries: list[dict[str, Any]]) -> set[str]:
    cols: set[str] = set()
    for entry in entries:
        if entry.get("column_name"):
            cols.add(entry["column_name"])
        cols.update(_COL_RE.findall(entry.get("filter_expr") or ""))
    return cols


def _describe_filters(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            k: v
            for k, v in {
                "column": e.get("column_name"),
                "widget": e.get("interactive_component_type"),
                "value": e.get("value"),
                "filter_expr": untrusted(e["filter_expr"]) if e.get("filter_expr") else None,
            }.items()
            if v is not None
        }
        for e in entries
    ]


def component_columns(comp: dict[str, Any], names: set[str]) -> list[str]:
    """Columns a component reads, in config order: every config string naming a column."""
    found: list[str] = []

    def take(value: Any) -> None:
        if isinstance(value, str):
            if value in names and value not in found:
                found.append(value)
        elif isinstance(value, list):
            for item in value:
                take(item)

    skip = {"dc_config", "cols_json", "title", "description", "body", "code_content", "index"}
    for key, value in comp.items():
        if key in skip:
            continue
        if isinstance(value, dict):
            for inner in value.values():
                take(inner)
        else:
            take(value)
    for column in _COL_RE.findall(comp.get("filter_expr") or ""):
        take(column)
    return found


def safe_cell(value: Any) -> Any:
    """A cell ready for an agent: PII-redacted, control characters stripped, long text wrapped."""
    if isinstance(value, str):
        text = redact_pii(clean_text(value))
        return untrusted(text) if len(text) >= LONG_TEXT_CHARS else text
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, date, time, timedelta)):
        return str(value)
    if isinstance(value, (list, dict)):
        return safe_cell(str(value)[:200])
    return value


def safe_rows(df: pl.DataFrame) -> list[dict[str, Any]]:
    return [{k: safe_cell(v) for k, v in row.items()} for row in df.to_dicts()]


def column_profile(df: pl.DataFrame) -> list[dict[str, Any]]:
    """``_summarize_columns`` plus min / max / mean / median for numeric columns."""
    out = []
    for summary in _summarize_columns(df):
        entry: dict[str, Any] = asdict(summary)
        entry["null_pct"] = round(entry["null_pct"], 4)
        series = df.get_column(summary.name)
        if series.dtype.is_numeric() and series.len() > series.null_count():
            entry.update(
                {
                    stat: safe_cell(getattr(series, stat)())
                    for stat in ("min", "max", "mean", "median")
                }
            )
        out.append(entry)
    return out


def _is_categorical(series: pl.Series) -> bool:
    dtype = series.dtype
    if dtype in (pl.String, pl.Categorical, pl.Boolean) or isinstance(dtype, pl.Enum):
        return True
    return dtype.is_integer() and series.n_unique() <= MAX_GROUPS


def _group_view(df: pl.DataFrame, by: str, value: str | None = None) -> dict[str, Any]:
    aggs = [pl.len().alias("count")]
    if value and value != by and df.get_column(value).dtype.is_numeric():
        aggs += [
            pl.col(value).mean().alias(f"mean_{value}"),
            pl.col(value).median().alias(f"median_{value}"),
        ]
    grouped = df.group_by(by).agg(aggs).sort("count", descending=True)
    return {
        "column": by,
        "group_count": grouped.height,
        "top_groups": safe_rows(grouped.head(MAX_GROUPS)),
    }


def figure_view(comp: dict[str, Any], df: pl.DataFrame) -> dict[str, Any]:
    """Which columns the figure maps, and a small aggregate that shows its shape."""
    kwargs = comp.get("dict_kwargs") or {}
    roles = {
        k: kwargs[k]
        for k in FIGURE_ROLE_KEYS
        if isinstance(kwargs.get(k), str) and kwargs[k] in df.columns
    }
    view: dict[str, Any] = {"visu_type": comp.get("visu_type"), "roles": roles}
    if comp.get("component_type") == "advanced_viz":
        view["viz_kind"] = comp.get("viz_kind")
    x = roles.get("x") or roles.get("names")
    y = roles.get("y") or roles.get("values")
    if df.height == 0:
        return view
    if x and _is_categorical(df.get_column(x)):
        view["by_x"] = _group_view(df, x, y)
    elif (
        x
        and y
        and x != y
        and df.get_column(x).dtype.is_numeric()
        and df.get_column(y).dtype.is_numeric()
    ):
        view["pearson_x_y"] = safe_cell(df.select(pl.corr(x, y)).item())
    color = roles.get("color")
    if color and color != x and _is_categorical(df.get_column(color)):
        view["by_color"] = _group_view(df, color)
    return view


def card_value(user: Any, doc: dict[str, Any], comp: dict[str, Any], filters: list[dict]) -> dict:
    """The card's value under ``filters``, computed by the viewer's own card route."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import bulk_compute_cards

    index = str(comp.get("index"))
    result = bulk_compute_cards(
        dashboard_id=doc["dashboard_id"],
        request={"filters": filters, "component_ids": [index]},
        current_user=user,
        access_token=None,
    )
    out: dict[str, Any] = {
        "aggregation": comp.get("aggregation"),
        "column": comp.get("column_name"),
        "value": safe_cell((result.get("values") or {}).get(index)),
    }
    secondary = (result.get("secondary_values") or {}).get(index)
    if secondary:
        out["secondary_values"] = {k: safe_cell(v) for k, v in secondary.items()}
    if comp.get("filter_expr"):
        out["card_filter_expr"] = untrusted(comp["filter_expr"])
    return out


# ---------------------------------------------------------------------------
# Core functions (user-level, reusable outside the tool registry)
# ---------------------------------------------------------------------------
def _component_data_sync(
    user: Any, doc: dict[str, Any], comp: dict[str, Any], args: ComponentDataArgs
) -> dict[str, Any]:
    dc_id = str(comp["dc_id"])
    wf_id = str(comp["wf_id"]) if comp.get("wf_id") else None
    init_data = init_data_for_dc(dc_id)
    types = column_types(dc_id, wf_id, init_data)
    names = set(types)

    explicit = filter_payload(args.filters, types)
    widget_entries = clean_filter_payload(
        [*(_saved_filters(doc) if args.use_saved_filters else []), *args.viewer_filters]
    )
    kept, ignored = _split_known(widget_entries, types)
    applied = [*kept, *explicit]

    used = component_columns(comp, names) if names else []
    if args.columns:
        if names:
            missing = [c for c in args.columns if c not in names]
            if missing:
                raise _unknown_columns_error(missing, types)
        shown = list(dict.fromkeys(args.columns))
    elif comp.get("component_type") == "table" and not comp.get("columns"):
        shown = list(types)[:MAX_SHOWN_COLUMNS]
    else:
        shown = used or list(types)[:MAX_SHOWN_COLUMNS]
    load_cols = sorted(set(shown) | set(used) | _filter_columns(applied)) or None
    metadata = clean_filter_payload(applied) or None

    if not wf_id:
        raise ToolError("This component is not bound to a workflow; it has no data to load.")
    try:
        df = load_deltatable_lite(
            workflow_id=ObjectId(wf_id),
            data_collection_id=ObjectId(dc_id),
            metadata=metadata,
            select_columns=load_cols,
            init_data=init_data,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _load_error(exc) from exc
    if df is None:
        raise ToolError("The data collection could not be loaded.")
    df = df.drop([c for c in INTERNAL_COLUMNS if c in df.columns and c not in used])
    shown = [c for c in shown if c in df.columns] or df.columns[:MAX_SHOWN_COLUMNS]

    comp_type = comp.get("component_type")
    out: dict[str, Any] = {
        "dashboard_id": str(doc["dashboard_id"]),
        "index": str(comp.get("index")),
        "type": comp_type,
        "dc_id": dc_id,
        "row_count": df.height,
    }
    if metadata:
        out["total_row_count"] = count_deltatable_lite(
            ObjectId(wf_id), ObjectId(dc_id), init_data=init_data
        )
    out["filters_applied"] = _describe_filters(applied)
    if ignored:
        out["filters_ignored"] = ignored
    out["component_columns"] = used
    if comp_type == "card":
        out["card"] = card_value(user, doc, comp, applied)
    elif comp_type in ("figure", "advanced_viz"):
        out["figure"] = figure_view(comp, df)
    elif comp_type == "interactive" and comp.get("column_name") in df.columns:
        out["options"] = _group_view(df, comp["column_name"])
    out["columns"] = column_profile(df.select(shown))
    if args.max_rows:
        out["rows"] = safe_rows(df.select(shown).head(args.max_rows))
    return out


async def component_data(user: Any, args: ComponentDataArgs) -> dict[str, Any]:
    doc = load_viewable_dashboard(user, args.dashboard_id)
    comp = find_component(doc, args.index)
    if not comp.get("dc_id"):
        raise ToolError(f"Component {args.index} ({comp.get('component_type')}) has no data.")
    return await run_bounded(_component_data_sync, user, doc, comp, args)


def _describe_sync(user: Any, dc_id: str, sample_rows: int) -> dict[str, Any]:
    ctx = asyncio.run(build_data_context(dc_id, user, sample_n=max(sample_rows, 1)))
    return {
        "dc_id": ctx.data_collection_id,
        "dc_tag": ctx.data_collection_tag,
        "workflow_id": ctx.workflow_id,
        "workflow_tag": ctx.workflow_tag,
        "dc_type": ctx.dc_type,
        "project_name": untrusted(ctx.project_name),
        "project_description": untrusted(ctx.project_description),
        "dc_description": untrusted(ctx.dc_description),
        "row_count": ctx.row_count,
        "columns": [
            {**asdict(c), "null_pct": round(c.null_pct, 4)}
            for c in ctx.columns
            if c.name not in INTERNAL_COLUMNS
        ],
        "sample_rows": [
            {k: safe_cell(v) for k, v in row.items() if k not in INTERNAL_COLUMNS}
            for row in ctx.sample_rows[:sample_rows]
        ],
    }


async def describe_collection(user: Any, dc_id: str, sample_rows: int = 5) -> dict[str, Any]:
    return await run_bounded(_describe_sync, user, dc_id, sample_rows)


# Running query_data calls per user.
_active_queries: dict[str, int] = {}
_active_lock = threading.Lock()


@contextmanager
def query_slot(user_key: str) -> Iterator[None]:
    """At most ``MAX_CONCURRENT_QUERIES`` sandboxes per user; the next one is refused."""
    with _active_lock:
        if _active_queries.get(user_key, 0) >= MAX_CONCURRENT_QUERIES:
            raise ToolError(
                f"At most {MAX_CONCURRENT_QUERIES} queries may run at once; wait for one to finish.",
                status=429,
            )
        _active_queries[user_key] = _active_queries.get(user_key, 0) + 1
    try:
        yield
    finally:
        with _active_lock:
            remaining = _active_queries.get(user_key, 1) - 1
            if remaining > 0:
                _active_queries[user_key] = remaining
            else:
                _active_queries.pop(user_key, None)


def _sandbox_factory(specs: list[FrameSpec]) -> Any:
    """Indirection so tests can substitute ``sandbox.InlineSandbox``."""
    return AnalysisSandbox(specs)


async def _query_source(user: Any, args: QueryDataArgs) -> tuple[str, str, str]:
    """``(dc_id, workflow_id, tag)`` of the frame to query, permission-checked."""
    if args.dc_id:
        wf_id, _wf_tag, dc_doc, _project = await _resolve_dc_and_project(args.dc_id, user)
        tag = dc_doc.get("data_collection_tag") or dc_doc.get("name") or args.dc_id
        return args.dc_id, wf_id, str(tag)
    doc = load_viewable_dashboard(user, args.dashboard_id or "")
    comp = find_component(doc, args.index or "")
    if not comp.get("dc_id") or not comp.get("wf_id"):
        raise ToolError(f"Component {args.index} ({comp.get('component_type')}) has no data.")
    dc_id = str(comp["dc_id"])
    project = projects_collection.find_one({"_id": ObjectId(str(doc["project_id"]))})
    tag = (dc_index(project).get(dc_id) or {}).get("tag") or dc_id
    return dc_id, str(comp["wf_id"]), str(tag)


async def run_query(user: Any, args: QueryDataArgs) -> dict[str, Any]:
    dc_id, wf_id, tag = await _query_source(user, args)
    init_data = await run_bounded(init_data_for_dc, dc_id)
    types = await run_bounded(column_types, dc_id, wf_id, init_data)
    applied = filter_payload(args.filters, types)
    spec = FrameSpec(
        tag=tag,
        workflow_id=wf_id,
        data_collection_id=dc_id,
        init_data=init_data,
        filters=clean_filter_payload(applied) or None,
    )
    deadline = settings.mcp.query_timeout_s

    with query_slot(str(getattr(user, "id", ""))):
        sandbox = _sandbox_factory([spec])

        def execute() -> Any:
            try:
                sandbox.start()
                return sandbox.run(args.code, dc_tag=tag, deadline_s=deadline)
            finally:
                sandbox.close()

        try:
            step = await run_bounded(execute, extra_s=SANDBOX_START_ALLOWANCE_S)
        except ToolError:
            await asyncio.to_thread(sandbox.close)
            raise
        except RuntimeError as exc:  # the child failed to start or load
            raise _load_error(exc) from exc

    if step.status == "error":
        raise ToolError(f"Query failed: {clean_text(step.output)[:1500]}")
    return {
        "dc_id": dc_id,
        "dc_tag": tag,
        "code": args.code,
        "status": step.status,
        "rows_in": step.rows_in,
        "rows_out": step.rows_out,
        "seconds": step.seconds,
        "filters_applied": _describe_filters(applied),
        "output": untrusted(step.output),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@agent_tool(
    name="get_component_data",
    scope="read",
    description=(
        "The data behind one dashboard component. Returns row_count after filters (and "
        "total_row_count before), the columns the component uses, a profile per column "
        "(dtype, nulls, distinct, numeric min/max/mean/median), a head of rows (PII "
        "redacted), and per type: the card's computed value, the figure's mapped "
        "columns with group counts, or a filter's options. " + _FILTERS_DESCRIPTION + " "
        "Filters on columns the collection lacks are listed under filters_ignored. "
        "Results can be cited as evidence."
    ),
    input_model=ComponentDataArgs,
    evidence=True,
)
async def get_component_data(ctx: ToolContext, args: ComponentDataArgs) -> dict[str, Any]:
    return await component_data(ctx.user, args)


@agent_tool(
    name="describe_data_collection",
    scope="read",
    description=(
        "Profile a data collection: project and collection description, row count, every "
        "column with dtype, null share and distinct count, and a few PII-redacted sample "
        "rows. Use before query_data."
    ),
    input_model=DescribeDataCollectionArgs,
)
async def describe_data_collection(
    ctx: ToolContext, args: DescribeDataCollectionArgs
) -> dict[str, Any]:
    return await describe_collection(ctx.user, args.dc_id, args.sample_rows)


@agent_tool(
    name="query_data",
    scope="read",
    description=(
        "Run Polars code against one data collection (by dc_id, or the collection of a "
        "dashboard component) in a sandbox and return the printed result of the last "
        "expression (frames show at most 200 rows), its row counts and the code. Only "
        "an allowlist of DataFrame and expression methods is accepted (select, filter, "
        "with_columns, group_by, agg, sort, head, describe, join, ...); no imports, no I/O. "
        + _FILTERS_DESCRIPTION
        + f" Times out after the configured limit; at most {MAX_CONCURRENT_QUERIES} run at "
        "once per user. Aggregate rather than dumping rows. Results can be cited as evidence."
    ),
    input_model=QueryDataArgs,
    evidence=True,
)
async def query_data(ctx: ToolContext, args: QueryDataArgs) -> dict[str, Any]:
    return await run_query(ctx.user, args)
