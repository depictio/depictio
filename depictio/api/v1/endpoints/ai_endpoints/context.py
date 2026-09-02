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
from dataclasses import dataclass, field, replace
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
    # The DC's `config.type` ("table", "phylogeny", ...). The advanced_viz
    # ranker gates some kinds on it; None means unknown and gates nothing.
    dc_type: str | None = None

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
    component_type: str  # stored component_type ("interactive")
    column: str | None
    value: Any
    # The widget flavour ("MultiSelect", "Slider", ...) — what
    # `add_filter` keys on when a set_widget proposal is turned into a
    # concrete row filter (e.g. for threshold resolution).
    interactive_component_type: str | None = None


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

    def with_active_filters(self, active: list[dict[str, Any]] | None) -> DashboardContext:
        """Overlay the client's live filter state on the stored widget values.

        `_summarize_dashboard` reads each interactive's *saved* value, i.e.
        what a fresh visitor sees, not what the asking user sees. The client
        sends its live filters separately, and the sandbox frames are built
        from those. Without this overlay the prompt says the widgets are
        unset while the data is already narrowed, and the model reports the
        mismatch as a data-access anomaly instead of using it.

        Widget entries (`index` + `value`) replace the matching summary's
        value. Expression-only entries (`filter_expr` without a widget
        value — the AI panel's own `source: 'ai_prompt'` filters) have no
        stored counterpart and are appended as `filter_expr` lines.
        """
        if not active:
            return self
        by_index: dict[str, dict[str, Any]] = {}
        expressions: list[FilterSummary] = []
        for entry in active:
            if not isinstance(entry, dict):
                continue
            index = entry.get("index")
            value = entry.get("value")
            expr = entry.get("filter_expr") or (entry.get("metadata") or {}).get("filter_expr")
            if entry.get("column_name") and index is not None:
                by_index[str(index)] = entry
            elif expr:
                column = entry.get("column_name") or (entry.get("metadata") or {}).get(
                    "column_name"
                )
                expressions.append(
                    FilterSummary(
                        component_id=str(index or "expression"),
                        component_type="filter_expr",
                        column=column if isinstance(column, str) else None,
                        value=expr,
                    )
                )
            elif index is not None and value not in (None, [], ""):
                by_index[str(index)] = entry
        filters = [
            replace(f, value=by_index[f.component_id].get("value"))
            if f.component_id in by_index
            else f
            for f in self.filters
        ]
        return replace(self, filters=[*filters, *expressions])


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
        dc_type=(dc_doc.get("config") or {}).get("type"),
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
            widget_type = meta.get("interactive_component_type") or (
                meta.get("metadata") or {}
            ).get("interactive_component_type")
            filters.append(
                FilterSummary(
                    component_id=cid,
                    component_type=str(comp_type),
                    column=column if isinstance(column, str) else None,
                    value=value,
                    interactive_component_type=widget_type
                    if isinstance(widget_type, str)
                    else None,
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


# ---------- Project inventory (routing + whole-dashboard generation) ----------
#
# A cheap, Mongo-only picture of every data collection the dashboard's
# project offers: tags, types, stored column specs, and whether the
# dashboard already uses the collection. No delta table is read. The
# component router consumes it to choose a type and a collection before
# generation; a later lot can feed the same block to a whole-dashboard
# generator, which is why it is not shaped around a single request.

# Collections that materialise a delta table and can back any of the
# tabular component types (figure, card, interactive, table, ...). Image
# collections are tables with an image-path column, so they qualify.
TABLE_LIKE_DC_TYPES: frozenset[str] = frozenset({"table", "image"})

# Which `config.type` values a component type can be built on. `map` is
# further narrowed to collections with coordinate columns (see
# `dc_has_coordinates`) and `text` has no data source at all.
COMPONENT_DC_TYPES: dict[str, frozenset[str]] = {
    "figure": TABLE_LIKE_DC_TYPES,
    "card": TABLE_LIKE_DC_TYPES,
    "interactive": TABLE_LIKE_DC_TYPES,
    "table": TABLE_LIKE_DC_TYPES,
    "advanced_viz": TABLE_LIKE_DC_TYPES | {"phylogeny"},
    "multiqc": frozenset({"multiqc"}),
    "image": frozenset({"image"}),
    "map": TABLE_LIKE_DC_TYPES,
    "text": frozenset(),
}

MAX_INVENTORY_COLLECTIONS = 30
MAX_INVENTORY_COLUMNS = 40
# Per-collection line budget in `text_block()`. Thirty lines at this size
# plus the type sheet keep the routing prompt around 10k characters.
MAX_INVENTORY_LINE_CHARS = 260
MAX_INVENTORY_DESCRIPTION_CHARS = 120

_LAT_NAME_RE = re.compile(r"(^|[_.\- ])(lat|latitude)([_.\- ]|$)", re.IGNORECASE)
_LON_NAME_RE = re.compile(r"(^|[_.\- ])(lon|lng|long|longitude)([_.\- ]|$)", re.IGNORECASE)
_NUMERIC_DTYPE_RE = re.compile(r"int|float|double|decimal", re.IGNORECASE)


@dataclass
class InventoryEntry:
    """One data collection of the project, as the router sees it."""

    data_collection_id: str
    data_collection_tag: str
    workflow_id: str
    workflow_tag: str | None
    dc_type: str | None
    description: str | None
    # (name, dtype) from the stored column specs, capped at
    # MAX_INVENTORY_COLUMNS. Empty for collections without a delta table
    # (multiqc, jbrowse2, ...) or not yet ingested.
    columns: list[tuple[str, str]] = field(default_factory=list)
    on_dashboard: bool = False
    # Explicit lat/lon hints from a coordinates table config, when the DC
    # was declared with them; the name heuristic covers the rest.
    coordinate_columns: tuple[str, str] | None = None

    def to_prompt_line(self, max_chars: int = MAX_INVENTORY_LINE_CHARS) -> str:
        """One line: tag, type, on-dashboard marker, description, columns.

        Columns are appended while the line stays under `max_chars`; the
        rest is summarised as a count so the model knows the list is cut.
        """
        flags = [self.dc_type or "unknown type"]
        if self.on_dashboard:
            flags.append("on dashboard")
        head = f"- {self.data_collection_tag} [{', '.join(flags)}]"
        if self.description:
            desc = " ".join(self.description.split())
            if len(desc) > MAX_INVENTORY_DESCRIPTION_CHARS:
                desc = desc[: MAX_INVENTORY_DESCRIPTION_CHARS - 3].rstrip() + "..."
            head += f": {desc}"
        if not self.columns:
            return head
        line = f"{head}. columns: "
        shown = 0
        for name, dtype in self.columns:
            token = f"{name}:{dtype}"
            sep = "" if shown == 0 else ", "
            remaining = len(self.columns) - shown - 1
            tail = f" (+{remaining} more)" if remaining > 0 else ""
            if len(line) + len(sep) + len(token) + len(tail) > max_chars and shown > 0:
                break
            line += sep + token
            shown += 1
        hidden = len(self.columns) - shown
        if hidden > 0:
            line += f" (+{hidden} more)"
        return line


def dc_has_coordinates(entry: InventoryEntry) -> bool:
    """Whether a collection looks mappable.

    True when the DC was declared with explicit `lat_column` / `lon_column`
    hints, or when its stored columns contain one latitude-looking and one
    longitude-looking numeric column (name match; dtype must be numeric
    when known).
    """
    if entry.coordinate_columns is not None:
        return True

    def numeric(dtype: str) -> bool:
        return not dtype or bool(_NUMERIC_DTYPE_RE.search(dtype))

    has_lat = any(_LAT_NAME_RE.search(n) and numeric(d) for n, d in entry.columns)
    has_lon = any(_LON_NAME_RE.search(n) and numeric(d) for n, d in entry.columns)
    return has_lat and has_lon


@dataclass
class ProjectInventory:
    """Every data collection the dashboard's project offers, dashboard DCs first."""

    dashboard_id: str
    project_id: str
    project_name: str | None
    entries: list[InventoryEntry] = field(default_factory=list)
    # How many collections were left out by MAX_INVENTORY_COLLECTIONS.
    dropped: int = 0

    def tags(self) -> list[str]:
        return [e.data_collection_tag for e in self.entries]

    def entry_for_tag(self, tag: str | None) -> InventoryEntry | None:
        """Exact tag match first, then case-insensitive, then id match.

        The router is told to answer with tags, but a model occasionally
        echoes an id it saw elsewhere in the conversation; accepting it
        costs nothing and saves a retry.
        """
        if not tag:
            return None
        wanted = tag.strip()
        for e in self.entries:
            if e.data_collection_tag == wanted:
                return e
        lowered = wanted.lower()
        for e in self.entries:
            if e.data_collection_tag.lower() == lowered:
                return e
        return self.entry_for_id(wanted)

    def entry_for_id(self, data_collection_id: str | None) -> InventoryEntry | None:
        if not data_collection_id:
            return None
        for e in self.entries:
            if e.data_collection_id == data_collection_id:
                return e
        return None

    def candidates_for(self, component_type: str) -> list[InventoryEntry]:
        """Collections a component of this type can be built on, inventory order.

        Table-like DCs for the tabular types (plus phylogeny for
        advanced_viz), multiqc DCs for multiqc, image DCs for image,
        coordinate-bearing table-like DCs for map, nothing for text.
        """
        allowed = COMPONENT_DC_TYPES.get(component_type, frozenset())
        out = [e for e in self.entries if (e.dc_type or "").lower() in allowed]
        if component_type == "map":
            out = [e for e in out if dc_has_coordinates(e)]
        return out

    def text_block(self) -> str:
        if not self.entries:
            return "(the project has no data collections)"
        lines = [e.to_prompt_line() for e in self.entries]
        if self.dropped:
            lines.append(f"(+{self.dropped} more collections not listed)")
        return "\n".join(lines)


def _stored_columns_by_dc(dc_ids: list[str]) -> dict[str, list[tuple[str, str]]]:
    """(name, dtype) per DC from the latest aggregation's column specs.

    Read from the `deltatables` documents the ingest writes, so no frame
    is loaded. Collections without a delta table simply get no columns.
    """
    oids = []
    for dc_id in dc_ids:
        try:
            oids.append(ObjectId(dc_id))
        except Exception:  # noqa: BLE001
            continue
    if not oids:
        return {}
    cursor = deltatables_collection.find(
        {"data_collection_id": {"$in": oids}},
        {
            "data_collection_id": 1,
            "aggregation.aggregation_columns_specs.name": 1,
            "aggregation.aggregation_columns_specs.type": 1,
        },
    )
    out: dict[str, list[tuple[str, str]]] = {}
    for doc in cursor:
        dc_id = _coerce_id(doc.get("data_collection_id"))
        aggregations = doc.get("aggregation") or []
        if not dc_id or not aggregations:
            continue
        specs = (aggregations[-1] or {}).get("aggregation_columns_specs") or []
        columns: list[tuple[str, str]] = []
        if isinstance(specs, list):
            for spec in specs:
                if isinstance(spec, dict) and spec.get("name"):
                    columns.append((str(spec["name"]), str(spec.get("type") or "")))
        elif isinstance(specs, dict):  # legacy name-keyed shape
            for name, spec in specs.items():
                dtype = spec.get("type") if isinstance(spec, dict) else ""
                columns.append((str(name), str(dtype or "")))
        out[dc_id] = columns[:MAX_INVENTORY_COLUMNS]
    return out


async def build_project_inventory(
    dashboard_id: str,
    current_user: Any,
    *,
    prioritize: list[str] | None = None,
) -> ProjectInventory:
    """Inventory the data collections of the dashboard's project.

    Same gate as `build_dashboard_context` (viewer permission on the
    dashboard's project via `check_project_permission`), same error
    codes. Collections already used by the dashboard come first, after
    any ids in `prioritize` (a pinned collection must survive the
    MAX_INVENTORY_COLLECTIONS cut, whatever its position in the project).
    """
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

    project = projects_collection.find_one(
        {"_id": ObjectId(project_id)},
        {
            "name": 1,
            "workflows._id": 1,
            "workflows.workflow_tag": 1,
            "workflows.data_collections._id": 1,
            "workflows.data_collections.data_collection_tag": 1,
            "workflows.data_collections.description": 1,
            "workflows.data_collections.config.type": 1,
            "workflows.data_collections.config.description": 1,
            "workflows.data_collections.config.dc_specific_properties.lat_column": 1,
            "workflows.data_collections.config.dc_specific_properties.lon_column": 1,
        },
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    _, _, _, dashboard_dc_ids = _summarize_dashboard(doc)
    on_dashboard = set(dashboard_dc_ids)

    entries: list[InventoryEntry] = []
    for wf in project.get("workflows") or []:
        if not isinstance(wf, dict):
            continue
        wf_id = _coerce_id(wf.get("_id")) or ""
        wf_tag = wf.get("workflow_tag")
        for dc in wf.get("data_collections") or []:
            if not isinstance(dc, dict):
                continue
            dc_id = _coerce_id(dc.get("_id"))
            if not dc_id:
                continue
            cfg = dc.get("config") or {}
            props = cfg.get("dc_specific_properties") or {}
            lat, lon = props.get("lat_column"), props.get("lon_column")
            entries.append(
                InventoryEntry(
                    data_collection_id=dc_id,
                    data_collection_tag=str(dc.get("data_collection_tag") or dc_id),
                    workflow_id=wf_id,
                    workflow_tag=wf_tag if isinstance(wf_tag, str) else None,
                    dc_type=str(cfg["type"]).lower() if cfg.get("type") else None,
                    description=cfg.get("description") or dc.get("description") or None,
                    on_dashboard=dc_id in on_dashboard,
                    coordinate_columns=(str(lat), str(lon)) if lat and lon else None,
                )
            )

    rank = {dc_id: i for i, dc_id in enumerate([*(prioritize or []), *dashboard_dc_ids])}
    # Stable sort: unranked collections keep their project order.
    entries.sort(key=lambda e: rank.get(e.data_collection_id, len(rank)))
    dropped = max(len(entries) - MAX_INVENTORY_COLLECTIONS, 0)
    entries = entries[:MAX_INVENTORY_COLLECTIONS]

    columns = _stored_columns_by_dc([e.data_collection_id for e in entries])
    for e in entries:
        e.columns = columns.get(e.data_collection_id, [])

    return ProjectInventory(
        dashboard_id=dashboard_id,
        project_id=str(project_id),
        project_name=project.get("name"),
        entries=entries,
        dropped=dropped,
    )
