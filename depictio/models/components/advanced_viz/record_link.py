"""A record card's link to the component whose selection drives it.

`RecordCardConfig.linked_component` names another component of the same
dashboard by its YAML `tag`. Three places need to agree on what that means:
the dashboard import, which rewrites the tag to the component's `index` (the
key selection filters carry), the model validation, which refuses a tag that
names nothing, and the shipped-template lint, which checks that the named
component actually emits a selection the card can follow. The rules live here
so none of them drifts from the others.

Everything takes plain component dicts, the shape a dashboard YAML parses to,
so the lint can run on raw files without building models first.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

Component = Mapping[str, Any]

# Advanced-viz kinds that emit a `scatter_selection`, with the config fields
# the emitted column is read from, in order. Mirrors
# `advancedVizSelectionColumn` in packages/depictio-react-core/src/selection.ts:
# each of these only emits once `selection_enabled` is true, and falls back to
# its identifying column when no `selection_column` is named.
SELECTION_EMITTING_KINDS: dict[str, tuple[str, ...]] = {
    "embedding": ("selection_column", "sample_id_col"),
    "manhattan": ("selection_column",),
    "genome_view": ("selection_column",),
    "profile": ("selection_column", "series_col"),
    "scatter_xy": ("selection_column", "label_col"),
    "genome_chord": ("selection_column", "label_col"),
}


class LinkedComponentError(ValueError):
    """A `linked_component` that names no component of its dashboard."""


def _config(comp: Component) -> Mapping[str, Any]:
    config = comp.get("config")
    return config if isinstance(config, Mapping) else {}


def viz_kind_of(comp: Component) -> str | None:
    kind = comp.get("viz_kind") or _config(comp).get("viz_kind")
    return str(kind) if kind else None


def linked_component_of(comp: Component) -> str | None:
    """The `linked_component` a record card declares, or None.

    Read off any advanced_viz config rather than off record cards only: a
    `use:` render carries its kind in the catalog, not in the YAML, and the
    config model already refuses the field on every other kind.
    """
    if comp.get("component_type") != "advanced_viz":
        return None
    value = _config(comp).get("linked_component")
    return str(value) if value else None


def component_refs(comp: Component) -> set[str]:
    """The names a component answers to: its tag and, when set, its index."""
    return {str(v) for v in (comp.get("tag"), comp.get("index")) if v}


def resolve_linked_components(components: Iterable[Component]) -> dict[int, int]:
    """Position of each linked record card to the position of its source.

    Raises `LinkedComponentError` naming every card whose `linked_component`
    matches no tag or index of this dashboard, or names the card itself.
    """
    comps = list(components)
    by_ref: dict[str, int] = {}
    for pos, comp in enumerate(comps):
        for ref in component_refs(comp):
            by_ref.setdefault(ref, pos)

    resolved: dict[int, int] = {}
    errors: list[str] = []
    for pos, comp in enumerate(comps):
        ref = linked_component_of(comp)
        if ref is None:
            continue
        label = comp.get("tag") or f"component[{pos}]"
        target = by_ref.get(ref)
        if target is None:
            errors.append(
                f"[{label}] config.linked_component: '{ref}' matches no component "
                "tag or index in this dashboard"
            )
        elif target == pos:
            errors.append(f"[{label}] config.linked_component: a card cannot link to itself")
        else:
            resolved[pos] = target
    if errors:
        raise LinkedComponentError("\n".join(errors))
    return resolved


def emitted_selection_column(
    comp: Component, config: Mapping[str, Any] | None = None
) -> str | None:
    """The column a component's selection carries, or None if it emits none.

    `config` overrides the component's own config block, for an advanced_viz
    whose config comes from a `use:` catalog render.
    """
    ctype = comp.get("component_type")
    if ctype == "table":
        if comp.get("row_selection_enabled") and comp.get("row_selection_column"):
            return str(comp["row_selection_column"])
        return None
    if ctype in ("figure", "map"):
        if comp.get("selection_enabled") and comp.get("selection_column"):
            return str(comp["selection_column"])
        return None
    if ctype == "advanced_viz":
        cfg = config if config is not None else _config(comp)
        fields = SELECTION_EMITTING_KINDS.get(str(cfg.get("viz_kind") or viz_kind_of(comp)))
        if not fields or cfg.get("selection_enabled") is not True:
            return None
        for field in fields:
            if cfg.get(field):
                return str(cfg[field])
    return None


def linked_component_problems(
    components: Iterable[Component],
    resolve_config: Callable[[Component], Mapping[str, Any] | None] | None = None,
) -> list[str]:
    """Why each linked record card's source cannot drive it, if it cannot.

    The source has to emit a selection, and when it reads the same data
    collection as the card, on the card's own `id_col`: the card matches the
    picked values against that column, so any other column matches nothing.
    A source on another collection is left alone, because its pick reaches the
    card through a project link and the two sides of a link are named
    independently.

    `resolve_config` supplies an advanced_viz config the YAML does not spell
    out (a `use:` render); without one the raw `config` block is read.
    """
    comps = list(components)
    try:
        links = resolve_linked_components(comps)
    except LinkedComponentError as exc:
        return str(exc).splitlines()

    problems: list[str] = []
    for card_pos, source_pos in links.items():
        card, source = comps[card_pos], comps[source_pos]
        label = card.get("tag") or f"component[{card_pos}]"
        source_label = source.get("tag") or source.get("index") or f"component[{source_pos}]"
        config = resolve_config(source) if resolve_config else None
        column = emitted_selection_column(source, config)
        if column is None:
            problems.append(
                f"[{label}] linked_component '{source_label}' emits no selection "
                "(a table needs row_selection_enabled + row_selection_column, a "
                "figure or map selection_enabled + selection_column, an "
                f"advanced_viz one of {sorted(SELECTION_EMITTING_KINDS)} with "
                "selection_enabled)"
            )
            continue
        id_col = str(_config(card).get("id_col") or "id")
        same_dc = card.get("data_collection_tag") == source.get("data_collection_tag")
        if same_dc and column != id_col:
            problems.append(
                f"[{label}] linked_component '{source_label}' selects on '{column}' "
                f"but the card matches on id_col '{id_col}'"
            )
    return problems


def _layout(comp: Component) -> Mapping[str, Any]:
    layout = comp.get("layout")
    return layout if isinstance(layout, Mapping) else {}


def side_panel_pairs(components: Iterable[Component]) -> list[tuple[int, int]]:
    """`(source_pos, card_pos)` for every card laid out as its source's side panel.

    A side panel shares its source's section and row (same `y`) and touches it
    edge to edge on either side. The viewer applies the same rule to decide
    which cards collapse into a rail (`recordPanelLayout.ts`).
    """
    comps = list(components)
    try:
        links = resolve_linked_components(comps)
    except LinkedComponentError:
        return []
    pairs: list[tuple[int, int]] = []
    for card_pos, source_pos in links.items():
        card, source = comps[card_pos], comps[source_pos]
        if card.get("section") != source.get("section"):
            continue
        cl, sl = _layout(card), _layout(source)
        if any(k not in cl or k not in sl for k in ("x", "y", "w")):
            continue
        if cl["y"] != sl["y"]:
            continue
        if cl["x"] == sl["x"] + sl["w"] or sl["x"] == cl["x"] + cl["w"]:
            pairs.append((source_pos, card_pos))
    return pairs
