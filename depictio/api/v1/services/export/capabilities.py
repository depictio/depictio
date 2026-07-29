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
"""

from enum import Enum
from typing import Literal, get_args

from depictio.models.components.types import AdvancedVizKind, ComponentType


class ExportFormat(str, Enum):
    """Wire value of the ``format`` query parameter."""

    JSON = "json"
    HTML = "html"


#: Legacy ``viz_kind`` strings that are still present in persisted ``stored_metadata``
#: but absent from the ``AdvancedVizKind`` Literal. Stored metadata is an untyped
#: ``list[dict]`` and bypasses Pydantic entirely, so these reach us at runtime;
#: ``ComponentRenderer.tsx`` maps ``ancombc_differentials`` onto ``DaBarplotRenderer``
#: and we must resolve it the same way.
VIZ_KIND_ALIASES: dict[str, str] = {
    "ancombc_differentials": "da_barplot",
}


def resolve_viz_kind(viz_kind: str | None) -> str | None:
    """Normalise a persisted ``viz_kind`` onto its canonical name."""
    if viz_kind is None:
        return None
    return VIZ_KIND_ALIASES.get(viz_kind, viz_kind)


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
}

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
    kind = resolve_viz_kind(viz_kind)
    if kind is None or kind not in AV_JSON_SOURCE:
        return None
    # A registered Python builder wins over the static table so a kind becomes
    # exportable the moment its module is imported, without a second edit here.
    if kind in _python_builder_kinds():
        return "python"
    return AV_JSON_SOURCE[kind]


def formats_for(component_type: str, viz_kind: str | None = None) -> frozenset[ExportFormat]:
    """Formats this specific component can actually be exported as.

    Unlike ``COMPONENT_FORMATS`` this accounts for the per-kind JSON gate on
    ``advanced_viz``, so it is what both the manifest route and the export route
    should consult.
    """
    formats = COMPONENT_FORMATS.get(component_type, frozenset())
    if component_type != "advanced_viz":
        return formats
    if advanced_viz_json_source(viz_kind) in ("celery", "python"):
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
    if ExportFormat.JSON in formats_for(component_type, viz_kind):
        return None
    if component_type == "advanced_viz":
        kind = resolve_viz_kind(viz_kind)
        if advanced_viz_json_source(viz_kind) is None:
            return f"Unknown advanced_viz kind {viz_kind!r}."
        return (
            f"The {kind!r} visualisation builds its Plotly spec in the browser, so no "
            "server-side figure exists yet. Use format=html, which runs the real "
            "renderer offline."
        )
    return (
        f"{component_type!r} components are not Plotly figures. Use format=html to embed "
        "the rendered component."
    )


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
