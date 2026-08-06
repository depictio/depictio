"""Build the data + dashboard context the LLM sees.

Three things go into a prompt:
- column schema (name, dtype, null %, nunique)
- N sample rows with simple PII redaction
- project + data collection metadata (description, tags) and, for analyze,
  the current dashboard state (existing figures + active filters)

This module owns the "what does the LLM know about the dataset" question
so the routes themselves stay thin.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import polars as pl
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import (
    dashboards_collection,
    deltatables_collection,
    projects_collection,
)
from depictio.api.v1.deltatables_utils import load_deltatable_lite

logger = logging.getLogger(__name__)


def init_data_for_dc(data_collection_id: str) -> dict[str, dict]:
    """Delta-table location to hand `load_deltatable_lite(init_data=...)`.

    Without it the loader falls back to `GET /deltatables/get/{dc_id}`,
    i.e. the API calls itself over HTTP. Every AI flow runs inside a
    request handler, so that self-call cannot be served while the caller
    is holding the event loop: it does not 401, it times out after
    httpx's default 5s and surfaces as "Error loading deltatable".

    advanced_viz_endpoints and celery_tasks resolve the location from
    Mongo for the same reason; this mirrors them.
    """
    dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(data_collection_id)})
    if not dt_doc or not dt_doc.get("delta_table_location"):
        raise HTTPException(
            status_code=404,
            detail=(
                f"No materialised delta table for data collection {data_collection_id}. "
                "Ingest the data collection before using the AI assistant on it."
            ),
        )
    return {
        str(data_collection_id): {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": (dt_doc.get("flexible_metadata") or {}).get("deltatable_size_bytes", 0),
        }
    }


_PII_PATTERNS = [
    # Email
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    # Phone-like (very loose)
    (re.compile(r"\+?\d[\d \-().]{7,}\d"), "<phone>"),
]


def redact_pii(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    out = value
    for pat, sub in _PII_PATTERNS:
        out = pat.sub(sub, out)
    return out


@dataclass
class ColumnSummary:
    name: str
    dtype: str
    null_pct: float
    nunique: int

    def to_prompt_line(self) -> str:
        return f"- {self.name} ({self.dtype}, null={self.null_pct:.0%}, distinct={self.nunique})"


@dataclass
class DataContext:
    """Everything the LLM needs to know about a single data collection."""

    data_collection_id: str
    workflow_id: str
    project_name: str | None
    project_description: str | None
    dc_name: str | None
    dc_description: str | None
    columns: list[ColumnSummary]
    sample_rows: list[dict[str, Any]]
    row_count: int
    # The user-facing tags required to write a valid YAML component.
    # Resolved alongside the DC at load time so the LLM can emit
    # `workflow_tag` / `data_collection_tag` that round-trip through
    # `DashboardDataLite.from_yaml`.
    workflow_tag: str | None = None
    data_collection_tag: str | None = None

    def schema_block(self) -> str:
        return "\n".join(c.to_prompt_line() for c in self.columns)

    def sample_block(self) -> str:
        if not self.sample_rows:
            return "(no sample rows available)"
        # Render as compact JSON-ish
        lines = []
        for i, row in enumerate(self.sample_rows, 1):
            lines.append(f"{i}. {row}")
        return "\n".join(lines)

    def metadata_block(self) -> str:
        parts = []
        if self.project_name:
            parts.append(f"Project: {self.project_name}")
        if self.project_description:
            parts.append(f"Project description: {self.project_description}")
        if self.dc_name:
            parts.append(f"Data collection: {self.dc_name}")
        if self.dc_description:
            parts.append(f"Data collection description: {self.dc_description}")
        parts.append(f"Row count: {self.row_count:,}")
        return "\n".join(parts)


@dataclass
class FigureSummary:
    """Compact representation of a dashboard figure for the LLM."""

    component_id: str
    visu_type: str
    dict_kwargs: dict[str, Any] = field(default_factory=dict)
    title: str | None = None


@dataclass
class FilterSummary:
    component_id: str
    component_type: str  # multiselect | slider | date_picker | ...
    column: str | None
    value: Any


@dataclass
class ComponentSummary:
    """Any component on the dashboard, whatever its type.

    Figures and interactives get richer summaries above; this is the flat
    inventory, and it exists because the earlier walk skipped every other
    type outright. A card, table, multiqc or map component was invisible
    to the model even though its data collection was sitting right there.
    """

    component_id: str
    component_type: str
    dc_id: str | None = None
    title: str | None = None


@dataclass
class DashboardContext:
    """Snapshot of what is currently on the dashboard.

    Used by the analyze flow so the LLM can reference existing components
    when proposing filter changes or figure mutations.
    """

    dashboard_id: str
    figures: list[FigureSummary]
    filters: list[FilterSummary]
    components: list[ComponentSummary] = field(default_factory=list)
    # Every DC referenced by any component, in first-seen order.
    dc_ids: list[str] = field(default_factory=list)

    def components_block(self) -> str:
        if not self.components:
            return "(no components)"
        return "\n".join(
            f"- {c.component_id} ({c.component_type}, dc={c.dc_id})"
            + (f" — {c.title}" if c.title else "")
            for c in self.components
        )

    def figures_block(self) -> str:
        if not self.figures:
            return "(no figures)"
        return "\n".join(
            f"- {f.component_id}: {f.visu_type} {f.dict_kwargs}"
            + (f" — {f.title}" if f.title else "")
            for f in self.figures
        )

    def filters_block(self) -> str:
        if not self.filters:
            return "(no active filters)"
        return "\n".join(
            f"- {f.component_id} ({f.component_type}, col={f.column}): {f.value}"
            for f in self.filters
        )


# ---------- Loaders ----------


async def _resolve_dc_and_project(
    data_collection_id: str, current_user: Any
) -> tuple[str, str | None, dict[str, Any], dict[str, Any]]:
    """Return (workflow_id, workflow_tag, dc_doc, project_doc) for a DC id.

    Permission is delegated to the dashboards endpoints'
    `check_project_permission(..., "viewer")` — the same gate
    `build_dashboard_context` uses. An earlier version re-implemented the
    check as inline Mongo `$or` clauses and silently diverged from it: no
    admin override, no anonymous-user handling, so an admin without an
    explicit permissions entry got a 404 here while the dashboard flow
    let them through.

    Denial is still reported as the same 404 as absence, so the endpoint
    does not reveal which DC ids exist.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    try:
        dc_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid data_collection_id: {e}")

    pipeline = [
        {"$match": {"workflows.data_collections._id": dc_oid}},
        {"$unwind": "$workflows"},
        {"$unwind": "$workflows.data_collections"},
        {"$match": {"workflows.data_collections._id": dc_oid}},
        {
            "$project": {
                "project_name": "$name",
                "project_description": "$description",
                "workflow_id": "$workflows._id",
                "workflow_tag": "$workflows.workflow_tag",
                "dc": "$workflows.data_collections",
            }
        },
    ]
    rows = list(projects_collection.aggregate(pipeline))
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Data collection not found or access denied.",
        )
    row = rows[0]
    if not check_project_permission(row["_id"], current_user, "viewer"):
        raise HTTPException(
            status_code=404,
            detail="Data collection not found or access denied.",
        )
    project_doc = {
        "name": row.get("project_name"),
        "description": row.get("project_description"),
    }
    workflow_tag = row.get("workflow_tag")
    return str(row["workflow_id"]), workflow_tag, row["dc"], project_doc


