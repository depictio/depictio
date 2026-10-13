"""Which (component_type, format) pairs can be exported — the single source of truth.

The classification here is the audit that motivated the export feature, encoded as
data rather than prose so it cannot silently drift from the code:

* ``COMPONENT_FORMATS`` must name every member of ``ComponentType``.
* ``AV_JSON_SOURCE`` must name every member of ``AdvancedVizKind``.

``depictio/tests/api/v1/services/export/test_capabilities.py`` parametrises over
``typing.get_args`` of both Literals, so adding a component type or a viz kind
without classifying it here fails CI.

The three tiers, for orientation:

* Server-built Plotly today — ``figure`` (``services/figure/figure_builder.py``),
  ``map`` (``services/map/render.py``), ``multiqc`` (``services/multiqc/figures.py``),
  and the ``complex_heatmap`` / ``upset_plot`` / ``sankey`` advanced-viz kinds which
  already return ``{"figure": {...}}`` from their Celery compute tasks.
* Plotly *visually*, but the spec is built client-side in TypeScript — the other 15
  advanced-viz kinds. They are HTML-exportable immediately (the offline bundle runs
  the real renderers) and become JSON-exportable one at a time as Python builders
  land in ``services/advanced_viz/kinds/``.
* Not Plotly at all — ``card``, ``interactive``, ``table``, ``image``, ``text``.
  HTML only. ``jbrowse`` is neither: it is an iframe onto a live JBrowse2 server,
  so it cannot be made offline-self-contained and is unsupported in both formats.

A kind folded into another (``ma``/``qq`` into ``volcano``, ``enrichment`` into
``dot_plot``, ``roc_pr_curve`` into ``pr_benchmark``) keeps its entry here: its
builder still draws that view. Whether a *component* exports as JSON therefore
depends on the view it opens on, which :func:`component_formats` resolves through
``services/advanced_viz/views.py``.
"""

from enum import Enum
from typing import Literal, get_args

from depictio.api.v1.services.advanced_viz.views import BuildPlan, canonical_kind, plan_for
from depictio.models.components.types import AdvancedVizKind, ComponentType


class ExportFormat(str, Enum):
    """Wire value of the ``format`` query parameter."""

    JSON = "json"
    HTML = "html"


#: Retired and legacy ``viz_kind`` names resolve the way the models resolve them
#: (``configs.resolve_viz_kind`` plus the older ``ancombc_differentials``). Stored
#: metadata bypasses Pydantic, so both shapes reach the export at runtime.
resolve_viz_kind = canonical_kind


#: Formats each component type can be exported as. ``advanced_viz`` advertises JSON
#: here, but it is gated per-kind by ``AV_JSON_SOURCE`` — see ``formats_for``.
COMPONENT_FORMATS: dict[str, frozenset[ExportFormat]] = {
    "figure": frozenset({ExportFormat.JSON, ExportFormat.HTML}),
    "map": frozenset({ExportFormat.JSON, ExportFormat.HTML}),
    "multiqc": frozenset({ExportFormat.JSON, ExportFormat.HTML}),
    "advanced_viz": frozenset({ExportFormat.JSON, ExportFormat.HTML}),
    "table": frozenset({ExportFormat.HTML}),
    "card": frozenset({ExportFormat.HTML}),
    "image": frozenset({ExportFormat.HTML}),
    "interactive": frozenset({ExportFormat.HTML}),
    "text": frozenset({ExportFormat.HTML}),
    # A sandboxed iframe onto a live JBrowse2 instance. Nothing to serialise and
    # nothing that survives being taken offline.
    "jbrowse": frozenset(),
    # Another tab's figure, shown again here. Not in ``ComponentType`` (it has no
    # data binding of its own), but it is stored like any other component. The
    # thing to export is its source, which the manifest names.
    "highlight": frozenset(),
}

