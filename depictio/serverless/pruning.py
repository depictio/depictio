"""Per-data-collection column pruning for serverless bundles (RFC §6).

Computes, from a ``DashboardDataLite`` spec, the set of columns each data
collection actually needs — the union of every consuming component's
referenced columns — so the builder re-exports only those. ``None`` means
"keep every column": projecting a whole-frame figure or a table risks
silently breaking it, so uncertainty always widens to a full keep.

Data collections are keyed by ``"{workflow_tag}:{dc_tag}"`` (see
:func:`dc_key`), the same string producer B hashes into synthetic dc_ids.

Since phase 7 the pruning also has to survive **cross-DC links** (RFC §8): a
link translates a filter through a *join column* that no component necessarily
plots, so both endpoints of every emitted link must keep theirs or the bundled
filter would silently no-op. This mirrors the server's ``_effective_projection``
fold, pinned by ``TestCrossDcLinkProjection``
(``depictio/tests/api/v1/test_column_projection.py``).
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
#
# ``coverage_track`` dispatches on the server but is NOT here: its task
# (``compute_coverage_track``, celery_tasks.py:1340) is a projection, two
# whitelist row masks, a sort, a per-(chromosome, sample) rolling mean and an
# every-Nth decimation — all of it row-wise or partitioned by the very columns
# a dashboard filter masks on, so the mask commutes with the computation and
# the browser can redo the whole thing (``coverageTrackLive``). Freezing it
# also cost more than shipping the data: the frozen payload is the aggregated
# rows as JSON, several times the size of the same rows as bundled Parquet.
CELERY_VIZ_KINDS = frozenset({"embedding", "complex_heatmap", "upset", "upset_plot", "sankey"})

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


# Config-key suffixes that name data-collection columns. Scalars carry one
# column (``metric_col``, complex_heatmap's ``index_column``); the plural
# suffixes carry a list of them (``rank_cols``, ``value_columns``,
# rarefaction's ``metric_options`` — the metrics its tab strip switches
# between, each one a column of the frame).
_COLUMN_SCALAR_SUFFIXES = ("_col", "_column")
_COLUMN_LIST_SUFFIXES = ("_cols", "_columns", "_options")


def advanced_viz_columns(comp: dict[str, Any]) -> list[str]:
    """Columns an advanced_viz component reads, in config order, deduplicated.

    Derived from the persisted ``config`` blob — the convention
    ``buildAdvancedVizConfigBlob`` writes, the catalog preview reads and the
    ``/advanced_viz/data`` request carries. A key names columns when it ends in
    one of :data:`_COLUMN_SCALAR_SUFFIXES` (one column) or
    :data:`_COLUMN_LIST_SUFFIXES` (a list of them). Everything else is a knob,
    a palette or a value list (``top_n``, ``compute_method``,
    ``chromosomes_filter``, …) and contributes nothing.

    The rule deliberately **over**-collects: every consumer intersects the
    result with the DC's real schema before using it — producer A's
    ``select = [c for c in available if c in wanted]``, producer B's
    :func:`intersect_with_schema`, and the ``/advanced_viz/data`` endpoint's own
    ``projection = [c for c in projection if c in available_cols]`` — so a key
    that turns out to name no column is dropped harmlessly. Missing one is not
    harmless: the column never reaches the bundled Parquet and the renderer
    quietly falls back to whatever it does have. That is how rarefaction's
    metric tabs (``metric_options``) rendered the default metric for every tab
    in a bundle while looking like they worked.
    """
    columns: list[str] = []
    for key, value in (comp.get("config") or {}).items():
        if key.endswith(_COLUMN_LIST_SUFFIXES) and isinstance(value, list):
            columns.extend(v for v in value if isinstance(v, str) and v)
        elif key.endswith(_COLUMN_SCALAR_SUFFIXES) and isinstance(value, str) and value:
            columns.append(value)
    return list(dict.fromkeys(columns))


def advanced_viz_roles(comp: dict[str, Any]) -> dict[str, str]:
    """``<role> -> column`` map for an advanced_viz component's ``*_col`` keys.

    Deliberately NARROWER than :func:`advanced_viz_columns`: a role is a single
    binding the server looks up by name (``sampling.tail_role_for_kind`` asks
    for e.g. the ``significance`` role), so the list-valued keys — ``rank_cols``
    (a hierarchy), ``metric_options`` (a switchable set), ``value_columns`` (a
    matrix) — have no role to carry, and widening the map with them would only
    add entries no caller reads. They contribute columns and nothing else.
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


