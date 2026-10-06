"""Figure style presets: a look applied to a finished figure.

A preset is a layout and trace overlay applied to the serialised figure, after
the theme and brand templates have done their work, so it reaches every figure
the same way: UI mode, code mode and the scan-level aggregation path all end in
the same figure dict.

``minimal`` is the "showcase" look of a landing page: a transparent plot, faint
dashed grid lines and no axis lines, small grey ticks, the legend in one line
under the plot, tight margins, large markers without outlines, bars without
edges. The card header carries the title, so the plot drops its own. Grouped
bars (one facet per group, each with its own categories) get a coloured
underline per group with the group's name under it, in place of the facet
titles over the panels.

The overlay is a pure function of the figure dict: it copies what it changes
and never mutates its input, so the caller can apply it to a cached figure.

Kept in sync with ``FIGURE_STYLES`` in
packages/depictio-react-core/src/components/figureStyle.ts.
"""

from __future__ import annotations

import copy
import re
from typing import Any

FIGURE_STYLES: tuple[str, ...] = ("default", "minimal")
DEFAULT_FIGURE_STYLE = "default"

# Mantine gray-6 / dark-2 for ticks and axis titles, gray-7 / dark-0 for labels
# a reader reads (legend, group names). The grid is a near-transparent ink so it
# sits on whatever the card's background is.
_PALETTE: dict[str, dict[str, str]] = {
    "light": {
        "grid": "rgba(15, 23, 42, 0.09)",
        "tick": "#868e96",
        "label": "#495057",
        "hover_bg": "#ffffff",
        "hover_border": "#dee2e6",
        "hover_font": "#212529",
        "fallback_group": "#adb5bd",
    },
    "dark": {
        "grid": "rgba(255, 255, 255, 0.09)",
        "tick": "#909296",
        "label": "#c1c2c5",
        "hover_bg": "#25262b",
        "hover_border": "#373a40",
        "hover_font": "#c1c2c5",
        "fallback_group": "#5c5f66",
    },
}

_AXIS_KEY = re.compile(r"^([xy])axis(\d*)$")

# Marker size by how many points share the plot: large markers are the look,
# but a few thousand of them at 12px is a blot, not a scatter.
_MARKER_SIZE_STEPS: tuple[tuple[int, int], ...] = ((300, 12), (1500, 8), (6000, 6))
_MARKER_SIZE_FLOOR = 4

# Trace types whose markers the preset resizes.
_SCATTER_TYPES = frozenset({"scatter", "scattergl", "scatterpolar", "scatterpolargl"})
# Marker symbols drawn by their outline (a median tick, a cross, an open
# circle): the preset's outline-free look would erase them.
_LINE_SYMBOL = re.compile(r"^(line-|asterisk|hash|y-)|-thin|-open")
# Trace types that put categories on one axis and values on the other.
_CATEGORICAL_TYPES = frozenset({"bar", "box", "violin", "histogram", "funnel"})

# Top margin for a kept plot title, and for facet titles over the top panels.
_TITLE_MARGIN_PX = 32
_FACET_TITLE_MARGIN_PX = 26
# Short, fine dashes: a grid that is there when looked for.
_GRID_DASH = "3px,4px"

# Room the group underline and its label take under a grouped bar chart.
_UNDERLINE_GAP_PX = 6
_UNDERLINE_HEIGHT_PX = 4
_UNDERLINE_LABEL_GAP_PX = 14
_UNDERLINE_MARGIN_PX = 40
# Each underline stops short of its panel's edges so neighbours read as two.
_UNDERLINE_INSET = 0.012


def normalize_figure_style(value: Any) -> str | None:
    """A known style name, or None for anything else (unset, unknown, wrong type)."""
    return value if isinstance(value, str) and value in FIGURE_STYLES else None


def resolve_figure_style(*candidates: Any) -> str:
    """The first known style among ``candidates``, else the default.

    Called with the most specific choice first: a request's override, the
    figure's own ``figure_style``, its grid section's ``figure_style``.
    """
    for candidate in candidates:
        style = normalize_figure_style(candidate)
        if style:
            return style
    return DEFAULT_FIGURE_STYLE