def _summarize_columns(df: pl.DataFrame) -> list[ColumnSummary]:
    summaries: list[ColumnSummary] = []
    height = max(df.height, 1)
    for col in df.columns:
        s = df.get_column(col)
        try:
            null_pct = s.null_count() / height
        except Exception:
            null_pct = 0.0
        try:
            nunique = int(s.n_unique())
        except Exception:
            nunique = 0
        summaries.append(
            ColumnSummary(
                name=col,
                dtype=str(s.dtype),
                null_pct=float(null_pct),
                nunique=nunique,
            )
        )
    return summaries


def _sample_rows(df: pl.DataFrame, n: int) -> list[dict[str, Any]]:
    head = df.head(n).to_dicts()
    return [{k: redact_pii(v) for k, v in row.items()} for row in head]


async def build_data_context(
    data_collection_id: str,
    current_user: Any,
    *,
    sample_n: int | None = None,
) -> DataContext:
    """Loader for the suggest / component-from-prompt flows."""
    workflow_id, workflow_tag, dc_doc, project_doc = await _resolve_dc_and_project(
        data_collection_id, current_user
    )

    df = load_deltatable_lite(
        workflow_id=ObjectId(workflow_id),
        data_collection_id=ObjectId(data_collection_id),
        init_data=init_data_for_dc(data_collection_id),
    )
    if df is None:
        raise HTTPException(status_code=404, detail="Failed to load data collection.")

    dc_tag = dc_doc.get("data_collection_tag") or dc_doc.get("name")
    return DataContext(
        data_collection_id=data_collection_id,
        workflow_id=workflow_id,
        project_name=project_doc.get("name"),
        project_description=project_doc.get("description"),
        dc_name=dc_tag,
        dc_description=(dc_doc.get("config") or {}).get("description") or dc_doc.get("description"),
        columns=_summarize_columns(df),
        sample_rows=_sample_rows(df, n=sample_n or settings.ai.max_sample_rows),
        row_count=df.height,
        workflow_tag=workflow_tag,
        data_collection_tag=dc_tag,
    )