# ---------------------------------------------------------------------------
# Cross-DC links (RFC §8): join columns must survive pruning
# ---------------------------------------------------------------------------


def spec_links(spec: DashboardDataLite) -> list[dict[str, Any]]:
    """The optional top-level ``links:`` block of a build-from-spec YAML.

    ``DashboardDataLite`` is ``extra="allow"``, so a spec that declares
    project-shaped links (``source_dc_tag`` / ``target_dc_tag`` + ``source_column``
    + ``link_config`` + ``enabled``) simply carries them as an extra attribute.
    Anything that is not a list of dicts is ignored rather than fatal — a
    malformed block must not sink a build whose components are all fine.
    """
    raw = getattr(spec, "links", None)
    if not isinstance(raw, list):
        return []
    return [link for link in raw if isinstance(link, dict)]


def link_target_column(link: dict[str, Any]) -> str | None:
    """The column a link's resolved values name on the TARGET DC.

    Mirror of the server's ``_link_target_column`` (``api/v1/filter_links.py:57``)
    minus its first (resolver-supplied) branch, which only exists at resolution
    time: ``link_config.target_field`` first, then the link's own
    ``source_column`` — for a direct table→table link the join column has the
    same name on both sides.
    """
    link_config = link.get("link_config") or {}
    return link_config.get("target_field") or link.get("source_column") or None


def dc_keys_by_tag(spec: DashboardDataLite) -> dict[str, list[str]]:
    """``dc_tag -> [dc_key, ...]`` for every DC the spec's components reference.

    A spec's link block names data collections by *tag* alone (that is the
    project-YAML convention), while pruning keys DCs by ``workflow_tag:dc_tag``.
    The same tag under two workflows is legal, so the map keeps every match and
    callers fold into all of them — a spare kept column is harmless, a missing
    join column is a silently dead filter.
    """
    by_tag: dict[str, list[str]] = {}
    for raw in spec.components:
        comp = component_as_dict(raw)
        wf_tag = comp.get("workflow_tag") or ""
        dc_tag = comp.get("data_collection_tag") or ""
        if not wf_tag or not dc_tag:
            continue
        key = dc_key(wf_tag, dc_tag)
        keys = by_tag.setdefault(dc_tag, [])
        if key not in keys:
            keys.append(key)
    return by_tag


def link_join_columns(
    spec: DashboardDataLite, links: list[dict[str, Any]] | None = None
) -> dict[str, set[str]]:
    """``dc_key -> join columns`` contributed by the spec's cross-DC links.

    Each link pins ``source_column`` on its source DC and
    :func:`link_target_column` on its target DC. Disabled links count too: they
    ship in the manifest (the runtime skips them), and a link re-enabled in a
    rebuilt bundle should not need a different column set. Links whose tags do
    not resolve to a spec DC contribute nothing — producer B reports them
    separately.
    """
    by_tag = dc_keys_by_tag(spec)
    out: dict[str, set[str]] = {}
    for link in spec_links(spec) if links is None else links:
        for tag_field, column in (
            ("source_dc_tag", link.get("source_column")),
            ("target_dc_tag", link_target_column(link)),
        ):
            tag = link.get(tag_field)
            if not tag or not column:
                continue
            for key in by_tag.get(str(tag), []):
                out.setdefault(key, set()).add(str(column))
    return out


def compute_column_sets(
    spec: DashboardDataLite, links: list[dict[str, Any]] | None = None
) -> dict[str, set[str] | None]:
    """Per-DC column sets for the whole spec.

    Returns ``{dc_key: set_of_columns | None}`` where ``None`` means keep every
    column. Only DCs referenced by at least one data-reading component appear.

    Cross-DC link join columns (:func:`link_join_columns`) are folded in on top
    — a link's join column is typically NOT one a component plots, and dropping
    it would leave the bundled link resolving against a column that is not
    there. Only DCs that already have an entry are widened: a link endpoint no
    component reads is not a reason to bundle a whole extra data collection.
    Columns absent from the DC's real schema are dropped later, by
    :func:`intersect_with_schema`'s caller (schema-guard, like the server's
    ``_project_scan``).
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

    for key, join_cols in link_join_columns(spec, links).items():
        if key in sets and sets[key] is not None:
            sets[key] = (sets[key] or set()) | join_cols
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
