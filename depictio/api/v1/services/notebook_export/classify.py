"""How each component reaches the notebook.

Three outcomes, written for the reader of the export modal and of the
notebook itself:

* ``code`` — the component is reproduced as explicit Polars / Plotly code
  over the funnel's final frame;
* ``api`` — the component is re-rendered through the Depictio API with the
  exported analysis state (``client.component(...)``), because its renderer
  lives in Python packages or in the React viewer rather than in a formula;
* ``omitted`` — nothing can stand in for it, and the notebook says why.

``COMPONENT_COVERAGE`` must name every ``ComponentType`` (plus ``multiqc`` and
``highlight``, which ``stored_metadata`` carries although the literal does not
list them);
the exhaustiveness test fails when a new type is added without a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, get_args

from depictio.api.v1.services.export.capabilities import (
    GENOMESPY_VIEWS,
    component_json_source,
    resolve_viz_kind,
)
from depictio.models.components.types import AdvancedVizKind, ComponentType
from depictio.notebook.native import renderer_for

from .aggregations import agg_expr_source

Inclusion = str  # "code" | "api" | "omitted"


# What the reader gets for an ``api`` tile, in the rendered report:
#
# * ``interactive`` — a Plotly figure (hover, zoom, legend);
# * ``static`` — HTML (a card, a table, an image gallery);
# * ``snapshot`` — a PNG of the real renderer, for what is not Plotly.
Output = Literal["interactive", "static", "snapshot"]


@dataclass(frozen=True)
class Classification:
    status: Inclusion
    reason: str
    kind: str | None = None
    output: Output | None = None
    # Drawn in the document from its data rather than by the server.
    native: bool = False


# Component types that the literal does not list but the viewer draws.
EXTRA_COMPONENT_TYPES: tuple[str, ...] = ("multiqc", "highlight")

ALL_COMPONENT_TYPES: tuple[str, ...] = (*get_args(ComponentType), *EXTRA_COMPONENT_TYPES)
ALL_ADVANCED_VIZ_KINDS: tuple[str, ...] = tuple(get_args(AdvancedVizKind))

# How each advanced-viz kind reaches the notebook. Every member of
# ``AdvancedVizKind`` has an explicit verdict here (the module refuses to import
# otherwise, and ``test_classify`` pins a few by name), so a new kind cannot
# reach a report by default and fail it there:
#
# * ``plotly`` — the React renderer draws a Plotly figure. A kind whose figure
#   the server can also build (a Celery compute or a registered Python builder,
#   ``export.capabilities.component_json_source``) is served from there, with
#   no browser; the rest are extracted from the renderer, headless.
# * ``snapshot`` — the renderer draws SVG, a canvas, WebGL or plain HTML: no
#   Plotly figure exists to hand back. The document draws the tile itself from
#   its data where ``depictio.notebook.native`` has a renderer for it (Plotly,
#   py3Dmol, SVG or HTML); otherwise, and as that renderer's fallback, the
#   report shows a PNG of the real renderer, taken by the same headless pass,
#   and says it is one.
AdvancedVizRendering = Literal["plotly", "snapshot"]

ADVANCED_VIZ_RENDERING: dict[str, AdvancedVizRendering] = {
    # Celery computes return a Plotly figure.
    "complex_heatmap": "plotly",
    "upset_plot": "plotly",
    "sankey": "plotly",
    # Plotly in TypeScript, with a registered Python builder.
    "volcano": "plotly",
    "embedding": "plotly",
    "manhattan": "plotly",
    "stacked_bar": "plotly",
    "stacked_taxonomy": "plotly",
    "da_barplot": "plotly",
    "enrichment": "plotly",
    "ma": "plotly",
    "qq": "plotly",
    "sunburst": "plotly",
    "pr_benchmark": "plotly",
    "roc_pr_curve": "plotly",
    "confusion_matrix": "plotly",
    "metric_ci_bars": "plotly",
    # Plotly in TypeScript only: extracted from the renderer.
    "phylogenetic": "plotly",  # the tree; the rank summary (collapse_rank) is SVG, below
    "rarefaction": "plotly",
    "dot_plot": "plotly",
    "lollipop": "plotly",
    "oncoplot": "plotly",
    "coverage_track": "plotly",  # the track view; `locus` is GenomeSpy
    "profile": "plotly",
    "signal_matrix": "plotly",
    "fusion_structure": "plotly",
    "gene_arrow_track": "plotly",
    "gsea_running_score": "plotly",
    "sashimi": "plotly",  # the plotly view; `genomespy` is GenomeSpy
    "scatter_xy": "plotly",
    "contact_map": "plotly",  # the opening window only
    "knee_plot": "plotly",
    "damage_profile": "plotly",
    "group_compare": "plotly",  # the opening pair only
    "transcript_structure": "plotly",
    "cnv_profile": "plotly",  # the plotly view; `locus` is GenomeSpy
    "parallel_coordinates": "plotly",
    "ramachandran": "plotly",
    "ranked_distribution": "plotly",
    "spatial_cells": "plotly",
    # Not Plotly at all.
    "genome_view": "snapshot",  # GenomeSpy (WebGL)
    "genome_chord": "snapshot",  # hand-drawn SVG ring
    "ideogram": "snapshot",  # canvas karyotype
    "record_card": "snapshot",  # HTML fields of one row
    "ranked_table": "snapshot",  # HTML table with medals and bars
    "molecule_3d": "snapshot",  # 3Dmol.js (WebGL)
    "msa": "snapshot",  # canvas
    "sequence_track": "snapshot",  # canvas
    "hmm_logo": "snapshot",  # canvas
    "secondary_structure": "snapshot",  # canvas
    "domain_architecture": "snapshot",  # SVG lanes
    "pae_matrix": "snapshot",  # canvas matrix
    "allele_grid": "snapshot",  # hand-drawn SVG
    "pedigree": "snapshot",  # hand-drawn SVG
}

# Views of a Plotly kind that are drawn by something else: GenomeSpy's (the
# export's own table of them), and the phylogenetic rank summary, an SVG drawn
# when the tile collapses the tree to a rank.
SNAPSHOT_VIEWS: dict[str, frozenset[str]] = dict(GENOMESPY_VIEWS)

_MISSING_KINDS = set(get_args(AdvancedVizKind)) - set(ADVANCED_VIZ_RENDERING)
if _MISSING_KINDS:  # pragma: no cover - guards a coding error, like capabilities.py
    raise RuntimeError(
        "notebook export: advanced-viz kinds without a rendering verdict: "
        f"{sorted(_MISSING_KINDS)} (add them to ADVANCED_VIZ_RENDERING)"
    )

# Advanced-viz kinds whose Plotly figure the server builds itself (kept for
# callers of the older name; ``advanced_viz_rendering`` is the per-tile answer).
SERVER_PLOTLY_KINDS: frozenset[str] = frozenset({"complex_heatmap", "upset_plot", "sankey"})

API_REASON = "re-rendered through the Depictio API with the exported filters"

AdvancedVizDelivery = Literal["server", "extracted", "native", "snapshot"]


def advanced_viz_kind(meta: dict[str, Any]) -> str:
    return str(meta.get("viz_kind") or meta.get("kind") or meta.get("advanced_viz_kind") or "")


def advanced_viz_delivery(meta: dict[str, Any]) -> AdvancedVizDelivery | None:
    """How *this* tile reaches the document, honouring the view it opens on.

    ``server`` — the server builds the Plotly figure (no browser);
    ``extracted`` — the React renderer's Plotly figure, read headlessly;
    ``native`` — not Plotly in the app, drawn in the document from its data
    (``depictio.notebook.native``), with the snapshot as its fallback;
    ``snapshot`` — a PNG of the renderer, for what is not Plotly.
    ``None`` for an unknown kind.
    """
    raw = advanced_viz_kind(meta)
    kind = str(resolve_viz_kind(raw) or raw)
    verdict = ADVANCED_VIZ_RENDERING.get(raw) or ADVANCED_VIZ_RENDERING.get(kind)
    if verdict is None:
        return None
    config = meta.get("config") if isinstance(meta.get("config"), dict) else {}
    view = config.get("view")
    snapshot = (
        verdict == "snapshot"
        or view in SNAPSHOT_VIEWS.get(kind, frozenset())
        or (kind == "phylogenetic" and bool(config.get("collapse_rank")))
    )
    if snapshot:
        return "native" if renderer_for(meta) is not None else "snapshot"
    try:
        source = component_json_source(meta)
    except Exception:  # a malformed config is the renderer's problem, not the export's
        source = None
    if source in ("celery", "python"):
        return "server"
    return "extracted"


def _figure(meta: dict[str, Any]) -> Classification:
    mode = str(meta.get("mode") or "ui")
    visu = str(meta.get("visu_type") or "scatter")
    if mode == "code":
        return Classification("code", "the author's code, inlined verbatim", kind="code")
    # A UI-built figure's px.* call was reconstructed from the tile's stored
    # kwargs, which drifts from what the chart builder actually draws (theme,
    # any option the builder computes rather than stores) and reads as new
    # code rather than the dashboard's own. `client.component(...)` asks
    # Depictio for the real figure instead, so the notebook shows the same
    # picture the dashboard does, not a lookalike.
    return Classification(
        "api",
        f"a {visu} figure built by Depictio's chart builder; " + API_REASON,
        kind=visu,
        output="interactive",
    )


def _card(meta: dict[str, Any]) -> Classification:
    agg = str(meta.get("aggregation") or "")
    layout = str(meta.get("secondary_layout") or "")
    secondary_aggs = meta.get("aggregations") or []
    breakdown = meta.get("breakdown_col")
    if layout or secondary_aggs or breakdown:
        # A multi-metric card (a box plot, a top-N breakdown, a trend
        # sparkline, a completeness/coverage gauge, icon and colour
        # styling...) is drawn by the React card renderer from several
        # fields this dict carries, not by one scalar Polars reduction.
        # Reproducing only the hero number would show less than the
        # dashboard does, so the whole card renders through the API instead.
        return Classification(
            "api",
            f"a {layout or 'multi-metric'} card built by Depictio's card renderer; " + API_REASON,
            kind=layout or agg or None,
            output="static",
        )
    if agg_expr_source("x", agg) is not None:
        return Classification("code", f"{agg} of the column over the filtered frame", kind=agg)
    return Classification(
        "api",
        f"the {agg or 'card'} aggregation has no closed-form Polars expression; " + API_REASON,
        kind=agg or None,
        output="static",
    )


def _advanced_viz(meta: dict[str, Any]) -> Classification:
    kind = advanced_viz_kind(meta)
    delivery = advanced_viz_delivery(meta)
    if delivery is None:
        return Classification(
            "omitted", f"unknown advanced visualisation kind {kind!r}", kind=kind or None
        )
    if delivery == "server":
        return Classification(
            "api",
            "a Plotly figure built on the server; " + API_REASON,
            kind=kind,
            output="interactive",
        )
    if delivery == "native":
        renderer = renderer_for(meta)
        assert renderer is not None
        return Classification(
            "api",
            f"drawn by Depictio's renderer without Plotly, so the document draws it from "
            f"its data: {renderer.how}; a static snapshot of Depictio's renderer when that "
            "cannot run",
            kind=kind,
            output=renderer.output,
            native=True,
        )
    if delivery == "extracted":
        return Classification(
            "api",
            "a Plotly figure read from Depictio's own renderer; " + API_REASON,
            kind=kind,
            output="interactive",
        )
    return Classification(
        "api",
        "drawn by Depictio's renderer without Plotly (SVG, canvas or WebGL), so it "
        "appears as a static snapshot of that renderer; interactive in the live dashboard",
        kind=kind,
        output="snapshot",
    )


def _always(
    status: Inclusion, reason: str, output: Output | None = None
) -> Callable[[dict[str, Any]], Classification]:
    return lambda meta: Classification(status, reason, output=output)


def _multiqc(meta: dict[str, Any]) -> Classification:
    general_stats = (
        str(meta.get("selected_plot") or "").endswith("general_stats")
        or meta.get("selected_module") == "general_stats"
    )
    if general_stats:
        return Classification(
            "api",
            "MultiQC's General Statistics table and its violin summary, built on the server; "
            + API_REASON,
            kind="general_stats",
            output="interactive",
        )
    return Classification(
        "api", "a MultiQC plot built on the server; " + API_REASON, output="interactive"
    )


COMPONENT_COVERAGE: dict[str, Callable[[dict[str, Any]], Classification]] = {
    "figure": _figure,
    "card": _card,
    "table": _always("code", "the filtered frame's first page, as a DataFrame"),
    "text": _always("code", "a markdown cell"),
    "interactive": _always("code", "a funnel stage when active; no cell otherwise"),
    "advanced_viz": _advanced_viz,
    "map": _always("api", "a Plotly map figure built on the server; " + API_REASON, "interactive"),
    "multiqc": _multiqc,
    "image": _always(
        "api", "an image gallery served from the object store; " + API_REASON, "static"
    ),
    # The live tile is the embedded JBrowse 2 linear view, reading its tracks by
    # HTTP range through the instance. None of that survives a file, so the
    # document carries the session as a table (assembly, locus, tracks), a link
    # to the live tile, and a snapshot of the view it opens on.
    "jbrowse": _always(
        "api",
        "a genome browser: the tracks and opening locus as a table, a snapshot of the view, "
        "and a link to browse it live",
        "snapshot",
    ),
    # A figure shown again from another tab. Every tab is a part of the same
    # document, so the figure is already drawn where it lives; the highlight
    # becomes a pointer to it rather than a second copy.
    "highlight": _always("code", "a pointer to the figure on the tab it comes from"),
}


def classify(meta: dict[str, Any]) -> Classification:
    ctype = str(meta.get("component_type") or "")
    rule = COMPONENT_COVERAGE.get(ctype)
    if rule is None:
        return Classification("omitted", f"unknown component type {ctype!r}")
    return rule(meta)