#: Kinds the offline bundle cannot serve, so ``format=html`` would render an
#: empty frame and a CSP violation in the host page. Two reasons:
#:
#: * the renderer reaches the network on its own, outside ``api.ts``: GenomeSpy
#:   reads its annotation tracks directly;
#: * the renderer computes per interaction, so no precomputed result stands for
#:   the component: a contact map dispatches one job per zoom window, a group
#:   comparison one per pair of selections.
HTML_UNAVAILABLE_KINDS: dict[str, str] = {
    "genome_view": (
        "The genome view draws with GenomeSpy, which fetches its annotation tracks "
        "itself, so it cannot be taken offline. Open the dashboard instead."
    ),
    "contact_map": (
        "A contact map computes each zoom window on the server as it is explored, so "
        "no offline page can stand for it. Open the dashboard instead."
    ),
    "group_compare": (
        "A group comparison computes on the server for the two groups picked in the "
        "tile, so no offline page can stand for it. Open the dashboard instead."
    ),
    "bioimage_viewer": (
        "The bioimage viewer draws on WebGL and fetches its image chunks with the "
        "viewer's credentials, so it cannot be taken offline. Open the dashboard instead."
    ),
}

#: Views drawn by GenomeSpy (see above), by kind. The kind's default view is
#: Plotly and embeds fine; a tile saved on one of these views does not.
GENOMESPY_VIEWS: dict[str, frozenset[str]] = {
    "coverage_track": frozenset({"locus"}),
    "cnv_profile": frozenset({"locus"}),
    "sashimi": frozenset({"genomespy"}),
}

_GENOMESPY_VIEW_REASON = (
    "This tile opens on a GenomeSpy view, which fetches its tracks itself and "
    "cannot be taken offline. Switch the tile to its Plotly view to embed it."
)

#: Where an advanced-viz kind's Plotly spec comes from.
#:
#: ``celery``      — an existing compute task already returns ``{"figure": {...}}``
#: ``python``      — a builder is registered in ``services/advanced_viz/kinds/``
#: ``client_only`` — the spec exists only in the browser; JSON export returns 501
#:                   and points the caller at ``format=html``
#:
#: Phase 3 flips entries from ``client_only`` to ``python`` one at a time. Nothing
#: else needs editing when a kind lands: ``formats_for`` and the route's 501 branch
#: both read this table.
AvJsonSource = Literal["celery", "python", "client_only"]

AV_JSON_SOURCE: dict[str, AvJsonSource] = {
    # Already server-built.
    "complex_heatmap": "celery",
    "upset_plot": "celery",
    "sankey": "celery",
    # Ported to Python; see services/advanced_viz/kinds/. Listed as client_only
    # only until a builder lands — `_python_builder_kinds()` overrides this table
    # from the registry, so these entries are documentation rather than a gate.
    "volcano": "python",
    "embedding": "python",
    "manhattan": "python",
    "stacked_taxonomy": "python",
    "phylogenetic": "client_only",
    "rarefaction": "client_only",
    "da_barplot": "python",
    "enrichment": "python",
    "ma": "python",
    "dot_plot": "client_only",
    "lollipop": "client_only",
    "qq": "python",
    "sunburst": "python",
    "oncoplot": "client_only",
    "coverage_track": "client_only",
    # Benchmarking kinds (nf-core/variantbenchmarking). Ported alongside the
    # rest; see services/advanced_viz/kinds/.
    "roc_pr_curve": "python",
    "pr_benchmark": "python",
    "confusion_matrix": "python",
    "metric_ci_bars": "python",
    # Kinds added after the export landed. Their specs are built in TypeScript
    # only; HTML renders them through the real renderer (bar genome_view, see
    # HTML_UNAVAILABLE_KINDS), JSON answers 501 until a builder is ported.
    "profile": "client_only",
    "signal_matrix": "client_only",
    "fusion_structure": "client_only",
    "gene_arrow_track": "client_only",
    "gsea_running_score": "client_only",
    "sashimi": "client_only",
    "scatter_xy": "client_only",
    "contact_map": "client_only",
    "knee_plot": "client_only",
    "damage_profile": "client_only",
    "genome_view": "client_only",
    "group_compare": "client_only",
    "transcript_structure": "client_only",
    "cnv_profile": "client_only",
    "genome_chord": "client_only",
    "record_card": "client_only",
    "parallel_coordinates": "client_only",
    "bioimage_viewer": "client_only",
}


