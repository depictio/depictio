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

# Component types that read tabular data from a DC. Omitted types (multiqc,
# map, image, …) contribute no columns — their DCs are only bundled if a
# live/frozen component also reads them. advanced_viz joined in phase 4: its
# data-path kinds are served live by the in-browser engine, so the columns
# their config binds must survive pruning (see :func:`advanced_viz_columns`).
DATA_COMPONENT_TYPES = frozenset({"figure", "card", "interactive", "table", "advanced_viz"})

# advanced_viz kinds whose payload is computed by a Celery dispatch server-side
# (mirrors ``_ADVANCED_VIZ_DISPATCH_KINDS`` in depictio/catalog/payload.py plus
# the RFC §2.4 list). They read no columns from a bundled table — there is no
# in-browser equivalent of the compute — so neither producer bundles data for
# them.
CELERY_VIZ_KINDS = frozenset(
    {"embedding", "complex_heatmap", "upset", "upset_plot", "sankey", "coverage_track"}
)

# Data-path kinds that additionally read a SECOND, non-tabular source: the
# phylogenetic kind pairs its tabular DC with a Newick tree DC (``tree_dc_id``).
# One DataRef per component is a table, so these cannot go live — producer A
# freezes them (tree merged into the frozen payload), producer B omits them.
NON_TABULAR_VIZ_KINDS = frozenset({"phylogenetic"})

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


def advanced_viz_kind(comp: dict[str, Any]) -> str:
    """The viz kind of an advanced_viz component, top level or config blob."""
    return comp.get("viz_kind") or (comp.get("config") or {}).get("viz_kind") or ""


def advanced_viz_columns(comp: dict[str, Any]) -> list[str]:
    """Columns an advanced_viz component reads, in config order, deduplicated.

    Derived from the persisted ``config`` blob — every ``<role>_col`` scalar
    plus the hierarchical ``rank_cols`` list — which is the convention
    ``buildAdvancedVizConfigBlob`` writes, the catalog preview reads, and the
    ``/advanced_viz/data`` request carries. Non-column scalars (``top_n``,
    ``compute_method``, …) are ignored: only keys ending in ``_col`` bind a
    column.
    """
    columns: list[str] = []
    for key, value in (comp.get("config") or {}).items():
        if key == "rank_cols" and isinstance(value, list):
            columns.extend(v for v in value if isinstance(v, str) and v)
        elif key.endswith("_col") and isinstance(value, str) and value:
            columns.append(value)
    return list(dict.fromkeys(columns))


def advanced_viz_roles(comp: dict[str, Any]) -> dict[str, str]:
    """``<role> -> column`` map for an advanced_viz component's ``*_col`` keys.

    ``rank_cols`` carries no role (it is a hierarchy, not a single binding), so
    it contributes to :func:`advanced_viz_columns` only.
    """
    return {
        key[: -len("_col")]: value
        for key, value in (comp.get("config") or {}).items()
        if key.endswith("_col") and isinstance(value, str) and value
    }


def serves_advanced_viz_live(comp: dict[str, Any]) -> bool:
    """True when an advanced_viz component's data path is served live (phase 4).

    Live means the browser engine reads the bundled Parquet itself, so the
    component's columns must be bundled. Celery-computed kinds (no in-browser
    compute) and the phylogenetic kind (second, non-tabular source) are out;
    a config that binds no column at all is out too — there would be nothing
    to project, and both producers degrade such a component instead.
    """
    if comp.get("component_type") != "advanced_viz":
        return False
    kind = advanced_viz_kind(comp)
    if kind in CELERY_VIZ_KINDS or kind in NON_TABULAR_VIZ_KINDS:
        return False
    return bool(advanced_viz_columns(comp))


def component_columns(comp: dict[str, Any]) -> set[str] | None:
    """Columns one component reads from its DC. ``None`` = keep all columns.

    - figures (ui mode): ``referenced_columns`` from the real figure service;
      its ``None`` (whole-frame visu / unparseable kwargs) means keep all.
      Code-mode figures are never projected — arbitrary code reads anything.
    - cards: aggregation column + optional breakdown + filter_expr columns.
    - interactive: filtered column + filter_expr columns.
    - tables: all columns (RFC §6) — sorting/filtering may touch any of them.
    - advanced_viz: the columns its config binds, for the kinds served live
      (phase 4). Celery/phylogenetic kinds contribute nothing — their DC is
      only bundled if another component reads it.
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
    if ctype == "advanced_viz":
        if not serves_advanced_viz_live(comp):
            return set()
        return set(advanced_viz_columns(comp))
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
        ctype = comp.get("component_type")
        if ctype not in DATA_COMPONENT_TYPES:
            continue
        if ctype == "advanced_viz" and not serves_advanced_viz_live(comp):
            # A Celery / phylogenetic advanced_viz is omitted by producer B —
            # it must not conjure a DC entry (and an empty column set) of its own.
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
