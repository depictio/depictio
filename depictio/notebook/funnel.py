"""The funnel, computed from ``depictio_state`` when the document runs.

The exported document holds the analysis state as its parameters cell
(``depictio_state``, tagged ``parameters`` so ``quarto render -P`` can replace
it). Each funnel stage reads its filter from that state rather than from a
literal written at export time, so editing the state, or rendering with other
parameters, changes every tile computed in code the same way it changes the
tiles Depictio renders: the document cannot disagree with itself.

The rules are the server's (``routes._funnel_filter_is_active``, the funnel
modal's reconcile order, ``FUNNEL_MAX_STAGES``), and each stage's predicate is
built from the very source the export writes (``depictio.notebook.predicates``),
so the equivalence test that pins that source against ``add_filter`` covers
these stages too.

One part cannot be recomputed here: a cross-collection link (a filter on one
collection narrowing another through a shared key) is resolved by the server.
The export passes the resolution it made as ``links``; it is applied only
while the stage's filter is still the one it was resolved for, and a stage
whose filter changed says so instead of applying a stale resolution.

A genome region (or a protein's residue range) is a place to look, not a subset
to summarise: the server keeps it off cards, and off figures that never encode
one of its columns (``region_scope.scope_region_filters``). ``region=False``
computes the same frames without it, for those tiles.
"""

from __future__ import annotations

import datetime
import warnings
from typing import Any

import polars as pl

from .predicates import emit_filter_expr, emit_predicate
from .theme import palette_hex

#: ``routes.FUNNEL_MAX_STAGES``: the funnel view shows twelve stages at most.
FUNNEL_MAX_STAGES = 12

_NAMESPACE = {"pl": pl, "col": pl.col, "lit": pl.lit, "datetime": datetime}


# ``region_scope``'s locus sources: either half of a region pair.
_LOCUS_SOURCES = frozenset({"genome_selection", "residue_selection"})


def is_region_filter(f: Any) -> bool:
    """``region_scope.is_region_filter``."""
    if not isinstance(f, dict):
        return False
    meta = f.get("metadata") or {}
    return (f.get("source") or meta.get("source")) in _LOCUS_SOURCES


def _is_active(f: dict[str, Any]) -> bool:
    """``routes._funnel_filter_is_active``: only values that narrow data count."""
    value = f.get("value")
    if value is None or value == "":
        return False
    if isinstance(value, list):
        return any(v is not None for v in value)
    return True