def _python_builder_kinds() -> frozenset[str]:
    """Kinds with a registered Python figure builder.

    Imported lazily so this module stays importable before the advanced-viz
    builder package exists, and so a broken builder cannot take down the
    capability matrix (and with it the whole export router).
    """
    try:
        from depictio.api.v1.services.advanced_viz.figure_registry import supported_kinds
    except Exception:  # pragma: no cover - package not present yet
        return frozenset()
    return supported_kinds()


def advanced_viz_json_source(viz_kind: str | None) -> AvJsonSource | None:
    """Resolve how (or whether) a viz kind can produce a Plotly spec server-side.

    Returns ``None`` for an unknown kind — the caller should treat that as
    unsupported rather than guessing.
    """
    # A registered Python builder wins over the static table so a kind becomes
    # exportable the moment its module is imported, without a second edit here.
    # Checked on the name as given first: a retired kind (`enrichment`) names the
    # drawing its builder still makes, even though its survivor (`dot_plot`) has
    # no builder for its own default view.
    builders = _python_builder_kinds()
    if viz_kind in builders:
        return "python"
    kind = resolve_viz_kind(viz_kind)
    if kind is None or kind not in AV_JSON_SOURCE:
        return None
    if kind in builders:
        return "python"
    return AV_JSON_SOURCE[kind]


def formats_for(component_type: str, viz_kind: str | None = None) -> frozenset[ExportFormat]:
    """Formats a component type (and, for ``advanced_viz``, a kind) can export as.

    Kind-level: a survivor with views answers for its default view. Use
    :func:`component_formats` for an actual component, whose stored view decides.
    """
    formats = COMPONENT_FORMATS.get(component_type, frozenset())
    if component_type != "advanced_viz":
        return formats
    kind = resolve_viz_kind(viz_kind)
    if kind in HTML_UNAVAILABLE_KINDS:
        formats = formats - {ExportFormat.HTML}
    if advanced_viz_json_source(viz_kind) in ("celery", "python"):
        return formats
    return formats - {ExportFormat.JSON}


def _plan_json_source(plan: BuildPlan) -> AvJsonSource | None:
    """JSON source for a resolved plan: every builder it needs must be registered."""
    if plan.kind not in AV_JSON_SOURCE:
        return None
    if AV_JSON_SOURCE[plan.kind] == "celery":
        return "celery"
    registered = _python_builder_kinds()
    if all(builder in registered for builder in plan.builders):
        return "python"
    return "client_only"


def _opens_on_genomespy(component: dict) -> bool:
    kind = resolve_viz_kind(component.get("viz_kind"))
    view = (component.get("config") or {}).get("view")
    return view in GENOMESPY_VIEWS.get(str(kind), frozenset())


def component_formats(component: dict, controls: dict | None = None) -> frozenset[ExportFormat]:
    """Formats *this* component can export as, given the view it opens on.

    A ``dot_plot`` on its enrichment view has a Python builder and its dot-plot
    view does not; a kind-level answer would get one of the two wrong.
    """
    component_type = component.get("component_type") or ""
    if component_type != "advanced_viz":
        return formats_for(component_type)
    plan = plan_for(component, controls)
    if plan is None:
        return frozenset()
    formats = COMPONENT_FORMATS["advanced_viz"]
    if plan.kind in HTML_UNAVAILABLE_KINDS or _opens_on_genomespy(component):
        formats = formats - {ExportFormat.HTML}
    if _plan_json_source(plan) in ("celery", "python"):
        return formats
    return formats - {ExportFormat.JSON}


