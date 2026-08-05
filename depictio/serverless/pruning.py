"""Per-data-collection column pruning for serverless bundles (RFC §6).

Computes, from a ``DashboardDataLite`` spec, the set of columns each data
collection actually needs — the union of every consuming component's
referenced columns — so the builder re-exports only those. ``None`` means
"keep every column": projecting a whole-frame figure or a table risks
silently breaking it, so uncertainty always widens to a full keep.

Data collections are keyed by ``"{workflow_tag}:{dc_tag}"`` (see
:func:`dc_key`), the same string producer B hashes into synthetic dc_ids.
"""

from __future__ import annotations

import re
from typing import Any

from depictio.models.models.dashboards import DashboardDataLite

# Component types that read tabular data from a DC in phase 1. Omitted types
# (multiqc, map, image, advanced_viz, …) contribute no columns — their DCs are
# only bundled if a live/frozen component also reads them.
DATA_COMPONENT_TYPES = frozenset({"figure", "card", "interactive", "table"})

# `col('name')` / `col("name")` references inside a component-static filter_expr.
_FILTER_EXPR_COL_RE = re.compile(r"col\(\s*['\"]([^'\"]+)['\"]\s*\)")


def dc_key(workflow_tag: str, dc_tag: str) -> str:
    """The canonical per-DC key used across producer B."""
    return f"{workflow_tag}:{dc_tag}"


def component_as_dict(comp: Any) -> dict[str, Any]:
    """Normalise a spec component (typed Lite model or raw dict) to a dict."""
    if isinstance(comp, dict):
        return comp
    return comp.model_dump(exclude_none=True)


def filter_expr_columns(expr: str | None) -> set[str]:
    """Columns referenced by a component-static ``filter_expr`` string."""
    if not expr:
        return set()
    return set(_FILTER_EXPR_COL_RE.findall(expr))


def component_columns(comp: dict[str, Any]) -> set[str] | None:
    """Columns one component reads from its DC. ``None`` = keep all columns.

    - figures (ui mode): ``referenced_columns`` from the real figure service;
      its ``None`` (whole-frame visu / unparseable kwargs) means keep all.
      Code-mode figures are never projected — arbitrary code reads anything.
    - cards: aggregation column + optional breakdown + filter_expr columns.
    - interactive: filtered column + filter_expr columns.
    - tables: all columns (RFC §6) — sorting/filtering may touch any of them.
    """
    ctype = comp.get("component_type")
    if ctype == "figure":
        if comp.get("mode", "ui") == "code":
            return None
        from depictio.api.v1.services.figure.figure_builder import referenced_columns

        dict_kwargs = comp.get("figure_params") or comp.get("dict_kwargs") or {}
        return referenced_columns(comp.get("visu_type") or "scatter", dict_kwargs)
    if ctype == "card":
        cols = {comp["column_name"]} if comp.get("column_name") else set()
        if comp.get("breakdown_col"):
            cols.add(comp["breakdown_col"])
        return cols | filter_expr_columns(comp.get("filter_expr"))
    if ctype == "interactive":
        cols = {comp["column_name"]} if comp.get("column_name") else set()
        return cols | filter_expr_columns(comp.get("filter_expr"))
    if ctype == "table":
        return None
    return set()


def compute_column_sets(spec: DashboardDataLite) -> dict[str, set[str] | None]:
    """Per-DC column sets for the whole spec.

    Returns ``{dc_key: set_of_columns | None}`` where ``None`` means keep every
    column. Only DCs referenced by at least one data-reading component appear.
    DC-link columns are out of scope for producer B phase 1 — the Lite spec
    carries no link configs (they are project-level documents).
    """
    sets: dict[str, set[str] | None] = {}
    for raw in spec.components:
        comp = component_as_dict(raw)
        if comp.get("component_type") not in DATA_COMPONENT_TYPES:
            continue
        wf_tag = comp.get("workflow_tag") or ""
        dc_tag = comp.get("data_collection_tag") or ""
        if not wf_tag or not dc_tag:
            continue
        key = dc_key(wf_tag, dc_tag)
        cols = component_columns(comp)
        if key in sets and sets[key] is None:
            continue  # already keep-all
        if cols is None:
            sets[key] = None
        else:
            existing = sets.get(key) or set()
            sets[key] = existing | cols
    return sets


def intersect_with_schema(
    cols: set[str] | None, schema_columns: list[str]
) -> tuple[list[str], set[str]]:
    """Intersect a computed column set with the actual Parquet schema.

    Returns ``(kept_columns_in_schema_order, missing_columns)``. ``None``
    (keep all) keeps the whole schema and reports nothing missing.
    """
    if cols is None:
        return list(schema_columns), set()
    kept = [c for c in schema_columns if c in cols]
    return kept, cols - set(schema_columns)
