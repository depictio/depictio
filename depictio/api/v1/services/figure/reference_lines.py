"""Guide lines on a UI-mode figure: a fixed value, or a statistic of the data.

``FigureLiteComponent.reference_lines`` (and the catalog ``Render`` field of the
same name) is a list of ``{axis, value | stat + column, label}``. A ``stat``
line is placed at the median (mean, p75..p99) of its column over the filtered
rows and named as such ("median of this table"), which is what RULES.md §17
asks of a reference defined by the data rather than by the tool.

The statistic is computed by the caller on the filtered frame *before* any
point sampling (the worker opens a dedicated scan; the catalog preview has the
whole fixture), then :func:`apply_reference_lines` draws every line onto the
built figure. Both halves are shared by the API worker and the catalog preview.
"""

from __future__ import annotations

from typing import Any

from depictio.api.v1.services.advanced_viz.reference_stats import (
    compute_requests,
    reference_label,
)


def _as_dict(line: Any) -> dict[str, Any] | None:
    if hasattr(line, "model_dump"):
        line = line.model_dump()
    return line if isinstance(line, dict) else None


def normalise_reference_lines(raw: Any) -> list[dict[str, Any]]:
    """The usable lines of a component's ``reference_lines``, as plain dicts."""
    out: list[dict[str, Any]] = []
    for line in raw or []:
        spec = _as_dict(line)
        if not spec or spec.get("axis") not in ("x", "y"):
            continue
        if spec.get("value") is None and not (spec.get("stat") and spec.get("column")):
            continue
        out.append(spec)
    return out


def stat_requests(lines: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """``{line index: (column, stat)}`` for the lines placed by a statistic."""
    return {
        str(i): (str(line["column"]), str(line["stat"]))
        for i, line in enumerate(lines)
        if line.get("value") is None and line.get("stat") and line.get("column")
    }


def resolve_reference_lines(lines: list[dict[str, Any]], frame: Any) -> list[dict[str, Any]]:
    """Each line with its ``value`` settled and its ``label`` written.

    ``frame`` is the filtered, unsampled data (a polars DataFrame or
    LazyFrame); it is only read when a line names a ``stat``. A line whose
    statistic has no finite value (an empty filter, a column the frame lacks)
    is dropped: no line beats a wrong one.
    """
    requests = stat_requests(lines)
    values = compute_requests(frame, requests) if requests and frame is not None else {}
    out: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        value = line.get("value")
        label = line.get("label")
        if value is None:
            value = values.get(str(i))
            if value is None:
                continue
            label = label or reference_label(str(line["stat"]))
        else:
            label = label or f"{line['axis']} = {float(value):g}"
        out.append({"axis": line["axis"], "value": float(value), "label": label})
    return out


def apply_reference_lines(fig: Any, resolved: list[dict[str, Any]], theme: str = "light") -> Any:
    """Draw resolved lines on a plotly figure (a ``go.Figure`` or its dict).

    Dashed, in the theme's neutral zero-line colour (the same one the
    advanced-viz guides use), with the label at the end of the line.
    """
    if not resolved:
        return fig
    from depictio.api.v1.services.advanced_viz.theme import plotly_theme_colors

    colour = plotly_theme_colors(theme == "dark").zero_line_color
    shapes: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for line in resolved:
        value = line["value"]
        if line["axis"] == "y":
            shapes.append(
                {
                    "type": "line",
                    "xref": "paper",
                    "x0": 0,
                    "x1": 1,
                    "yref": "y",
                    "y0": value,
                    "y1": value,
                    "line": {"color": colour, "width": 1, "dash": "dash"},
                }
            )
            annotations.append(
                {
                    "xref": "paper",
                    "x": 1,
                    "yref": "y",
                    "y": value,
                    "text": line["label"],
                    "showarrow": False,
                    "xanchor": "right",
                    "yanchor": "bottom",
                    "font": {"size": 10, "color": colour},
                }
            )
        else:
            shapes.append(
                {
                    "type": "line",
                    "yref": "paper",
                    "y0": 0,
                    "y1": 1,
                    "xref": "x",
                    "x0": value,
                    "x1": value,
                    "line": {"color": colour, "width": 1, "dash": "dash"},
                }
            )
            annotations.append(
                {
                    "yref": "paper",
                    "y": 1,
                    "xref": "x",
                    "x": value,
                    "text": line["label"],
                    "showarrow": False,
                    "xanchor": "left",
                    "yanchor": "top",
                    "font": {"size": 10, "color": colour},
                }
            )
    if isinstance(fig, dict):
        layout = fig.setdefault("layout", {})
        layout["shapes"] = [*(layout.get("shapes") or []), *shapes]
        layout["annotations"] = [*(layout.get("annotations") or []), *annotations]
        return fig
    # A built figure takes plotly's own helpers, which repeat the line on every
    # facet panel (the dict path above spans the first axis pair only).
    style = {"line_color": colour, "line_width": 1, "line_dash": "dash"}
    font = {"size": 10, "color": colour}
    for line in resolved:
        if line["axis"] == "y":
            fig.add_hline(
                y=line["value"],
                annotation_text=line["label"],
                annotation_position="top right",
                annotation_font=font,
                **style,
            )
        else:
            fig.add_vline(
                x=line["value"],
                annotation_text=line["label"],
                annotation_position="top left",
                annotation_font=font,
                **style,
            )
    return fig
