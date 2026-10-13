"""Which Python builder draws a stored advanced-viz component, and from what config.

Four kinds were folded into a surviving kind with a ``view`` switch
(``configs._KIND_ALIASES``)::

    ma, qq        -> volcano       view: volcano | ma | qq
    enrichment    -> dot_plot      view: dotplot | enrichment
    roc_pr_curve  -> pr_benchmark  view: pr | roc | both

The Python builders were written one per drawing, before that merge, and still
are: ``ma.py`` draws an MA plot whatever the stored kind says. So exporting a
component means two lookups, not one — the kind the dashboard knows it by, and
the view it opens on — and an export that read only the kind would serve a
volcano for a tile that shows an MA plot.

A stored component can hold either shape: a retired kind (a document saved
before the merge and not re-saved since) or the survivor with its ``view``.
:func:`plan_for` routes both through ``apply_kind_aliases``, the same rewrite
the models apply on validation, so the two cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from depictio.models.components.advanced_viz.configs import (
    apply_kind_aliases,
)
from depictio.models.components.advanced_viz.configs import (
    resolve_viz_kind as _resolve_retired_kind,
)

#: Names older than the ``_KIND_ALIASES`` merge, which the models rewrite in
#: ``AdvancedVizComponent`` rather than in the config. Stored metadata bypasses
#: that model, so the rewrite is repeated here.
_LEGACY_KIND_NAMES: dict[str, str] = {"ancombc_differentials": "da_barplot"}

#: ``survivor -> {view: builders, in trace order}``. A view absent here draws
#: with the survivor's own builder (or none, when the kind is client-only).
_VIEW_BUILDERS: dict[str, dict[str, tuple[str, ...]]] = {
    "volcano": {"volcano": ("volcano",), "ma": ("ma",), "qq": ("qq",)},
    "dot_plot": {"dotplot": ("dot_plot",), "enrichment": ("enrichment",)},
    # `both` stays in PR space: the operating points with the sweep they were
    # picked off, which is what PrBenchmarkRenderer.tsx draws for it.
    "pr_benchmark": {
        "pr": ("pr_benchmark",),
        "roc": ("roc_pr_curve",),
        "both": ("pr_benchmark", "roc_pr_curve"),
    },
}

#: The view each survivor opens on when its config names none.
_DEFAULT_VIEW: dict[str, str] = {"volcano": "volcano", "dot_plot": "dotplot", "pr_benchmark": "pr"}


def canonical_kind(viz_kind: str | None) -> str | None:
    """The kind a stored ``viz_kind`` string is today, after every rename."""
    if viz_kind is None:
        return None
    return _resolve_retired_kind(_LEGACY_KIND_NAMES.get(viz_kind, viz_kind))


@dataclass(frozen=True)
class BuildPlan:
    """How to draw one advanced-viz component server-side.

    Attributes:
        kind: The surviving kind, as the dashboard knows the component.
        view: The view drawn, or ``None`` for a kind without views.
        builders: Registered builders whose traces make the figure, in order.
        config: The config those builders read (survivor fields, view fallbacks
            applied).
        controls: Intra-viz state per builder; the shared ``controls`` plus
            whatever the view implies (e.g. ROC space for ``roc``).
        source: ``(wf_id, dc_id)`` to read instead of the component's own
            collection, when the view draws from a table of its own.
    """

    kind: str
    view: str | None
    builders: tuple[str, ...]
    config: dict[str, Any]
    controls: dict[str, dict[str, Any]] = field(default_factory=dict)
    source: tuple[str, str] | None = None


def _survivor_config(component: dict) -> dict[str, Any]:
    """The component's config as its surviving kind reads it."""
    raw = dict(component.get("config") or {})
    stored_kind = raw.get("viz_kind") or component.get("viz_kind")
    stored_kind = _LEGACY_KIND_NAMES.get(stored_kind, stored_kind)
    if stored_kind:
        raw["viz_kind"] = stored_kind
    return apply_kind_aliases(raw)


def _requested_view(kind: str, config: dict[str, Any], controls: dict[str, Any]) -> str | None:
    views = _VIEW_BUILDERS.get(kind)
    if views is None:
        return None
    for candidate in (controls.get("view"), config.get("view"), config.get("default_view")):
        if isinstance(candidate, str) and candidate in views:
            return candidate
    return _DEFAULT_VIEW[kind]


def plan_for(component: dict, controls: dict[str, Any] | None = None) -> BuildPlan | None:
    """Resolve what to build for an advanced-viz component.

    Args:
        component: A ``stored_metadata`` entry.
        controls: The caller's ``?controls=`` object. ``view`` picks the view, the
            rest is passed to the builders as their intra-viz state.

    Returns:
        ``None`` when the component names no kind at all.
    """
    controls = dict(controls or {})
    config = _survivor_config(component)
    kind = canonical_kind(config.get("viz_kind") or component.get("viz_kind"))
    if kind is None:
        return None

    view = _requested_view(kind, config, controls)
    builders = _VIEW_BUILDERS.get(kind, {}).get(view or "", (kind,))
    shared = {k: v for k, v in controls.items() if k != "view"}
    per_builder = {name: dict(shared) for name in builders}
    source: tuple[str, str] | None = None

    if kind == "volcano" and view == "ma":
        # VolcanoConfig documents both fallbacks: M is the effect size when no
        # separate log2 fold-change column is bound, and an MA table of its own
        # (canonical columns) stands in when the volcano table has no A column.
        # Same rule as `maTableOf` (deViews.ts): both ids, and no A column on
        # the volcano's own table.
        if (
            not config.get("avg_log_intensity_col")
            and config.get("ma_wf_id")
            and config.get("ma_dc_id")
        ):
            source = (str(config["ma_wf_id"]), str(config["ma_dc_id"]))
            config = {
                **config,
                "feature_id_col": "feature_id",
                "avg_log_intensity_col": "avg_log_intensity",
                "log2_fold_change_col": "log2_fold_change",
                "significance_col": "significance",
                "label_col": None,
            }
        else:
            config = {
                **config,
                "log2_fold_change_col": config.get("log2_fold_change_col")
                or config.get("effect_size_col"),
            }
    elif kind == "volcano" and view == "qq":
        config = {
            **config,
            "p_value_col": config.get("p_value_col") or config.get("significance_col"),
        }
    elif kind == "pr_benchmark" and "roc_pr_curve" in per_builder:
        # `roc` is the sweep alone, in ROC space when an FPR column is bound;
        # `both` overlays the sweep on the points, so it stays in PR space. An
        # explicit `mode` (pr | roc | threshold) still wins.
        sweep_mode = "roc" if view == "roc" and config.get("fpr_col") else "pr"
        per_builder["roc_pr_curve"].setdefault("mode", sweep_mode)

    return BuildPlan(
        kind=kind,
        view=view,
        builders=builders,
        config=config,
        controls=per_builder,
        source=source,
    )
