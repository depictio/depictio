"""Preflight (``--check``) for producer B: the per-component tier table.

Classifies every component of a ``DashboardDataLite`` spec into its expected
liveness tier *without* reading any data or writing any output — this is what
makes the feature usable: authors see up front why a component will degrade
(RFC §3.3). The build itself refines the verdicts that need data: a figure the
bind-and-refill builder accepts (ui-mode kwargs, or a code-mode figure whose
prologue transpiled) is upgraded to ``live``, a code-mode figure whose trusted
local execution fails drops to ``omitted``, and a ui-mode figure that had to be
sampled (``FIGURE_MAX_POINTS``) drops to ``partial``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from depictio.models.models.dashboards import DashboardDataLite
from depictio.models.models.serverless import ComponentTier, TierReason
from depictio.serverless.prologue import transpile_with_reason
from depictio.serverless.pruning import component_as_dict

# advanced_viz kinds whose payload is computed by a Celery dispatch server-side
# (mirrors ``_ADVANCED_VIZ_DISPATCH_KINDS`` in depictio/catalog/payload.py plus
# the RFC §2.4 list).
_CELERY_VIZ_KINDS = frozenset(
    {"embedding", "complex_heatmap", "upset", "upset_plot", "sankey", "coverage_track"}
)

# Component types phase 1 serves live (filters re-query in the browser).
_LIVE_TYPES = frozenset({"card", "interactive", "text"})


@dataclass
class TierRow:
    """One row of the preflight table (and one ``tiers`` manifest entry)."""

    component_id: str
    title: str
    component_type: str
    tier: ComponentTier
    reason: TierReason | None = None
    detail: str | None = None


def classify_component(comp: dict[str, Any]) -> tuple[ComponentTier, TierReason | None, str | None]:
    """Planned (data-free) tier verdict for one component."""
    ctype = comp.get("component_type") or ""

    if ctype in _LIVE_TYPES:
        return ComponentTier.LIVE, None, None

    if ctype == "table":
        # Live tables (phase 3): the runtime recomputes every page — filter,
        # sort, slice — from the bundled Parquet (sortSlice mirrors the
        # server's render_table_endpoint), so a table whose data can ship
        # needs no frozen payload at all.
        if comp.get("workflow_tag") and comp.get("data_collection_tag"):
            return ComponentTier.LIVE, None, None
        return (
            ComponentTier.OMITTED,
            TierReason.UNSUPPORTED,
            "table references no resolvable data collection",
        )

    if ctype == "figure":
        if comp.get("mode", "ui") == "code":
            # Data-free verdict, but the transpiler IS data-free: it reads the
            # code, so preflight can already tell a replayable prologue from one
            # that will freeze. The build refines the first case to live once
            # the binding matches (and omits either if the code fails to run).
            ops, refusal = transpile_with_reason(comp.get("code_content") or "")
            if ops is None:
                return (
                    ComponentTier.FROZEN,
                    TierReason.CODE_MODE,
                    f"code-mode figure not transpilable: {refusal}; executed locally "
                    "(trusted) and frozen at the default filter state — omitted if "
                    "execution fails",
                )
            return (
                ComponentTier.FROZEN,
                TierReason.BINDING_MISS,
                "transpilable prologue; offered to bind-and-refill, upgraded to "
                "live when the binding matches",
            )
        return (
            ComponentTier.FROZEN,
            TierReason.BINDING_MISS,
            "ui-mode bind-and-refill lands in phase 5; frozen at the default filter state",
        )

    if ctype == "multiqc":
        return (
            ComponentTier.OMITTED,
            TierReason.MULTIQC,
            "MultiQC rendering needs the multiqc Python package (producer A)",
        )
    if ctype == "map":
        return (
            ComponentTier.OMITTED,
            TierReason.MAP_TILES,
            "maps need network tiles; single-file bundles are zero-network",
        )
    if ctype == "image":
        return (
            ComponentTier.OMITTED,
            TierReason.IMAGE,
            "image galleries read from S3; no object store in a static bundle",
        )
    if ctype == "jbrowse":
        return (
            ComponentTier.OMITTED,
            TierReason.JBROWSE,
            "JBrowse sessions need a genome-data backend",
        )
    if ctype == "advanced_viz":
        kind = comp.get("viz_kind") or (comp.get("config") or {}).get("viz_kind") or ""
        if kind in _CELERY_VIZ_KINDS:
            return (
                ComponentTier.OMITTED,
                TierReason.CELERY_COMPUTE,
                f"advanced_viz '{kind}' is a server-side Celery compute (producer A)",
            )
        return (
            ComponentTier.OMITTED,
            TierReason.UNSUPPORTED,
            f"advanced_viz '{kind or '?'}' data-path kinds go live in phase 4",
        )

    return (
        ComponentTier.OMITTED,
        TierReason.UNSUPPORTED,
        f"component type '{ctype or '?'}' is not supported by producer B",
    )


def classify_spec(spec: DashboardDataLite) -> list[TierRow]:
    """The planned tier table for a whole spec, in component order."""
    rows: list[TierRow] = []
    for i, raw in enumerate(spec.components):
        comp = component_as_dict(raw)
        tier, reason, detail = classify_component(comp)
        rows.append(
            TierRow(
                component_id=comp.get("tag") or comp.get("index") or f"component-{i}",
                title=comp.get("title") or "",
                component_type=comp.get("component_type") or "?",
                tier=tier,
                reason=reason,
                detail=detail,
            )
        )
    return rows


def print_tier_table(rows: list[TierRow], console: Any) -> None:
    """Pretty-print the tier table on a rich console (CLI ``--check``)."""
    from rich.table import Table

    styles = {
        ComponentTier.LIVE: "green",
        ComponentTier.PARTIAL: "yellow",
        ComponentTier.FROZEN: "cyan",
        ComponentTier.OMITTED: "red",
    }
    table = Table(title="Static-bundle preflight — per-component tiers")
    table.add_column("Component", style="cyan")
    table.add_column("Title")
    table.add_column("Type", style="magenta")
    table.add_column("Tier")
    table.add_column("Reason", style="dim")
    table.add_column("Detail", overflow="fold")
    for row in rows:
        table.add_row(
            row.component_id,
            row.title or "-",
            row.component_type,
            f"[{styles[row.tier]}]{row.tier.value}[/{styles[row.tier]}]",
            row.reason.value if row.reason else "-",
            row.detail or "-",
        )
    console.print(table)

    counts: dict[ComponentTier, int] = {}
    for row in rows:
        counts[row.tier] = counts.get(row.tier, 0) + 1
    summary = ", ".join(f"{counts[t]} {t.value}" for t in ComponentTier if t in counts)
    console.print(f"  {len(rows)} component(s): {summary}")