def active_filters(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The state's active filters in funnel order: ranked ones first, then the rest."""
    filters = [f for f in state.get("filters") or [] if isinstance(f, dict) and _is_active(f)]
    order = [str(i) for i in ((state.get("funnel") or {}).get("stage_order") or [])]
    by_index = {str(f.get("index")): f for f in filters}
    ranked = [by_index.pop(i) for i in order if i in by_index]
    ranked += [f for f in filters if by_index.pop(str(f.get("index")), None) is not None]
    return ranked[:FUNNEL_MAX_STAGES]


def stage_filter(state: dict[str, Any], k: int) -> dict[str, Any] | None:
    """The filter at stage ``k`` (1-based) of ``state``'s funnel, or ``None``."""
    stages = active_filters(state)
    return stages[k - 1] if 0 < k <= len(stages) else None


def _field(f: dict[str, Any], key: str) -> Any:
    meta = f.get("metadata") or {}
    return f.get(key) if f.get(key) is not None else meta.get(key)


def _applies_to(f: dict[str, Any], dc_id: str | None) -> bool:
    target = str((f.get("metadata") or {}).get("dc_id") or "")
    return not target or not dc_id or target == str(dc_id)


def _apply_entry(frame: pl.DataFrame, entry: dict[str, Any]) -> pl.DataFrame:
    """One ``filter_metadata`` entry, as the export writes it and the server applies it."""
    column = str(_field(entry, "column_name") or "")
    itype = _field(entry, "interactive_component_type")
    if column not in frame.columns and itype != "__link_no_match__":
        return frame  # the server skips a filter on a column the collection lacks
    src = emit_predicate(
        itype,
        column,
        entry.get("value"),
        frame.schema.get(column),
        slider_mode=_field(entry, "slider_mode"),
        case_sensitive=_field(entry, "case_sensitive"),
        match_mode=_field(entry, "match_mode"),
        source=_field(entry, "source"),
    )
    if src is not None:
        scope = dict(_NAMESPACE)
        if src.prelude:
            exec("\n".join(src.prelude), scope)  # noqa: S102 - the export's own emitted source
        frame = frame.filter(eval(src.expr, scope))  # noqa: S307
        fexpr = _field(entry, "filter_expr")
        if fexpr:
            frame = frame.filter(eval(emit_filter_expr(str(fexpr)), dict(_NAMESPACE)))  # noqa: S307
    return frame


def _same_filter(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if a is None or b is None:
        return a is b
    return str(a.get("index")) == str(b.get("index")) and a.get("value") == b.get("value")


def funnel_stage(
    frame: pl.DataFrame,
    state: dict[str, Any],
    k: int,
    *,
    dc_id: str | None = None,
    links: list[dict[str, Any]] | None = None,
    resolved_for: dict[str, Any] | None = None,
    region: bool = True,
) -> pl.DataFrame:
    """``frame`` narrowed by stage ``k`` of ``state``'s funnel, for collection ``dc_id``.

    ``links`` are the cross-collection entries the export resolved for this
    stage, ``resolved_for`` the filter they were resolved for: applied while
    the stage's filter is unchanged, and reported otherwise. ``region=False``
    leaves a region stage (and what its links brought) out.
    """
    f = stage_filter(state, k)
    if not region and is_region_filter(f):
        return frame
    if f is not None and _applies_to(f, dc_id):
        frame = _apply_entry(frame, f)
    if links:
        if _same_filter(f, resolved_for):
            for entry in links:
                frame = _apply_entry(frame, entry)
        else:
            warnings.warn(
                f"stage {k}: the filter changed since export, and its cross-collection link "
                "was resolved by the server for the old value; it is not applied here. "
                "Export again from Depictio to resolve it for the new one.",
                stacklevel=2,
            )
    return frame


def funnel_rest(
    frame: pl.DataFrame,
    state: dict[str, Any],
    after: int,
    *,
    dc_id: str | None = None,
    region: bool = True,
) -> pl.DataFrame:
    """``frame`` narrowed by every stage past ``after``: filters the state gained since export."""
    for k in range(after + 1, len(active_filters(state)) + 1):
        frame = funnel_stage(frame, state, k, dc_id=dc_id, region=region)
    return frame


#: ``FunnelView.tsx``'s marker palette, in order, as Mantine resolves it.
FUNNEL_PALETTE: tuple[str, ...] = tuple(
    palette_hex(name, "", shade=shade)
    for name, shade in (
        ("teal", 6),
        ("blue", 6),
        ("violet", 6),
        ("orange", 6),
        ("pink", 6),
        ("cyan", 6),
        ("grape", 6),
        ("lime", 7),
    )
)


def funnel_figure(stages: list[str], series: list[tuple[str, list[int]]]):
    """The dashboard's funnel view as a Plotly figure.

    ``stages`` are the axis labels top to bottom (``0. Unfiltered`` first),
    ``series`` one ``(collection, rows after each stage)`` pair per data
    collection. One collection is drawn at a time, picked from a dropdown.
    """
    import plotly.graph_objects as go

    fig = go.Figure(
        go.Funnel(
            name=series[0][0],
            orientation="h",
            y=stages,
            x=series[0][1],
            textinfo="value+percent initial",
            textposition="inside",
            hovertemplate="%{y}<br>%{x} rows<extra>%{fullData.name}</extra>",
            marker={"color": FUNNEL_PALETTE[0]},
            connector={"line": {"color": "rgba(0,0,0,0.08)", "width": 1}},
        )
    )
    # One collection at a time: the tables span three orders of magnitude, and on
    # one shared axis the small ones collapse into slivers with no room for their
    # numbers. The dropdown is Plotly's own, so it works in the exported HTML with
    # nothing to run — the report's own script replaces it with an HTML select,
    # which Plotly cannot place here: a menu takes paper coordinates, and this
    # figure's left third is the gutter its stage labels need. It swaps the one
    # trace's data rather than toggling the visibility of seven, because a funnel
    # with hidden traces drops its stage labels off the axis entirely.
    fig.update_layout(
        updatemenus=[
            {
                "name": "Data collection",
                "buttons": [
                    {
                        "label": name,
                        "method": "restyle",
                        "args": [
                            {
                                "x": [rows],
                                "name": [name],
                                "marker.color": [FUNNEL_PALETTE[i % len(FUNNEL_PALETTE)]],
                            }
                        ],
                    }
                    for i, (name, rows) in enumerate(series)
                ],
                "direction": "down",
                "showactive": True,
                "x": 0,
                "xanchor": "left",
                "y": 1.18,
                "yanchor": "top",
                # The app's `Select`: white on a gray-4 border, gray-7 text, the
                # system stack at Mantine's `sm`.
                "bgcolor": "#ffffff",
                "bordercolor": "#ced4da",
                "borderwidth": 1,
                "pad": {"l": 10, "r": 10, "t": 7, "b": 7},
                "font": {
                    "family": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                    "size": 13,
                    "color": "#495057",
                },
            }
        ],
        template="plotly_white",
        showlegend=False,
        # No room reserved above for the menu: Plotly grows the top margin itself
        # while it is showing, and gives it back once the select has taken over.
        margin={"l": 260, "r": 24, "t": 28, "b": 24},
        yaxis={"autorange": "reversed"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#495057"},
        height=max(290, 130 + len(stages) * 46),
    )
    return fig
