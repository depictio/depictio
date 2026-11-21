"""The overview look: depictio's default figure style.

A figure is drawn for a reader scanning a dashboard, not for the person who
built it, so the overview look applies a few rules to the finished, serialised
figure (after the theme and brand templates, like every style preset):

a. *One hue.* Where colour only repeats the axis (px ``color=x``: every trace
   holds one category and is named after it), the traces take one colour and
   lose their legend.
b. *Sorted bars.* A categorical bar axis with no order of its own is ordered by
   total, the biggest first (on top for horizontal bars).
c. *Remainder last, long tails folded.* Traces named Other / Unclassified / NA
   come last and take their semantic grey; beyond ``top_n`` colour traces, the
   smallest ones share the "Other" grey and one legend entry. Colour only: no
   trace and no point is dropped.
d. *Light chrome.* Grid on the value axis only for bars, boxes and violins, in a
   near-transparent ink; no ticks; a soft zero line; the shared plot font and
   hover label.
e. *Rounded bars.*
f. *Markers by point count.* Fewer points are larger, bolder and outlined; a
   dense cloud is small and faint (see ``palettes.scatter_marker``).

Every rule yields to the author: a value the figure sets itself is never
replaced (a template-level value counts as unset). The constants live in the
shared palette JSON (``style`` block) and are mirrored for the viewer's own
renderers in ``packages/depictio-react-core/src/palettes.ts``.

The function is pure: it copies what it changes and shares the data arrays,
so the caller can hand it a cached figure.
"""

from __future__ import annotations

import base64
import copy
import re
from collections.abc import Iterable
from typing import Any

import numpy as np

from depictio.cli.cli.utils.mantine_templates import FONT_FAMILY as STOCK_FONT_FAMILY
from depictio.models import palettes

OTHER_LEGENDGROUP = "__other__"

_BAR_LIKE = frozenset({"bar", "box", "violin"})
_SCATTER = frozenset({"scatter", "scattergl"})
# Trace types whose colour is a series colour a legend names.
_COLOURED = frozenset({"bar", "box", "violin", "histogram", "scatter", "scattergl"})
# Types drawn on plain x/y axes: the chrome rules apply only to figures made of these.
_CARTESIAN = frozenset({"bar", "box", "violin", "histogram", "scatter", "scattergl"})

_AXIS_KEY = re.compile(r"^([xy])axis(\d*)$")
# A symbol drawn as a line is the mark itself: its size is left as drawn.
_LINE_SYMBOL = re.compile(r"^(line-|asterisk|hash|y-)|-thin|-open")
# Strings that are an order of their own (numbers, years, dates): never re-sorted by total.
_ORDINAL = re.compile(
    r"^\s*[-+]?[\d.,]+\s*%?\s*$|^\s*\d{4}([-/]\d{1,2}([-/]\d{1,2})?)?([ T][\d:.]+)?\s*$"
)

_DTYPES = {"f8", "f4", "i1", "i2", "i4", "i8", "u1", "u2", "u4", "u8"}


# ---------------------------------------------------------------------------
# small helpers


def _sub(container: dict, key: str) -> dict:
    """A copy of ``container[key]`` (a dict), stored back so it can be written."""
    value = container.get(key)
    copied = dict(value) if isinstance(value, dict) else {}
    container[key] = copied
    return copied


def _kind(trace: dict) -> str:
    return str(trace.get("type", "scatter"))


def _values(raw: Any) -> list | np.ndarray | None:
    """A trace array as a list or numpy array: plain lists and Plotly 6 typed buffers."""
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, dict) and "bdata" in raw:
        dtype = str(raw.get("dtype"))
        if dtype not in _DTYPES:
            return None
        try:
            return np.frombuffer(
                base64.b64decode(raw["bdata"]), dtype=np.dtype(dtype).newbyteorder("<")
            )
        except (ValueError, TypeError):
            return None
    return None


def _n_points(trace: dict) -> int:
    for key in ("x", "y"):
        values = _values(trace.get(key))
        if values is not None:
            return len(values)
    return 0


def _abs_sum(raw: Any) -> float | None:
    values = _values(raw)
    if values is None:
        return None
    total = 0.0
    for v in values:
        if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
            if v == v:  # NaN is no height
                total += abs(float(v))
    return total


def _horizontal(trace: dict) -> bool:
    return trace.get("orientation") == "h"