# ---------- Dashboard context ----------

# Component types that the analyze flow may target with filter proposals.
INTERACTIVE_TYPES: frozenset[str] = frozenset(
    {
        "interactive",
        "MultiSelect",
        "Slider",
        "RangeSlider",
        "DatePicker",
        "Switch",
        "SegmentedControl",
        "TimelineSlider",
    }
)

FIGURE_TYPES: frozenset[str] = frozenset({"figure", "Figure"})


def _component_id(meta: dict[str, Any]) -> str | None:
    """Best-effort component id resolver across the various store shapes."""
    for k in ("id", "component_id", "index"):
        v = meta.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            inner = v.get("index") or v.get("value")
            if isinstance(inner, str) and inner:
                return inner
    return None


def _coerce_id(value: Any) -> str | None:
    """Reduce a Mongo-fetched id (ObjectId, str, or {"$oid": "..."}) to a
    bare string suitable for ``ObjectId(s)`` round-tripping. Returns None
    on empty / unrecognized input.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        inner = value.get("$oid")
        if isinstance(inner, str) and inner:
            return inner
    return None


def _summarize_dashboard(
    dashboard_doc: dict[str, Any],
) -> tuple[list[FigureSummary], list[FilterSummary], list[ComponentSummary], list[str]]:
    """Inventory the dashboard: figures, interactives, every component, every DC.

    The DC list is ordered by first appearance in `stored_metadata`, and
    its head doubles as the default data source. Treat that default as an
    arbitrary pick, not a "main" table: `stored_metadata` is a Mongo array
    whose order reflects insertion, not layout and not importance. That is
    precisely why the multi-DC context exists — so the model chooses its
    source per step instead of inheriting whichever component was saved
    first.
    """
    figures: list[FigureSummary] = []
    filters: list[FilterSummary] = []
    components: list[ComponentSummary] = []
    dc_ids: list[str] = []

    for meta in dashboard_doc.get("stored_metadata", []) or []:
        comp_type = meta.get("component_type") or meta.get("type") or ""
        cid = _component_id(meta) or ""

        dc_id = _coerce_id(meta.get("dc_id") or (meta.get("metadata") or {}).get("dc_id"))
        if dc_id and dc_id not in dc_ids:
            dc_ids.append(dc_id)

        components.append(
            ComponentSummary(
                component_id=cid,
                component_type=str(comp_type),
                dc_id=dc_id,
                title=meta.get("title") or (meta.get("metadata") or {}).get("title"),
            )
        )

        if comp_type in FIGURE_TYPES or comp_type.lower() == "figure":
            dict_kwargs = (
                meta.get("dict_kwargs") or (meta.get("metadata") or {}).get("dict_kwargs") or {}
            )
            visu = (
                meta.get("visu_type") or (meta.get("metadata") or {}).get("visu_type") or "figure"
            )
            figures.append(
                FigureSummary(
                    component_id=cid,
                    visu_type=str(visu),
                    dict_kwargs=dict_kwargs if isinstance(dict_kwargs, dict) else {},
                    title=meta.get("title") or (meta.get("metadata") or {}).get("title"),
                )
            )
        elif comp_type in INTERACTIVE_TYPES or "interactive" in comp_type.lower():
            value = meta.get("value")
            if value is None:
                value = (meta.get("metadata") or {}).get("value")
            column = meta.get("column_name") or (meta.get("metadata") or {}).get("column_name")
            filters.append(
                FilterSummary(
                    component_id=cid,
                    component_type=str(comp_type),
                    column=column if isinstance(column, str) else None,
                    value=value,
                )
            )

    return figures, filters, components, dc_ids


# ---------- Multi-DC context (analysis) ----------


@dataclass
class JoinSummary:
    """A declared join between two of the dashboard's data collections."""

    left_dc: str
    right_dc: str
    on_columns: list[str]
    how: str = "inner"

    def to_prompt_line(self) -> str:
        cols = ", ".join(self.on_columns)
        return f"- {self.left_dc} {self.how} join {self.right_dc} on [{cols}]"