def section_figure_style(dashboard: dict | None, section: Any) -> str | None:
    """The ``figure_style`` of the grid section named ``section``, if any."""
    if not dashboard or not isinstance(section, str) or not section.strip():
        return None
    for spec in dashboard.get("grid_sections") or []:
        if isinstance(spec, dict) and spec.get("name") == section:
            return normalize_figure_style(spec.get("figure_style"))
    return None


def apply_figure_style(
    figure: dict,
    style: str | None,
    *,
    theme: str = "light",
    header_title: bool = False,
    hide_legend: bool = False,
    category_colors: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Return ``figure`` drawn in ``style``; the input is left untouched.

    Args:
        figure: A serialised Plotly figure (``{"data": [...], "layout": {...}}``).
        style: A name from ``FIGURE_STYLES``. ``default`` and unknown names
            return the figure as it is (bar ``hide_legend``).
        theme: ``light`` or ``dark``, for the grid, tick and hover colours.
        header_title: The card header shows the figure's title, so the plot
            drops its own rather than printing it twice.
        hide_legend: Drop the legend, in any style (a tile with no room for it).
        category_colors: ``{column: {value: colour}}``, the dashboard's colour
            per category. Colours the group underlines of grouped bars.
    """
    if not isinstance(figure, dict):
        return figure
    if normalize_figure_style(style) != "minimal":
        if not hide_legend:
            return figure
        out = dict(figure)
        out["layout"] = {**(figure.get("layout") or {}), "showlegend": False}
        return out
    return _apply_minimal(
        figure,
        palette=_PALETTE["dark" if theme == "dark" else "light"],
        header_title=header_title,
        hide_legend=hide_legend,
        category_colors=category_colors or {},
    )


# ---------------------------------------------------------------------------
# minimal


def _apply_minimal(
    figure: dict,
    *,
    palette: dict[str, str],
    header_title: bool,
    hide_legend: bool,
    category_colors: dict[str, dict[str, str]],
) -> dict:
    layout = copy.deepcopy(figure.get("layout") or {})
    # Traces are copied one level deep: the nested dicts the overlay writes to
    # (marker, line) are copied where they are changed, and the data arrays,
    # which can be most of the payload, are shared rather than duplicated.
    traces = [dict(t) for t in (figure.get("data") or []) if isinstance(t, dict)]

    _style_traces(traces, layout)
    has_title = _style_title(layout, header_title, palette)
    _style_axes(layout, traces, palette)
    _style_legend(layout, palette, hide_legend)
    _style_colorbars(layout, traces, palette)
    _style_annotations(layout, palette)

    layout["paper_bgcolor"] = "rgba(0,0,0,0)"
    layout["plot_bgcolor"] = "rgba(0,0,0,0)"
    layout["hoverlabel"] = {
        **(layout.get("hoverlabel") or {}),
        "bgcolor": palette["hover_bg"],
        "bordercolor": palette["hover_border"],
        "font": {"size": 12, "color": palette["hover_font"]},
    }
    # The toolbar shows on hover only (the viewer's Plotly config); with no
    # band of its own it floats over the card like the chrome's icons do.
    layout["modebar"] = {
        **(layout.get("modebar") or {}),
        "bgcolor": "rgba(0,0,0,0)",
        "color": palette["tick"],
        "activecolor": palette["label"],
    }
    # Tight on every side: automargin on the axes and the legend's own push
    # grow them to whatever the ticks, axis titles and legend need.
    # Annotations push no margin of their own, so the room a title or a facet
    # title over the top panels needs is reserved here.
    margin = {"l": 8, "r": 8, "t": 8, "b": 8, "pad": 0}
    if _underline_groups(layout, traces, palette, category_colors):
        margin["b"] = _UNDERLINE_MARGIN_PX
    if has_title:
        margin["t"] = _TITLE_MARGIN_PX
    elif _labels_above_plot(layout):
        margin["t"] = _FACET_TITLE_MARGIN_PX
    layout["margin"] = margin

    out = dict(figure)
    out["layout"] = layout
    out["data"] = traces
    return out


def _sub(container: dict, key: str) -> dict:
    """A copy of ``container[key]`` (a dict), stored back so it can be written."""
    value = container.get(key)
    copied = dict(value) if isinstance(value, dict) else {}
    container[key] = copied
    return copied


# Bytes per element of the typed-array dtypes Plotly 6 serialises numpy data to.
_DTYPE_BYTES = {"f8": 8, "f4": 4, "i4": 4, "u4": 4, "i2": 2, "u2": 2, "i1": 1, "u1": 1}


def _point_count(trace: dict) -> int:
    for key in ("x", "y", "r", "lat"):
        values = trace.get(key)
        if isinstance(values, (list, tuple)):
            return len(values)
        if isinstance(values, dict) and "bdata" in values:
            # A typed buffer, {"dtype", "bdata"[, "shape"]}: base64 of the raw
            # array, so its length gives the element count without decoding.
            shape = values.get("shape")
            if isinstance(shape, (list, tuple)) and shape:
                return int(str(shape[0]).split(",")[0])
            itemsize = _DTYPE_BYTES.get(str(values.get("dtype")), 8)
            return len(str(values["bdata"])) * 3 // 4 // itemsize
    return 0


def _marker_size(points: int) -> int:
    for ceiling, size in _MARKER_SIZE_STEPS:
        if points <= ceiling:
            return size
    return _MARKER_SIZE_FLOOR


def _drawn_by_line(trace: dict) -> bool:
    symbol = (trace.get("marker") or {}).get("symbol")
    return isinstance(symbol, str) and bool(_LINE_SYMBOL.search(symbol))


def _is_strip(trace: dict) -> bool:
    """A strip plot (px.strip): a box trace showing every point, its box hidden."""
    return trace.get("boxpoints") == "all" and trace.get("hoveron") == "points"


def _style_traces(traces: list[dict], layout: dict) -> None:
    scatter_points = sum(
        _point_count(t)
        for t in traces
        if t.get("type", "scatter") in _SCATTER_TYPES or _is_strip(t)
    )
    marker_size = _marker_size(scatter_points)
    has_bars = False

    for trace in traces:
        kind = trace.get("type", "scatter")
        if kind in _SCATTER_TYPES:
            mode = trace.get("mode") or "markers"
            if "markers" in mode and _drawn_by_line(trace):
                # Its size and outline are the mark itself: left as drawn.
                pass
            elif "markers" in mode:
                marker = _sub(trace, "marker")
                # A size or opacity array maps a column: that is data, not style.
                if not isinstance(marker.get("size"), (list, tuple, dict)):
                    marker["size"] = marker_size if "lines" not in mode else 6
                if not isinstance(marker.get("opacity"), (list, tuple, dict)):
                    marker["opacity"] = 0.9
                line = _sub(marker, "line")
                line["width"] = 0
            if "lines" in mode:
                line = _sub(trace, "line")
                line.setdefault("width", 2.25)
                if isinstance(line.get("width"), (int, float)) and line["width"] < 2:
                    line["width"] = 2
        elif kind in ("bar", "histogram", "funnel"):
            has_bars = has_bars or kind == "bar"
            marker = _sub(trace, "marker")
            _sub(marker, "line")["width"] = 0
        elif kind in ("box", "violin"):
            strip = _is_strip(trace)
            if not strip:
                _sub(trace, "line")["width"] = 1.5
            marker = _sub(trace, "marker")
            if not isinstance(marker.get("size"), (list, tuple, dict)):
                # A strip's points are the plot, sized as a scatter's; a box's
                # are its outliers, kept small beside it.
                marker["size"] = marker_size if strip else 5
            marker["opacity"] = 0.85 if strip else 0.75
            _sub(marker, "line")["width"] = 0

    if has_bars:
        layout["bargap"] = 0.22
        layout["bargroupgap"] = 0.06


def _style_title(layout: dict, header_title: bool, palette: dict[str, str]) -> bool:
    """Drop or restyle the plot title; True when the plot keeps one."""
    title = layout.get("title")
    text = title.get("text") if isinstance(title, dict) else title
    if header_title or not (isinstance(text, str) and text.strip()):
        layout["title"] = {"text": ""}
        return False
    layout["title"] = {
        "text": text,
        "x": 0,
        "xanchor": "left",
        "xref": "paper",
        "font": {"size": 13, "color": palette["label"]},
    }
    return True


def _axis_traces(traces: list[dict], letter: str, suffix: str) -> list[dict]:
    """Traces drawn against axis ``<letter>axis<suffix>``."""
    ref = letter + suffix
    return [t for t in traces if (t.get(f"{letter}axis") or letter) == ref]


def _is_category_side(trace: dict, letter: str) -> bool:
    """Whether ``letter`` is the axis a categorical trace lays its groups along."""
    kind = trace.get("type", "scatter")
    if kind not in _CATEGORICAL_TYPES:
        return False
    orientation = trace.get("orientation")
    if kind == "histogram":
        # The binned axis is the one with data; counts run along the other.
        horizontal = orientation == "h" or (trace.get("y") is not None and trace.get("x") is None)
    else:
        horizontal = orientation == "h"
    return letter == ("y" if horizontal else "x")


def _style_axes(layout: dict, traces: list[dict], palette: dict[str, str]) -> None:
    tick_font = {"size": 11, "color": palette["tick"]}
    for key in list(layout):
        match = _AXIS_KEY.match(key)
        if not match or not isinstance(layout[key], dict):
            continue
        letter, suffix = match.groups()
        axis = dict(layout[key])
        on_axis = _axis_traces(traces, letter, suffix)
        no_grid = any(t.get("type") == "heatmap" for t in on_axis) or any(
            _is_category_side(t, letter) for t in on_axis
        )
        axis.update(
            showline=False,
            zeroline=False,
            ticks="",
            showgrid=not no_grid,
            gridcolor=palette["grid"],
            gridwidth=1,
            griddash=_GRID_DASH,
            tickfont={**(axis.get("tickfont") or {}), **tick_font},
            automargin=True,
        )
        title = axis.get("title")
        if isinstance(title, dict) and title.get("text"):
            axis["title"] = {**title, "font": {"size": 11, "color": palette["tick"]}, "standoff": 8}
        layout[key] = axis
    # A figure with no explicit axis blocks still gets the look on its first pair.
    for letter in ("x", "y"):
        if f"{letter}axis" not in layout and _axis_traces(traces, letter, ""):
            layout[f"{letter}axis"] = {
                "showline": False,
                "zeroline": False,
                "ticks": "",
                "gridcolor": palette["grid"],
                "griddash": _GRID_DASH,
                "tickfont": tick_font,
                "automargin": True,
                "showgrid": not any(
                    _is_category_side(t, letter) for t in _axis_traces(traces, letter, "")
                ),
            }


def _style_legend(layout: dict, palette: dict[str, str], hide_legend: bool) -> None:
    if hide_legend:
        layout["showlegend"] = False
        return
    legend = dict(layout.get("legend") or {})
    legend.update(
        orientation="h",
        x=0.5,
        xanchor="center",
        # Against the bottom of the whole figure, not of the plot area: a
        # paper-relative offset lands on the x-axis title at some tile heights.
        # The legend pushes the bottom margin for the room it takes.
        y=0,
        yref="container",
        yanchor="bottom",
        title={"text": ""},
        font={"size": 11, "color": palette["label"]},
        itemsizing="constant",
        itemwidth=30,
        bgcolor="rgba(0,0,0,0)",
        borderwidth=0,
        tracegroupgap=0,
    )
    layout["legend"] = legend


def _style_colorbars(layout: dict, traces: list[dict], palette: dict[str, str]) -> None:
    tidy = {
        "thickness": 10,
        "outlinewidth": 0,
        "len": 0.85,
        "tickfont": {"size": 10, "color": palette["tick"]},
    }
    for key in list(layout):
        if key.startswith("coloraxis") and isinstance(layout[key], dict):
            axis = dict(layout[key])
            axis["colorbar"] = {**(axis.get("colorbar") or {}), **tidy}
            layout[key] = axis
    for trace in traces:
        if isinstance(trace.get("colorbar"), dict):
            trace["colorbar"] = {**trace["colorbar"], **tidy}
        marker = trace.get("marker")
        if isinstance(marker, dict) and isinstance(marker.get("colorbar"), dict):
            marker = _sub(trace, "marker")
            marker["colorbar"] = {**marker["colorbar"], **tidy}


def _style_annotations(layout: dict, palette: dict[str, str]) -> None:
    """Facet titles and other plain labels in the small label colour."""
    annotations = layout.get("annotations")
    if not isinstance(annotations, list):
        return
    styled = []
    for annotation in annotations:
        if isinstance(annotation, dict) and annotation.get("showarrow") is False:
            annotation = {
                **annotation,
                "font": {**(annotation.get("font") or {}), "size": 12, "color": palette["label"]},
            }
        styled.append(annotation)
    layout["annotations"] = styled


def _labels_above_plot(layout: dict) -> bool:
    """Whether a paper-anchored label sits at the top edge of the plot area."""
    for annotation in layout.get("annotations") or []:
        if not isinstance(annotation, dict) or annotation.get("showarrow") is not False:
            continue
        y = annotation.get("y")
        if (
            annotation.get("yref", "paper") == "paper"
            and isinstance(y, (int, float))
            and y >= 0.98
            and annotation.get("yanchor", "auto") in ("bottom", "auto")
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# grouped bars


def _values(trace: dict, letter: str) -> list[Any] | None:
    values = trace.get(letter)
    return list(values) if isinstance(values, (list, tuple)) else None


def _column_domains(layout: dict) -> dict[str, tuple[float, float]]:
    """``{"x": (0, .32), "x2": (.34, .66), …}``: each x axis and its panel."""
    domains: dict[str, tuple[float, float]] = {}
    for key, axis in layout.items():
        match = _AXIS_KEY.match(key)
        if not match or match.group(1) != "x" or not isinstance(axis, dict):
            continue
        domain = axis.get("domain")
        if isinstance(domain, (list, tuple)) and len(domain) == 2:
            domains["x" + match.group(2)] = (float(domain[0]), float(domain[1]))
    return domains


def _group_color(
    label: str,
    traces: list[dict],
    category_colors: dict[str, dict[str, str]],
    fallback: str,
) -> str:
    """The colour a group is known by: the dashboard's, a trace's, or neutral."""
    for mapping in category_colors.values():
        if isinstance(mapping, dict) and isinstance(mapping.get(label), str):
            return mapping[label]
    for trace in traces:
        color = (trace.get("marker") or {}).get("color")
        if trace.get("name") == label and isinstance(color, str):
            return color
    return fallback


def _underline_groups(
    layout: dict,
    traces: list[dict],
    palette: dict[str, str],
    category_colors: dict[str, dict[str, str]],
) -> bool:
    """Draw grouped bars as groups; True when the figure was one.

    Grouped bars are vertical bars faceted in columns where every panel holds
    its own categories (samples of one habitat, then the next), so the facets
    partition the x axis rather than repeat it. Each panel then keeps only its
    own categories, loses its per-bar tick labels (the hover still names each
    bar), and gets a bar of its group's colour under it with the group's name
    beneath. Facets that repeat the same categories are a comparison, not
    groups, and are left as they are.
    """
    bars = [t for t in traces if t.get("type") == "bar" and t.get("orientation", "v") != "h"]
    if not bars:
        return False
    domains = _column_domains(layout)
    if len(domains) < 2:
        return False

    categories: dict[str, set] = {}
    for trace in bars:
        values = _values(trace, "x")
        if values is None or any(isinstance(v, (int, float)) for v in values):
            return False
        categories.setdefault(trace.get("xaxis") or "x", set()).update(map(str, values))
    panels = [ref for ref in domains if categories.get(ref)]
    if len(panels) < 2:
        return False
    seen: set = set()
    for ref in panels:
        if seen & categories[ref]:
            return False
        seen |= categories[ref]

    annotations = [a for a in (layout.get("annotations") or []) if isinstance(a, dict)]
    shapes = list(layout.get("shapes") or [])
    labels_by_panel: dict[str, str] = {}
    kept_annotations = []
    for annotation in annotations:
        panel = _facet_title_panel(annotation, domains, panels)
        if panel and panel not in labels_by_panel:
            labels_by_panel[panel] = str(annotation.get("text") or "")
        else:
            kept_annotations.append(annotation)
    if not labels_by_panel:
        return False

    for ref in panels:
        axis_key = "xaxis" + ref[1:]
        axis = dict(layout.get(axis_key) or {})
        axis.update(matches=None, showticklabels=False, title={"text": ""})
        layout[axis_key] = axis
        label = labels_by_panel.get(ref)
        if not label:
            continue
        low, high = domains[ref]
        color = _group_color(label, traces, category_colors, palette["fallback_group"])
        shapes.append(
            {
                "type": "rect",
                "xref": "paper",
                "yref": "paper",
                "x0": low + _UNDERLINE_INSET,
                "x1": high - _UNDERLINE_INSET,
                "ysizemode": "pixel",
                "yanchor": 0,
                "y0": -_UNDERLINE_GAP_PX,
                "y1": -(_UNDERLINE_GAP_PX + _UNDERLINE_HEIGHT_PX),
                "fillcolor": color,
                "line": {"width": 0},
                "layer": "above",
            }
        )
        kept_annotations.append(
            {
                "text": label,
                "xref": "paper",
                "yref": "paper",
                "x": (low + high) / 2,
                "y": 0,
                "yshift": -(_UNDERLINE_GAP_PX + _UNDERLINE_HEIGHT_PX + _UNDERLINE_LABEL_GAP_PX),
                "xanchor": "center",
                "yanchor": "middle",
                "showarrow": False,
                "font": {"size": 12, "color": palette["label"]},
            }
        )
    layout["annotations"] = kept_annotations
    layout["shapes"] = shapes
    if layout.get("showlegend") is not False:
        # The group names take the room under the plot, so the legend moves to
        # its right, in the order the segments are stacked.
        legend = dict(layout.get("legend") or {})
        legend.update(
            orientation="v",
            x=1.01,
            xanchor="left",
            y=0.5,
            yref="paper",
            yanchor="middle",
            itemwidth=30,
        )
        if layout.get("barmode") in ("stack", "relative", None):
            legend["traceorder"] = "reversed"
        layout["legend"] = legend
    return True


def _facet_title_panel(
    annotation: dict, domains: dict[str, tuple[float, float]], panels: list[str]
) -> str | None:
    """The panel a facet title sits over, or None for any other annotation."""
    if annotation.get("showarrow") is True:
        return None
    if annotation.get("xref", "paper") != "paper" or annotation.get("yref", "paper") != "paper":
        return None
    x = annotation.get("x")
    y = annotation.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or y < 0.5:
        return None
    for ref in panels:
        low, high = domains[ref]
        if abs(x - (low + high) / 2) < 0.02:
            return ref
    return None


def figure_style_payload(
    component: dict,
    dashboard: dict | None = None,
    overrides: Any = None,
) -> dict[str, Any]:
    """The ``style`` block of a render payload for ``component``.

    The style is the most specific one set: the request's override (a
    highlight drawing another tab's figure in its own style), the figure's own
    ``figure_style``, the ``figure_style`` of the grid section it sits in on
    ``dashboard``, else the default. ``header_title`` and ``hide_legend``
    follow the same order, the component's own values standing in for an
    override the request does not make.

    Overrides are read field by field and only when well-typed, so a client
    cannot hand the task anything but a known style name and two booleans.
    """
    overrides = overrides if isinstance(overrides, dict) else {}
    header_title = overrides.get("header_title")
    if not isinstance(header_title, bool):
        header_title = bool(str(component.get("title") or "").strip())
    hide_legend = overrides.get("hide_legend")
    if not isinstance(hide_legend, bool):
        hide_legend = bool(component.get("hide_legend"))
    return {
        "figure_style": resolve_figure_style(
            overrides.get("figure_style"),
            component.get("figure_style"),
            section_figure_style(dashboard, component.get("section")),
        ),
        "header_title": header_title,
        "hide_legend": hide_legend,
    }