def _weight(trace: dict) -> float:
    """How much a trace shows: bar heights summed, else its point count."""
    if _kind(trace) == "bar":
        total = _abs_sum(trace.get("x" if _horizontal(trace) else "y"))
        if total is not None:
            return total
    return float(_n_points(trace))


def _axis_key(letter: str, trace: dict) -> str:
    ref = trace.get(f"{letter}axis")
    suffix = str(ref)[1:] if isinstance(ref, str) and ref.startswith(letter) else ""
    return f"{letter}axis{suffix}"


def _set_colour(trace: dict, colour: str) -> None:
    """Draw a trace in ``colour``; a colour array (a mapped column) is data and stays."""
    kind = _kind(trace)
    if kind in _SCATTER:
        mode = trace.get("mode") or "markers"
        if "lines" in mode:
            line = _sub(trace, "line")
            if not isinstance(line.get("color"), (list, tuple, dict)):
                line["color"] = colour
        if "markers" in mode:
            marker = _sub(trace, "marker")
            if not isinstance(marker.get("color"), (list, tuple, dict)):
                marker["color"] = colour
        return
    marker = _sub(trace, "marker")
    if isinstance(marker.get("color"), (list, tuple, dict)):
        return
    marker["color"] = colour
    if kind in ("box", "violin"):
        _sub(trace, "line")["color"] = colour


def _trace_colour(trace: dict) -> str | None:
    marker = trace.get("marker")
    colour = marker.get("color") if isinstance(marker, dict) else None
    if not isinstance(colour, str):
        line = trace.get("line")
        colour = line.get("color") if isinstance(line, dict) else None
    return colour.lower() if isinstance(colour, str) else None


def _named(trace: dict) -> str | None:
    name = trace.get("name")
    return name if isinstance(name, str) and name != "" else None


def _layout_colorway(layout: dict) -> list[str] | None:
    """The figure's own colorway (layout, else its template), or None."""
    colorway = layout.get("colorway")
    if not (isinstance(colorway, (list, tuple)) and colorway):
        template = layout.get("template")
        inner = template.get("layout") if isinstance(template, dict) else None
        colorway = inner.get("colorway") if isinstance(inner, dict) else None
    if (
        isinstance(colorway, (list, tuple))
        and colorway
        and all(isinstance(c, str) for c in colorway)
    ):
        return list(colorway)
    return None


def _first_colorway(layout: dict, mode: str) -> str:
    colorway = _layout_colorway(layout)
    return colorway[0] if colorway else palettes.categorical(None, mode)[0]


# ---------------------------------------------------------------------------
# a. one hue


def _colour_repeats_axis(trace: dict) -> bool:
    """One category on its axis, and the trace is named after it (px ``color=x``)."""
    axis = trace.get("y" if _horizontal(trace) else "x")
    values = axis if isinstance(axis, (list, tuple)) else None
    name = trace.get("name")
    if not values or not isinstance(name, str):
        return False
    distinct = {str(v) for v in values}
    return len(distinct) == 1 and name in distinct


def _single_hue(
    traces: list[dict],
    layout: dict,
    mode: str,
    category_colors: dict[str, dict[str, str]] | None = None,
) -> None:
    bar_like = [t for t in traces if _kind(t) in _BAR_LIKE]
    if len(bar_like) < 2 or not all(_colour_repeats_axis(t) for t in bar_like):
        return
    # The dashboard colours these categories everywhere (``category_colors``):
    # the colour is then an identity shared with the other tiles, not a repeat.
    names = {str(t.get("name")) for t in bar_like}
    if any(names <= set(m) for m in (category_colors or {}).values() if isinstance(m, dict)):
        return
    hue = _first_colorway(layout, mode)
    for trace in bar_like:
        _set_colour(trace, hue)
        trace["showlegend"] = False


# ---------------------------------------------------------------------------
# b. sorted bars


def _is_category_strings(values: Any) -> bool:
    items = values if isinstance(values, (list, tuple)) else None
    if not items:
        return False
    strings = [v for v in items if v is not None]
    if not strings or not all(isinstance(v, str) for v in strings):
        return False
    # Numbers, years and dates are an order of their own.
    return not all(_ORDINAL.match(v) for v in strings)