@dataclass
class DashboardDataContext:
    """Every data collection the dashboard touches, plus how they relate.

    Replaces the single `DataContext` for the analysis flow. The single
    version forced every question through whichever DC happened to be
    stored first; comparing two collections was not expressible at all,
    even though `join` has always been in the executor allowlist. What was
    missing was never the verb, only something to join against.
    """

    dashboard_id: str
    collections: list[DataContext] = field(default_factory=list)
    joins: list[JoinSummary] = field(default_factory=list)

    def tags(self) -> list[str]:
        return [c.data_collection_tag or c.data_collection_id for c in self.collections]

    def collections_block(self, *, with_samples: bool = True) -> str:
        if not self.collections:
            return "(no data collections)"
        chunks = []
        for c in self.collections:
            tag = c.data_collection_tag or c.data_collection_id
            head = f'dc["{tag}"] — {c.row_count:,} rows'
            if c.dc_description:
                head += f" — {c.dc_description}"
            body = [head, c.schema_block()]
            if with_samples:
                body.append(f"  sample: {c.sample_block()}")
            chunks.append("\n".join(body))
        return "\n\n".join(chunks)

    def joins_block(self) -> str:
        if not self.joins:
            return "(no declared joins)"
        return "\n".join(j.to_prompt_line() for j in self.joins)


def _joins_for_tags(project_doc: dict[str, Any], tags: set[str]) -> list[JoinSummary]:
    """Project-declared joins where both sides are on this dashboard.

    `left_dc`/`right_dc` are DC tags and may carry a `workflow.tag` scope
    prefix (see `depictio/models/models/joins.py`), so compare on the
    trailing segment.
    """

    def bare(value: Any) -> str:
        return str(value or "").split(".")[-1]

    out: list[JoinSummary] = []
    for raw in project_doc.get("joins") or []:
        if not isinstance(raw, dict):
            continue
        left, right = bare(raw.get("left_dc")), bare(raw.get("right_dc"))
        if not left or not right or left not in tags or right not in tags:
            continue
        cols = [str(c) for c in (raw.get("on_columns") or []) if c]
        if not cols:
            continue
        out.append(
            JoinSummary(
                left_dc=left,
                right_dc=right,
                on_columns=cols,
                how=str(raw.get("how") or "inner"),
            )
        )
    return out