def unsupported_reason(component_type: str, viz_kind: str | None = None) -> str | None:
    """Human-readable explanation for why JSON export is unavailable, if it is.

    Returns ``None`` when JSON export works. Used to populate the 422/501 body so a
    consumer learns what to do instead of just being refused.
    """
    if component_type not in COMPONENT_FORMATS:
        return f"Unknown component type {component_type!r}."
    if component_type == "jbrowse":
        return (
            "JBrowse components are an iframe onto a live JBrowse2 server and cannot "
            "be exported in any format."
        )
    if component_type == "highlight":
        return (
            "A highlight shows a component from another tab. Export that component "
            "instead: see `source` in this manifest entry."
        )
    if ExportFormat.JSON in formats_for(component_type, viz_kind):
        return None
    if component_type == "advanced_viz":
        kind = resolve_viz_kind(viz_kind)
        if advanced_viz_json_source(viz_kind) is None:
            return f"Unknown advanced_viz kind {viz_kind!r}."
        if kind in HTML_UNAVAILABLE_KINDS:
            return HTML_UNAVAILABLE_KINDS[kind]
        return _client_only_reason(str(kind))
    return (
        f"{component_type!r} components are not Plotly figures. Use format=html to embed "
        "the rendered component."
    )


def _client_only_reason(label: str) -> str:
    return (
        f"The {label!r} visualisation builds its Plotly spec in the browser, so no "
        "server-side figure exists yet. Use format=html, which runs the real "
        "renderer offline."
    )


def component_unsupported_reason(component: dict, controls: dict | None = None) -> str | None:
    """:func:`unsupported_reason` for one component, honouring its view."""
    component_type = component.get("component_type") or ""
    if component_type != "advanced_viz":
        return unsupported_reason(component_type)
    plan = plan_for(component, controls)
    if plan is None:
        return f"Unknown advanced_viz kind {component.get('viz_kind')!r}."
    if ExportFormat.JSON in component_formats(component, controls):
        return None
    if plan.kind not in AV_JSON_SOURCE:
        return f"Unknown advanced_viz kind {plan.kind!r}."
    if plan.kind in HTML_UNAVAILABLE_KINDS:
        return HTML_UNAVAILABLE_KINDS[plan.kind]
    label = f"{plan.kind} ({plan.view} view)" if plan.view else plan.kind
    return _client_only_reason(label)


def component_html_unavailable_reason(component: dict) -> str | None:
    """Why this component has no ``format=html`` form, or ``None`` when it has one."""
    if ExportFormat.HTML in component_formats(component):
        return None
    component_type = component.get("component_type") or ""
    if component_type == "advanced_viz":
        kind = str(resolve_viz_kind(component.get("viz_kind")))
        if kind in HTML_UNAVAILABLE_KINDS:
            return HTML_UNAVAILABLE_KINDS[kind]
        if _opens_on_genomespy(component):
            return _GENOMESPY_VIEW_REASON
    return unsupported_reason(component_type) or f"{component_type!r} cannot be embedded."


def component_json_source(component: dict, controls: dict | None = None) -> AvJsonSource | None:
    """:func:`advanced_viz_json_source` for one component, honouring its view."""
    plan = plan_for(component, controls)
    return _plan_json_source(plan) if plan is not None else None


# --- Self-check ------------------------------------------------------------------
# Cheap enough to run at import and it turns a silently-unclassified new component
# type into an immediate, obvious failure rather than a 422 in production.
_MISSING_TYPES = set(get_args(ComponentType)) - set(COMPONENT_FORMATS)
_MISSING_KINDS = set(get_args(AdvancedVizKind)) - set(AV_JSON_SOURCE)
if _MISSING_TYPES or _MISSING_KINDS:  # pragma: no cover - guards a coding error
    raise RuntimeError(
        "export capability matrix is incomplete: "
        f"component types {sorted(_MISSING_TYPES)}, viz kinds {sorted(_MISSING_KINDS)}"
    )