def _equal_totals(traces: list[dict], axis_key: str) -> bool:
    """Every category on ``axis_key`` sums to the same total (within 0.5 %)."""
    totals: dict[str, float] = {}
    for trace in traces:
        if (
            _kind(trace) != "bar"
            or _axis_key("y" if _horizontal(trace) else "x", trace) != axis_key
        ):
            continue
        cats = trace.get("y" if _horizontal(trace) else "x")
        vals = _values(trace.get("x" if _horizontal(trace) else "y"))
        if not isinstance(cats, (list, tuple)) or vals is None:
            return False
        for cat, val in zip(cats, list(vals)):
            try:
                totals[str(cat)] = totals.get(str(cat), 0.0) + abs(float(val))
            except (TypeError, ValueError):
                continue
    if len(totals) < 2:
        return False
    lo, hi = min(totals.values()), max(totals.values())
    return hi > 0 and (hi - lo) / hi < 0.005


def _sort_bars(traces: list[dict], layout: dict) -> None:
    wanted: dict[str, str] = {}
    for trace in traces:
        if _kind(trace) != "bar":
            continue
        horizontal = _horizontal(trace)
        letter = "y" if horizontal else "x"
        if not _is_category_strings(trace.get(letter)):
            continue
        wanted.setdefault(
            _axis_key(letter, trace), "total ascending" if horizontal else "total descending"
        )
    for key, order in wanted.items():
        if _equal_totals(traces, key):
            continue  # a 100 % stack: every bar is as long, a total sort only shuffles them
        raw = layout.get(key)
        axis = raw if isinstance(raw, dict) else {}
        if axis.get("categoryorder") or axis.get("categoryarray") is not None:
            continue
        if axis.get("type") not in (None, "category"):
            continue
        layout[key] = {**axis, "categoryorder": order}


# ---------------------------------------------------------------------------
# c. remainder last, long tails folded


def _remainder_last(traces: list[dict], mode: str) -> list[dict]:
    """Reserved-name traces last (Other, Unclassified, NA) and in their grey."""
    rank = {"other": 1, "unclassified": 2, "na": 3}

    def kind_of(trace: dict) -> str | None:
        name = trace.get("name")
        if _kind(trace) not in _COLOURED or not isinstance(name, str):
            return None
        return palettes.reserved_kind(name)

    for trace in traces:
        kind = kind_of(trace)
        if kind is not None:
            _set_colour(trace, palettes.semantic(kind, mode))
    return sorted(traces, key=lambda t: rank.get(kind_of(t) or "", 0))


def _fold_tail(traces: list[dict], layout: dict, mode: str) -> None:
    top_n = int(palettes.style()["top_n"])
    other = palettes.semantic("other", mode)
    for kind in sorted({_kind(t) for t in traces} & _COLOURED):
        group = [
            t
            for t in traces
            if _kind(t) == kind and _named(t) and palettes.reserved_kind(t["name"]) is None
        ]
        by_name: dict[str, list[dict]] = {}
        for trace in group:
            by_name.setdefault(trace["name"], []).append(trace)
        listed = [
            n for n, ts in by_name.items() if any(t.get("showlegend") is not False for t in ts)
        ]
        if len(listed) <= top_n:
            continue
        order = {n: i for i, n in enumerate(listed)}
        totals = {n: sum(_weight(t) for t in by_name[n]) for n in listed}
        keep = sorted(listed, key=lambda n: (-totals[n], order[n]))[:top_n]
        kept = [n for n in listed if n in keep]
        folded = [n for n in listed if n not in keep]

        # A palette cycled past its slots gives two kept series one colour;
        # the kept ones then take the figure's own colorway's slots, in order
        # (the default palette only when the layout carries none).
        colours = [_trace_colour(by_name[n][0]) for n in kept]
        if len({c for c in colours if c}) < len([c for c in colours if c]):
            slots = _layout_colorway(layout) or palettes.categorical(None, mode)
            for i, name in enumerate(kept):
                for trace in by_name[name]:
                    _set_colour(trace, slots[i % len(slots)])

        first = True
        for trace in group:
            if trace["name"] not in folded:
                continue
            _set_colour(trace, other)
            trace["legendgroup"] = OTHER_LEGENDGROUP
            if first:
                trace["name"] = f"Other ({len(folded)})"
                trace["showlegend"] = True
                first = False
            else:
                trace["showlegend"] = False


# ---------------------------------------------------------------------------
# d. light chrome


def _axis_orientation(traces: list[dict]) -> str | None:
    """``v`` / ``h`` when the value axis is y / x (bars, boxes, violins), else None."""
    kinds = {_kind(t) for t in traces}
    if kinds & (_SCATTER | {"histogram"}):
        return None
    for trace in traces:
        if _kind(trace) in _BAR_LIKE:
            return "h" if _horizontal(trace) else "v"
    return None