# Ceiling on how many collections we describe to the model. A dashboard
# with dozens of DCs would otherwise blow the context budget on schemas
# alone; what gets dropped is reported to the caller rather than silently
# trimmed.
MAX_ANALYSIS_COLLECTIONS = 8


async def build_dashboard_data_context(
    dashboard_ctx: DashboardContext,
    current_user: Any,
) -> tuple[DashboardDataContext, list[str]]:
    """Summarise every DC on the dashboard. Returns (context, warnings).

    Permission is already settled by the time we get here: all of these
    collections belong to the dashboard's project, and
    `build_dashboard_context` has checked viewer access to it.

    Each collection is summarised through `build_data_context`, so this
    reads every frame the dashboard uses. Those reads go through the same
    Redis-backed cache the dashboard itself populates, so they are usually
    warm; it has not been measured, and if a trace ever shows it hurting,
    the fix is to have the sandbox child report schemas instead of loading
    twice.
    """
    warnings: list[str] = []
    dc_ids = dashboard_ctx.dc_ids
    if len(dc_ids) > MAX_ANALYSIS_COLLECTIONS:
        dropped = dc_ids[MAX_ANALYSIS_COLLECTIONS:]
        warnings.append(
            f"{len(dropped)} of {len(dc_ids)} data collections were left out of the "
            f"analysis context (limit {MAX_ANALYSIS_COLLECTIONS})."
        )
        dc_ids = dc_ids[:MAX_ANALYSIS_COLLECTIONS]

    collections: list[DataContext] = []
    project_doc: dict[str, Any] = {}
    for dc_id in dc_ids:
        try:
            ctx = await build_data_context(dc_id, current_user)
        except Exception as e:  # noqa: BLE001 — one bad DC must not void the rest
            logger.warning("analysis context: skipping dc %s: %s", dc_id, e)
            warnings.append(f"Data collection {dc_id} could not be read and was skipped.")
            continue
        collections.append(ctx)

    if collections:
        project_doc = _project_doc_for_dc(collections[0].data_collection_id) or {}

    tags = {c.data_collection_tag or c.data_collection_id for c in collections}
    return (
        DashboardDataContext(
            dashboard_id=dashboard_ctx.dashboard_id,
            collections=collections,
            joins=_joins_for_tags(project_doc, tags),
        ),
        warnings,
    )


def _project_doc_for_dc(data_collection_id: str) -> dict[str, Any] | None:
    """Fetch the owning project doc (for its `joins` list)."""
    try:
        oid = ObjectId(data_collection_id)
    except Exception:  # noqa: BLE001
        return None
    return projects_collection.find_one(
        {"workflows.data_collections._id": oid},
        {"joins": 1, "name": 1},
    )


async def build_dashboard_context(
    dashboard_id: str, current_user: Any
) -> tuple[DashboardContext, str | None]:
    """Return (dashboard context, primary DC id) or raise 400/403/404.

    Delegates the permission decision to the dashboards endpoints'
    `check_project_permission` so AI access mirrors `/dashboards/get/{id}`
    exactly (admin override, anonymous mode, owners/editors/viewers/public).
    The primary DC id is the first one referenced by any stored component,
    used as the analyze flow's default data source.
    """
    # Local import: dashboards_endpoints.routes is a heavy module and
    # importing it at module scope would risk a cycle through routers.py.
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    try:
        d_oid = ObjectId(dashboard_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid dashboard_id: {e}")

    doc = dashboards_collection.find_one({"dashboard_id": d_oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Dashboard not found.")

    project_id = doc.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this dashboard.",
        )

    figures, filters, components, dc_ids = _summarize_dashboard(doc)
    return (
        DashboardContext(
            dashboard_id=dashboard_id,
            figures=figures,
            filters=filters,
            components=components,
            dc_ids=dc_ids,
        ),
        dc_ids[0] if dc_ids else None,
    )
