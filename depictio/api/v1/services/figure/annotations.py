"""The automatic marks a figure draws on itself (``FigureAnnotations``).

A mark is a small piece of text the server places on the finished, styled
figure: the value on every bar, the number of rows behind each group of a box
or violin plot, the value inside each heatmap cell, a note saying what the
figure does not show. Declared on the component (``annotations: {bar_labels:
value, ...}``) or automatic by figure type; a given block draws only the marks
it turns on, so ``{}`` draws none (see ``FigureAnnotations``).

Drawn on the figure DICT, right after ``apply_figure_style``: the hidden-note
mark counts the categories the overview look folded into its grey "Other"
(``layout.meta["depictio_folded"]``). Pure functions on dicts, like the style
presets; the callers wrap the call in a try/except so a mark never costs the
figure.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from depictio.models import palettes
from depictio.models.palettes.cvd import contrast_ratio

# Automatic marks size themselves to the figure: labels on a 40-bar chart are
# noise, cell values on a 50x50 heatmap are a blur. A declared mark draws
# whatever it is on -- the author asked.
_MAX_AUTO_BARS = 12
_MAX_AUTO_CELLS = 400

# The one ink a label on a dark cell can fall back to, beside the theme's own
# text colour (``chrome``); whichever of the two reads better over the trace's
# colourscale wins.
_WHITE_INK = "#ffffff"

_HEX_COLOUR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Bytes per element of the dtypes Plotly 6 serialises numpy arrays to.
_DTYPES = {"f8", "f4", "i1", "i2", "i4", "i8", "u1", "u2", "u4", "u8"}


# ---------------------------------------------------------------------------
# small helpers (pure functions on dicts, as in ``overview_style``)


def _sub(container: dict, key: str) -> dict:
    """A copy of ``container[key]`` (a dict), stored back so it can be written."""
    value = container.get(key)
    copied = dict(value) if isinstance(value, dict) else {}
    container[key] = copied
    return copied


def _kind(trace: dict) -> str:
    return str(trace.get("type", "scatter"))


def _horizontal(trace: dict) -> bool:
    return trace.get("orientation") == "h"


def _values(raw: Any) -> list | None:
    """A trace array as a plain list: a list, or a Plotly 6 typed buffer."""
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, dict) and "bdata" in raw:
        import base64

        import numpy as np

        if str(raw.get("dtype")) not in _DTYPES:
            return None
        try:
            return np.frombuffer(
                base64.b64decode(raw["bdata"]), dtype=np.dtype(str(raw["dtype"])).newbyteorder("<")
            ).tolist()
        except (ValueError, TypeError):
            return None
    return None


def _axis_key(letter: str, trace: dict) -> str:
    ref = trace.get(f"{letter}axis")
    suffix = str(ref)[1:] if isinstance(ref, str) and ref.startswith(letter) else ""
    return f"{letter}axis{suffix}"


def _numeric(values: list) -> list[float | None]:
    """The values as floats, ``None`` where a cell is missing or not a number."""
    return [
        float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None
        for v in values
    ]


# ---------------------------------------------------------------------------
# which marks to draw


def _declared(spec: dict) -> dict:
    """The marks an ``annotations`` block turns on: exactly its truthy fields."""
    bar_labels = spec.get("bar_labels")
    return {
        "bar_labels": bar_labels if bar_labels in ("value", "percent") else None,
        "group_n": bool(spec.get("group_n")),
        "cell_values": bool(spec.get("cell_values")),
        "hidden_note": bool(spec.get("hidden_note")),
    }


def _automatic(traces: list[dict], layout: dict) -> dict:
    """The marks a figure draws by its own type when no block is declared."""
    marks = {"bar_labels": None, "group_n": False, "cell_values": False, "hidden_note": False}

    # plotly-express sets `relative` on every bar chart: only two or more bar
    # traces stacked on each other make a stack, a single series never does.
    barmode = layout.get("barmode")
    bars = [t for t in traces if _kind(t) == "bar"]
    stacked = barmode in ("stack", "relative") and len(bars) > 1
    if bars and not stacked:
        total = 0
        for trace in bars:
            # The categories are one per bar: x on a vertical bar, y on a horizontal one.
            values = _values(trace.get("y" if _horizontal(trace) else "x"))
            total += len(values) if values else 0
        if total <= _MAX_AUTO_BARS:
            marks["bar_labels"] = "value"

    marks["group_n"] = any(_kind(t) in ("box", "violin") for t in traces)

    for trace in traces:
        if _kind(trace) != "heatmap":
            continue
        cells = _cell_count(trace)
        if cells is not None and cells <= _MAX_AUTO_CELLS:
            marks["cell_values"] = True
            break

    meta = layout.get("meta")
    folded = meta.get("depictio_folded") if isinstance(meta, dict) else None
    if isinstance(folded, int) and folded > 0:
        marks["hidden_note"] = True
    return marks


def _resolve(
    spec: dict | None, figure_style: str | None, traces: list[dict], layout: dict
) -> dict | None:
    """The marks to draw, or ``None`` for nothing (a declared-empty block, or classic)."""
    if spec is not None:
        return _declared(spec)
    if figure_style == "classic":
        return None
    return _automatic(traces, layout)


# ---------------------------------------------------------------------------
# bar labels


def _draw_bar_labels(traces: list[dict], mode: str, label: str) -> None:
    """Every bar carries its value, or its share of its trace's total."""
    colour = palettes.chrome(mode)["text"]
    for trace in traces:
        if _kind(trace) != "bar":
            continue
        horizontal = _horizontal(trace)
        value_key = "x" if horizontal else "y"
        values = _numeric(_values(trace.get(value_key)) or [])
        if not values:
            continue
        if label == "value":
            # Counts print whole; measures keep two decimals, trailing zeros dropped.
            whole = all(v is None or float(v).is_integer() for v in values)
            fmt = ",.0f" if whole else ",.2~f"
            trace["texttemplate"] = f"%{{{value_key}:{fmt}}}"
        else:  # percent of the trace's total, carried in customdata
            if trace.get("customdata") is not None:
                continue  # the author's own hover data is not ours to replace
            total = sum(v for v in values if v is not None)
            if total == 0:
                continue
            trace["customdata"] = [v / total if v is not None else None for v in values]
            trace["texttemplate"] = "%{customdata:.0%}"
        trace["textposition"] = "outside"
        trace["cliponaxis"] = False
        _sub(trace, "textfont")["color"] = colour


