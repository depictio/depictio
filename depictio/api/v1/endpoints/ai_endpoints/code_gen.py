"""Render LLM-driven figure suggestions back to readable Python code.

The user wants every AI-driven action to be explainable as Python — the
analyze flow already surfaces Polars code via `ExecutionStep.code`, but
the figure flows produce a structured `PlotSuggestion` (visu_type +
dict_kwargs) that has no source code by construction. We synthesize the
equivalent Plotly Express call here so the React drawer can show it
alongside the rendered chart.

Output is *display-only* — never eval'd. Keep it readable (one kwarg per
line when there are several) and faithful to the actual rendering path
(`px.<visu_type>(df, **dict_kwargs)`).
"""

from __future__ import annotations

from typing import Any


def _format_value(value: Any) -> str:
    """repr() with one carve-out: short lists render inline."""
    if (
        isinstance(value, list)
        and len(value) <= 6
        and all(isinstance(x, (str, int, float, bool)) for x in value)
    ):
        return repr(value)
    return repr(value)


def figure_python_code(visu_type: str, dict_kwargs: dict[str, Any]) -> str:
    """Render a `PlotSuggestion` back to a Plotly Express call.

    The DataFrame is referenced as `df` — matches what the analyze
    executor exposes and what an end-user would type in a notebook after
    `df = pl.read_parquet(...)`.
    """
    items = list(dict_kwargs.items())
    if not items:
        body = "df"
    elif len(items) <= 2:
        kwargs_str = ", ".join(f"{k}={_format_value(v)}" for k, v in items)
        body = f"df, {kwargs_str}"
    else:
        lines = ["    df,"]
        for k, v in items:
            lines.append(f"    {k}={_format_value(v)},")
        body = "\n".join(lines)
        return f"import plotly.express as px\n\nfig = px.{visu_type}(\n{body}\n)"

    return f"import plotly.express as px\n\nfig = px.{visu_type}({body})"
