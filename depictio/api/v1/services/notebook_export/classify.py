"""How each component reaches the notebook.

Three outcomes, written for the reader of the export modal and of the
notebook itself:

* ``code`` — the component is reproduced as explicit Polars / Plotly code
  over the funnel's final frame;
* ``api`` — the component is re-rendered through the Depictio API with the
  exported analysis state (``client.component(...)``), because its renderer
  lives in Python packages or in the React viewer rather than in a formula;
* ``omitted`` — nothing can stand in for it, and the notebook says why.

``COMPONENT_COVERAGE`` must name every ``ComponentType`` (plus ``multiqc``,
which ``stored_metadata`` carries although the literal does not list it);
the exhaustiveness test fails when a new type is added without a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, get_args

from depictio.models.components.types import AdvancedVizKind, ComponentType

from .aggregations import agg_expr_source

Inclusion = str  # "code" | "api" | "omitted"


@dataclass(frozen=True)
class Classification:
    status: Inclusion
    reason: str
    kind: str | None = None


# A component type that the literal does not list but the viewer draws.
EXTRA_COMPONENT_TYPES: tuple[str, ...] = ("multiqc",)

ALL_COMPONENT_TYPES: tuple[str, ...] = (*get_args(ComponentType), *EXTRA_COMPONENT_TYPES)
ALL_ADVANCED_VIZ_KINDS: tuple[str, ...] = tuple(get_args(AdvancedVizKind))

# Advanced-viz kinds the server already renders as a Plotly figure; the other
# kinds are drawn by the React renderer from a data payload and reach the
# notebook as an extracted figure (see services/embed).
SERVER_PLOTLY_KINDS: frozenset[str] = frozenset({"complex_heatmap", "upset_plot", "sankey"})

API_REASON = "re-rendered through the Depictio API with the exported filters"


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
        "api", f"a {visu} figure built by Depictio's chart builder; " + API_REASON, kind=visu
    )


def _card(meta: dict[str, Any]) -> Classification:
    agg = str(meta.get("aggregation") or "")
    if agg_expr_source("x", agg) is not None:
        return Classification("code", f"{agg} of the column over the filtered frame", kind=agg)
    return Classification(
        "api",
        f"the {agg or 'card'} aggregation has no closed-form Polars expression; " + API_REASON,
        kind=agg or None,
    )


def _advanced_viz(meta: dict[str, Any]) -> Classification:
    kind = str(meta.get("viz_kind") or meta.get("kind") or meta.get("advanced_viz_kind") or "")
    if kind in SERVER_PLOTLY_KINDS:
        return Classification("api", "computed on the server; " + API_REASON, kind=kind or None)
    return Classification(
        "api",
        "drawn by the Depictio renderer from the filtered data; " + API_REASON,
        kind=kind or None,
    )


def _always(status: Inclusion, reason: str) -> Callable[[dict[str, Any]], Classification]:
    return lambda meta: Classification(status, reason)


COMPONENT_COVERAGE: dict[str, Callable[[dict[str, Any]], Classification]] = {
    "figure": _figure,
    "card": _card,
    "table": _always("code", "the filtered frame's first page, as a DataFrame"),
    "text": _always("code", "a markdown cell"),
    "interactive": _always("code", "a funnel stage when active; no cell otherwise"),
    "advanced_viz": _advanced_viz,
    "map": _always("api", "a Plotly map figure built on the server; " + API_REASON),
    "multiqc": _always("api", "a MultiQC plot built on the server; " + API_REASON),
    "image": _always("api", "an image gallery served from the object store; " + API_REASON),
    "jbrowse": _always(
        "api",
        "a genome browser session on the instance's JBrowse host; " + API_REASON,
    ),
}


def classify(meta: dict[str, Any]) -> Classification:
    ctype = str(meta.get("component_type") or "")
    rule = COMPONENT_COVERAGE.get(ctype)
    if rule is None:
        return Classification("omitted", f"unknown component type {ctype!r}")
    return rule(meta)
