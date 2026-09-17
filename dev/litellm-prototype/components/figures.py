"""Plotly Express figure builder from dict_kwargs."""

from __future__ import annotations

from typing import Any

import dash_mantine_components as dmc
import pandas as pd
import plotly.express as px
from dash import dcc

ALLOWED_TYPES = {"scatter", "bar", "line", "histogram", "box", "violin", "heatmap"}


def create_figure(
    df: pd.DataFrame,
    visu_type: str,
    dict_kwargs: dict[str, Any],
    title: str | None = None,
    graph_id: str | None = None,
) -> dmc.Paper:
    """Build a Plotly Express figure from a visu_type and dict_kwargs.

    Args:
        df: Source DataFrame.
        visu_type: Plotly Express function name (scatter, bar, etc.).
        dict_kwargs: Keyword arguments for the px function.
        title: Optional figure title override.
        graph_id: Optional Dash component ID for the dcc.Graph.
    """
    if visu_type not in ALLOWED_TYPES:
        visu_type = "scatter"

    plot_fn = getattr(px, visu_type)

    # Filter dict_kwargs to only include columns that exist
    safe_kwargs = {}
    for k, v in dict_kwargs.items():
        if isinstance(v, str) and k in ("x", "y", "color", "size", "facet_col", "facet_row", "symbol", "text"):
            if v in df.columns:
                safe_kwargs[k] = v
        else:
            safe_kwargs[k] = v

    # Guard: px functions need at least x (or y for histogram) to avoid
    # wide-form fallback on mixed-type DataFrames.
    needs_x = visu_type not in ("histogram",)
    if needs_x and "x" not in safe_kwargs:
        raise ValueError(
            f"Cannot create '{visu_type}' plot: missing required 'x' column mapping in dict_kwargs. "
            f"Available columns: {list(df.columns)}"
        )
    if visu_type == "histogram" and "x" not in safe_kwargs and "y" not in safe_kwargs:
        raise ValueError(
            f"Cannot create histogram: missing 'x' or 'y' column mapping in dict_kwargs. "
            f"Available columns: {list(df.columns)}"
        )

    fig = plot_fn(df, **safe_kwargs)
    if title:
        fig.update_layout(title=title)
    fig.update_layout(margin=dict(l=40, r=20, t=50, b=40))

    return dmc.Paper(
        dcc.Graph(
            figure=fig,
            id=graph_id or f"fig-{visu_type}",
            style={"height": "100%"},
            config={"displayModeBar": False},
        ),
        withBorder=True,
        radius="md",
        p="xs",
        style={"height": "380px"},
    )