# ---------------------------------------------------------------------------
# group n


def _draw_group_n(traces: list[dict], layout: dict) -> None:
    """The number of rows behind each group, on its tick or its legend entry.

    One box (or violin) trace holding every category writes the n beside each
    category tick; several traces sharing the categories (a group-by ``color``)
    would repeat each tick, so each trace's n goes into its legend name
    instead. A trace whose points are not on the figure (a pre-aggregated
    ``go.Box``) says nothing: no n beats a wrong n.
    """
    infos: list[tuple[dict, str, dict[str, int]]] = []
    owners: dict[str, set[int]] = {}
    for trace in traces:
        if _kind(trace) not in ("box", "violin"):
            continue
        cat_letter = "y" if _horizontal(trace) else "x"
        cats = _values(trace.get(cat_letter))
        vals = _values(trace.get("x" if cat_letter == "y" else "y"))
        if cats is None or vals is None or len(vals) != len(cats):
            continue
        counts: dict[str, int] = {}
        for cat in cats:
            if cat is None:
                continue
            counts[str(cat)] = counts.get(str(cat), 0) + 1
        if not counts:
            continue
        infos.append((trace, _axis_key(cat_letter, trace), counts))
        for cat in counts:
            owners.setdefault(cat, set()).add(len(infos) - 1)

    if not infos:
        return

    if any(len(seen) > 1 for seen in owners.values()):
        for trace, _, counts in infos:
            name = trace.get("name")
            if isinstance(name, str) and name:
                trace["name"] = f"{name} (n={sum(counts.values())})"
        return

    by_axis: dict[str, dict[str, int]] = {}
    first_seen: dict[str, dict[str, Any]] = {}
    for _, axis_key, counts in infos:
        seen = by_axis.setdefault(axis_key, {})
        values = first_seen.setdefault(axis_key, {})
        for cat, n in counts.items():
            seen[cat] = seen.get(cat, 0) + n
            values.setdefault(cat, cat)
    for axis_key, counts in by_axis.items():
        axis = layout.get(axis_key)
        if isinstance(axis, dict) and (
            axis.get("tickvals") is not None or axis.get("ticktext") is not None
        ):
            continue  # the author labels their own ticks
        axis = _sub(layout, axis_key)
        order = list(counts)
        axis["tickvals"] = [first_seen[axis_key][cat] for cat in order]
        axis["ticktext"] = [f"{cat} (n={counts[cat]})" for cat in order]


# ---------------------------------------------------------------------------
# cell values


def _cell_count(trace: dict) -> int | None:
    """How many cells a heatmap draws, or ``None`` when it cannot be told."""
    z = trace.get("z")
    if isinstance(z, dict):
        # A Plotly 6 typed buffer: its shape ("2, 3") says the grid.
        shape = z.get("shape")
        if not isinstance(shape, str):
            return None
        try:
            dims = [int(d) for d in shape.replace(" ", "").split(",") if d]
        except ValueError:
            return None
        cells = 1
        for dim in dims:
            cells *= dim
        return cells
    if not isinstance(z, (list, tuple)) or not z:
        return None
    rows = [r for r in z if isinstance(r, (list, tuple))]
    if rows:
        return len(z) * max(len(r) for r in rows)
    return len(z)


def _scale_stops(trace: dict, layout: dict) -> list[str]:
    """The hex colours of the trace's colourscale (its own, or a shared coloraxis)."""
    raw = trace.get("colorscale")
    if not raw:
        ref = trace.get("coloraxis")
        axis = layout.get(str(ref)) if isinstance(ref, str) else None
        raw = axis.get("colorscale") if isinstance(axis, dict) else None
    if isinstance(raw, str):
        # A named scale: resolve it through plotly's own table.
        from plotly.colors import PLOTLY_SCALES

        raw = PLOTLY_SCALES.get(raw)
    stops: list[str] = []
    if isinstance(raw, (list, tuple)):
        for stop in raw:
            if isinstance(stop, (list, tuple)) and len(stop) == 2:
                colour = stop[1]
                if isinstance(colour, str) and _HEX_COLOUR.match(colour.strip()):
                    stops.append(colour.strip())
    return stops


