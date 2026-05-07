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

from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.api.v1.deltatables_utils import load_deltatable_lite

logger = logging.getLogger(__name__)


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
class DashboardContext:
    """Snapshot of what is currently on the dashboard.

    Used by the analyze flow so the LLM can reference existing components
    when proposing filter changes or figure mutations.
    """

    dashboard_id: str
    figures: list[FigureSummary]
    filters: list[FilterSummary]

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
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Return (workflow_id, dc_doc, project_doc) for a DC id.

    Performs the same permission gate as `_get_data_collection_specs` but
    keeps the workflow + project around so we can build the metadata block.
    """
    try:
        dc_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid data_collection_id: {e}")

    pipeline = [
        {
            "$match": {
                "workflows.data_collections._id": dc_oid,
                "$or": [
                    {"permissions.owners._id": current_user.id},
                    {"permissions.viewers._id": current_user.id},
                    {"permissions.viewers": "*"},
                    {"is_public": True},
                ],
            }
        },
        {"$unwind": "$workflows"},
        {"$unwind": "$workflows.data_collections"},
        {"$match": {"workflows.data_collections._id": dc_oid}},
        {
            "$project": {
                "project_name": "$name",
                "project_description": "$description",
                "workflow_id": "$workflows._id",
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
    project_doc = {
        "name": row.get("project_name"),
        "description": row.get("project_description"),
    }
    return str(row["workflow_id"]), row["dc"], project_doc


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


def _sample_rows(df: pl.DataFrame, n: int = 5) -> list[dict[str, Any]]:
    head = df.head(n).to_dicts()
    return [{k: redact_pii(v) for k, v in row.items()} for row in head]


async def build_data_context(
    data_collection_id: str,
    current_user: Any,
    *,
    sample_n: int = 5,
) -> DataContext:
    """Loader for the suggest / figure-from-prompt flows."""
    workflow_id, dc_doc, project_doc = await _resolve_dc_and_project(
        data_collection_id, current_user
    )

    df = load_deltatable_lite(
        workflow_id=ObjectId(workflow_id),
        data_collection_id=ObjectId(data_collection_id),
    )
    if df is None:
        raise HTTPException(status_code=404, detail="Failed to load data collection.")

    return DataContext(
        data_collection_id=data_collection_id,
        workflow_id=workflow_id,
        project_name=project_doc.get("name"),
        project_description=project_doc.get("description"),
        dc_name=dc_doc.get("data_collection_tag") or dc_doc.get("name"),
        dc_description=(dc_doc.get("config") or {}).get("description") or dc_doc.get("description"),
        columns=_summarize_columns(df),
        sample_rows=_sample_rows(df, n=sample_n),
        row_count=df.height,
    )


# ---------- Dashboard context ----------

# Component types that the analyze flow may target with FilterAction.
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

    The dashboard doc loaded directly from MongoDB hands us ``ObjectId``
    instances — the analyze flow's prior ``isinstance(v, str)`` gate
    silently rejected those and produced "Dashboard has no data
    collection to analyze yet."
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
) -> tuple[list[FigureSummary], list[FilterSummary], str | None]:
    """Extract figures + interactive filter values + best-guess primary DC."""
    figures: list[FigureSummary] = []
    filters: list[FilterSummary] = []
    primary_dc: str | None = None

    for meta in dashboard_doc.get("stored_metadata", []) or []:
        comp_type = meta.get("component_type") or meta.get("type") or ""
        cid = _component_id(meta) or ""

        # Track the first DC we encounter — gives us a default for analyze
        # when the request body does not specify one.
        dc_id = _coerce_id(meta.get("dc_id") or (meta.get("metadata") or {}).get("dc_id"))
        if dc_id and primary_dc is None:
            primary_dc = dc_id

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

    return figures, filters, primary_dc


async def build_dashboard_context(
    dashboard_id: str, current_user: Any
) -> tuple[DashboardContext, str | None]:
    """Return (dashboard context, primary DC id) or raise 404/403.

    Reuses the same permission gate as `/dashboards/get/{id}` (project-based
    viewer access). The primary DC id is the first one referenced by any
    stored component, used as the analyze flow's default data source.
    """
    from bson import ObjectId as _OID  # local — avoid widening top-level imports

    try:
        d_oid = _OID(dashboard_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid dashboard_id: {e}")

    doc = dashboards_collection.find_one({"dashboard_id": d_oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Dashboard not found.")

    project_id = doc.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    project = projects_collection.find_one({"_id": _OID(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Dashboard's project not found.")

    is_public = bool(project.get("is_public"))
    perms = project.get("permissions") or {}
    user_id = getattr(current_user, "id", None)
    allowed = (
        is_public
        or any(
            (p.get("_id") == user_id)
            for p in (perms.get("owners") or []) + (perms.get("viewers") or [])
        )
        or "*" in (perms.get("viewers") or [])
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this dashboard.",
        )

    figures, filters, primary_dc = _summarize_dashboard(doc)
    return (
        DashboardContext(
            dashboard_id=dashboard_id,
            figures=figures,
            filters=filters,
        ),
        primary_dc,
    )