def _light_chrome(
    traces: list[dict], layout: dict, chrome: dict[str, str], *, set_font: bool = True
) -> None:
    if traces and all(_kind(t) in _CARTESIAN for t in traces):
        orientation = _axis_orientation(traces)
        keys = [k for k in layout if _AXIS_KEY.match(k) and isinstance(layout[k], dict)]
        for letter in ("x", "y"):
            if not any(k.startswith(f"{letter}axis") for k in keys):
                keys.append(f"{letter}axis")
        for key in keys:
            letter = key[0]
            axis = dict(layout.get(key) or {})
            category_side = (orientation == "v" and letter == "x") or (
                orientation == "h" and letter == "y"
            )
            if category_side:
                axis.setdefault("showgrid", False)
            else:
                axis.setdefault("gridcolor", chrome["grid"])
            axis.setdefault("ticks", "")
            axis.setdefault("zerolinecolor", chrome["zero"])
            layout[key] = axis

    template = layout.get("template")
    template_layout = template.get("layout") if isinstance(template, dict) else None
    template_font = (template_layout or {}).get("font") or {}
    # A brand font lives in the template; only the stock one is ours to replace.
    if set_font and template_font.get("family") in (None, STOCK_FONT_FAMILY):
        _sub(layout, "font").setdefault("family", palettes.font_family())

    hover = _sub(layout, "hoverlabel")
    hover.setdefault("bgcolor", chrome["hover_bg"])
    hover.setdefault("bordercolor", chrome["hover_border"])
    hover_font = dict(hover["font"]) if isinstance(hover.get("font"), dict) else {}
    hover_font.setdefault("color", chrome["hover_text"])
    hover["font"] = hover_font


# ---------------------------------------------------------------------------
# f. markers by point count


def _marker_traces(traces: Iterable[dict]) -> list[dict]:
    out = []
    for trace in traces:
        if _kind(trace) not in _SCATTER:
            continue
        mode = trace.get("mode") or "markers"
        if "markers" not in mode or "lines" in mode:
            continue
        symbol = (trace.get("marker") or {}).get("symbol")
        if isinstance(symbol, str) and _LINE_SYMBOL.search(symbol):
            continue
        out.append(trace)
    return out


def _size_markers(traces: list[dict], chrome: dict[str, str]) -> None:
    marker_traces = _marker_traces(traces)
    if not marker_traces:
        return
    bucket = palettes.scatter_marker(sum(_n_points(t) for t in marker_traces))
    for trace in marker_traces:
        marker = _sub(trace, "marker")
        if marker.get("size") is None:
            marker["size"] = bucket["size"]
        if marker.get("opacity") is None and trace.get("opacity") is None:
            marker["opacity"] = bucket["opacity"]
        if bucket["outline"] and not marker.get("line"):
            marker["line"] = {"width": 0.5, "color": chrome["surface"]}


# ---------------------------------------------------------------------------
# entry point


def apply_overview(
    figure: dict,
    *,
    theme: str = "light",
    set_font: bool = True,
    category_colors: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Return ``figure`` drawn in the overview look; the input is left untouched.

    ``set_font=False`` leaves the font to a caller that sets its own (``minimal``).
    """
    if not isinstance(figure, dict):
        return figure
    mode = "dark" if theme == "dark" else "light"
    chrome = palettes.chrome(mode)

    # The template is large and read-only here: shared, never written.
    layout = {
        k: (v if k == "template" else copy.deepcopy(v))
        for k, v in (figure.get("layout") or {}).items()
    }
    # Traces are copied one level deep; nested dicts are copied where written
    # and the data arrays, most of the payload, are shared.
    traces = [dict(t) for t in (figure.get("data") or []) if isinstance(t, dict)]

    _single_hue(traces, layout, mode, category_colors)
    _sort_bars(traces, layout)
    traces = _remainder_last(traces, mode)
    _fold_tail(traces, layout, mode)
    _light_chrome(traces, layout, chrome, set_font=set_font)
    if any(_kind(t) == "bar" for t in traces):
        layout.setdefault("barcornerradius", palettes.style()["bar_corner_radius"])
    _size_markers(traces, chrome)

    out = dict(figure)
    out["layout"] = layout
    out["data"] = traces
    return out