def _cell_ink(stops: list[str], mode: str) -> str:
    """The one ink for every cell value: whichever candidate reads better over the scale.

    Plotly draws a heatmap's labels in one font, so the colour is chosen for
    the scale's weakest spot rather than for each cell.
    """
    text = palettes.chrome(mode)["text"]
    if not stops:
        return text

    def worst(candidate: str) -> float:
        return min(contrast_ratio(candidate, stop) for stop in stops)

    return max((text, _WHITE_INK), key=worst)


def _draw_cell_values(traces: list[dict], layout: dict, mode: str) -> None:
    """Each cell prints its value, in the ink that reads over the colourscale."""
    for trace in traces:
        if _kind(trace) != "heatmap":
            continue
        trace["texttemplate"] = "%{z:.2~f}"
        _sub(trace, "textfont")["color"] = _cell_ink(_scale_stops(trace, layout), mode)


# ---------------------------------------------------------------------------
# hidden note


def _draw_hidden_note(layout: dict, mode: str) -> None:
    """What the figure does not show, in small ink at the bottom right."""
    meta = layout.get("meta")
    folded = meta.get("depictio_folded") if isinstance(meta, dict) else None
    if not isinstance(folded, int) or folded <= 0:
        return
    note = {
        "text": f"{folded} more not shown",
        "xref": "paper",
        "yref": "paper",
        "x": 1,
        "y": 0,
        "xanchor": "right",
        "yanchor": "bottom",
        "showarrow": False,
        "font": {"size": 11, "color": palettes.annotation_ink(mode)},
    }
    layout["annotations"] = [*(layout.get("annotations") or []), note]


# ---------------------------------------------------------------------------
# entry point


def apply_annotations(
    figure: dict,
    spec: dict | None,
    *,
    figure_style: str | None,
    theme: str,
) -> dict:
    """Return ``figure`` with its automatic marks drawn; the input is left untouched.

    Args:
        figure: A serialised Plotly figure (``{"data": [...], "layout": {...}}``),
            as ``apply_figure_style`` leaves it.
        spec: The component's ``annotations`` block (a dict or a
            ``FigureAnnotations``). ``None`` draws every mark automatic by
            figure type (nothing under the ``classic`` style); a given block
            draws only the marks it turns on, so ``{}`` draws none.
        figure_style: The style the figure was drawn in (``default``,
            ``minimal``, ``classic``); only the automatic marks care.
        theme: ``light`` or ``dark``, for the label inks.
    """
    if not isinstance(figure, dict):
        return figure
    if hasattr(spec, "model_dump"):
        spec = spec.model_dump()
    if spec is not None and not isinstance(spec, dict):
        spec = None

    mode = "dark" if theme == "dark" else "light"
    layout = {
        k: (v if k == "template" else copy.deepcopy(v))
        for k, v in (figure.get("layout") or {}).items()
    }
    traces = [dict(t) for t in (figure.get("data") or []) if isinstance(t, dict)]

    marks = _resolve(spec, figure_style, traces, layout)
    if marks:
        if marks["bar_labels"]:
            _draw_bar_labels(traces, mode, marks["bar_labels"])
        if marks["group_n"]:
            _draw_group_n(traces, layout)
        if marks["cell_values"]:
            _draw_cell_values(traces, layout, mode)
        if marks["hidden_note"]:
            _draw_hidden_note(layout, mode)

    out = dict(figure)
    out["layout"] = layout
    out["data"] = traces
    return out


def marks_off_patch(marked: dict, plain: dict) -> dict | None:
    """What turns ``marked`` back into ``plain``: ``None`` when they are the same.

    The catalog preview ships the marked figure and this patch, so its
    "Automatic marks" switch can drop the marks without a second figure.
    ``{"data": [{"i": n, "set": {...}, "unset": [...]}], "layout": {"set", "unset"}}``,
    top-level keys only (a mark replaces a key whole: ``textfont``, ``xaxis``,
    ``annotations``). Applied by ``applyMarksOff`` in depictio-react-core.
    """

    def diff(after: dict, before: dict) -> dict:
        changed = {k: v for k, v in before.items() if after.get(k, _MISSING) != v}
        gone = [k for k in after if k not in before]
        out: dict[str, Any] = {}
        if changed:
            out["set"] = changed
        if gone:
            out["unset"] = gone
        return out

    data: list[dict[str, Any]] = []
    for i, (after, before) in enumerate(zip(marked.get("data") or [], plain.get("data") or [])):
        entry = diff(after, before)
        if entry:
            data.append({"i": i, **entry})
    layout = diff(marked.get("layout") or {}, plain.get("layout") or {})
    if not data and not layout:
        return None
    return {"data": data, "layout": layout}


_MISSING = object()
