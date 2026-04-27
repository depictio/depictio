"""Callbacks for the conditional highlighting prototype.

Architecture
------------
1. Slider range callbacks (×2): update slider min/max/marks when condition column
   or absolute-value toggle changes.
2. Toggle callbacks (×2): enable/disable condition panel controls.
3. Main view callback: single callback that computes the highlight mask and
   renders the figure, AG Grid table data, and summary card.
"""

from typing import Any

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, no_update
from data import COLUMN_LABELS

# ── Helpers ───────────────────────────────────────────────────────────────────


def _slider_params(df: pd.DataFrame, col: str, use_abs: bool = False) -> dict[str, Any]:
    """Compute slider min, max, step, midpoint value, and marks for a column.

    Args:
        df: Source data.
        col: Column name.
        use_abs: Use absolute values.

    Returns:
        Dict with keys: min, max, step, value, marks.
    """
    values = np.abs(df[col].values) if use_abs else df[col].values
    col_min = float(np.floor(values.min()))
    col_max = float(np.ceil(values.max()))
    col_range = col_max - col_min
    step = round(col_range / 200, 4) or 0.01
    n_marks = 5
    mark_step = col_range / (n_marks - 1) if n_marks > 1 else 0
    marks = [
        {
            "value": round(col_min + i * mark_step, 2),
            "label": str(round(col_min + i * mark_step, 2)),
        }
        for i in range(n_marks)
    ]
    return {
        "min": col_min,
        "max": col_max,
        "step": step,
        "value": round((col_min + col_max) / 2, 2),
        "marks": marks,
    }


def _eval_condition(series: pd.Series, op: str, threshold: float, use_abs: bool) -> pd.Series:
    """Evaluate a numeric condition, returning a boolean mask.

    Args:
        series: Data column.
        op: One of ">", "<", ">=", "<=".
        threshold: Threshold value.
        use_abs: Apply abs() to values before comparison.

    Returns:
        Boolean Series.
    """
    values = series.abs() if use_abs else series
    ops = {">": values.gt, "<": values.lt, ">=": values.ge, "<=": values.le}
    return ops[op](threshold)


def _build_condition_display(
    col: str | None, op: str, val: float, use_abs: bool, enabled: bool
) -> str:
    """Build a human-readable condition string."""
    if not enabled or not col:
        return "Disabled"
    label = COLUMN_LABELS.get(col, col)
    if use_abs:
        return f"|{label}| {op} {val:.2f}"
    return f"{label} {op} {val:.2f}"


# ── Figure builder ────────────────────────────────────────────────────────────


def _build_figure(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    color_col: str | None,
    x_scale: str,
    y_scale: str,
    mask: pd.Series,
    conditions_active: bool,
    active_conditions: list[dict],
) -> go.Figure:
    """Build the scatter figure with optional highlighting and threshold lines.

    Args:
        df: Source data.
        x_col: X-axis column.
        y_col: Y-axis column.
        color_col: Optional color grouping column.
        x_scale: "linear" or "log".
        y_scale: "linear" or "log".
        mask: Boolean highlight mask.
        conditions_active: Whether any condition is active.
        active_conditions: List of condition dicts for drawing threshold lines.

    Returns:
        Plotly Figure.
    """
    fig = go.Figure()
    palette = px.colors.qualitative.Plotly

    if conditions_active:
        if color_col:
            unique_groups = sorted(df[color_col].unique())
            for i, group in enumerate(unique_groups):
                color = palette[i % len(palette)]
                gm = df[color_col] == group
                highlighted = gm & mask
                dimmed = gm & ~mask

                # Dimmed trace (behind)
                if dimmed.any():
                    fig.add_trace(
                        go.Scatter(
                            x=df.loc[dimmed, x_col],
                            y=df.loc[dimmed, y_col],
                            mode="markers",
                            marker=dict(color=color, opacity=0.12, size=5),
                            name=str(group),
                            legendgroup=str(group),
                            showlegend=not highlighted.any(),
                            text=df.loc[dimmed, "gene_name"],
                            hovertemplate="%{text}<br>x=%{x:.3f}<br>y=%{y:.3f}<extra></extra>",
                        )
                    )

                # Highlighted trace (on top)
                if highlighted.any():
                    fig.add_trace(
                        go.Scatter(
                            x=df.loc[highlighted, x_col],
                            y=df.loc[highlighted, y_col],
                            mode="markers",
                            marker=dict(
                                color=color,
                                opacity=0.9,
                                size=8,
                                line=dict(width=0.5, color="white"),
                            ),
                            name=str(group),
                            legendgroup=str(group),
                            text=df.loc[highlighted, "gene_name"],
                            hovertemplate="%{text}<br>x=%{x:.3f}<br>y=%{y:.3f}<extra></extra>",
                        )
                    )
        else:
            # No color column — two traces: dimmed + selected
            dimmed = ~mask
            if dimmed.any():
                fig.add_trace(
                    go.Scatter(
                        x=df.loc[dimmed, x_col],
                        y=df.loc[dimmed, y_col],
                        mode="markers",
                        marker=dict(color="lightgrey", opacity=0.3, size=5),
                        name="Other",
                        text=df.loc[dimmed, "gene_name"],
                        hovertemplate="%{text}<br>x=%{x:.3f}<br>y=%{y:.3f}<extra></extra>",
                    )
                )
            if mask.any():
                fig.add_trace(
                    go.Scatter(
                        x=df.loc[mask, x_col],
                        y=df.loc[mask, y_col],
                        mode="markers",
                        marker=dict(
                            color="#e63946",
                            opacity=0.9,
                            size=8,
                            line=dict(width=0.5, color="white"),
                        ),
                        name="Selected",
                        text=df.loc[mask, "gene_name"],
                        hovertemplate="%{text}<br>x=%{x:.3f}<br>y=%{y:.3f}<extra></extra>",
                    )
                )
    else:
        # No conditions — regular scatter
        if color_col:
            unique_groups = sorted(df[color_col].unique())
            for i, group in enumerate(unique_groups):
                gm = df[color_col] == group
                fig.add_trace(
                    go.Scatter(
                        x=df.loc[gm, x_col],
                        y=df.loc[gm, y_col],
                        mode="markers",
                        marker=dict(color=palette[i % len(palette)], opacity=0.7, size=6),
                        name=str(group),
                        text=df.loc[gm, "gene_name"],
                        hovertemplate="%{text}<br>x=%{x:.3f}<br>y=%{y:.3f}<extra></extra>",
                    )
                )
        else:
            fig.add_trace(
                go.Scatter(
                    x=df[x_col],
                    y=df[y_col],
                    mode="markers",
                    marker=dict(color="#228be6", opacity=0.6, size=6),
                    name="All points",
                    text=df["gene_name"],
                    hovertemplate="%{text}<br>x=%{x:.3f}<br>y=%{y:.3f}<extra></extra>",
                )
            )

    # ── Threshold lines ──────────────────────────────────────────
    line_style = dict(dash="dash", color="rgba(255, 0, 0, 0.5)", width=1.5)
    for cond in active_conditions:
        if cond["col"] == x_col:
            fig.add_vline(x=cond["val"], line=line_style)
            if cond["abs"]:
                fig.add_vline(x=-cond["val"], line=line_style)
        elif cond["col"] == y_col:
            fig.add_hline(y=cond["val"], line=line_style)
            if cond["abs"]:
                fig.add_hline(y=-cond["val"], line=line_style)

    # ── Layout ───────────────────────────────────────────────────
    fig.update_layout(
        xaxis_title=COLUMN_LABELS.get(x_col, x_col),
        yaxis_title=COLUMN_LABELS.get(y_col, y_col),
        xaxis_type="log" if x_scale == "log" else "linear",
        yaxis_type="log" if y_scale == "log" else "linear",
        template="plotly_white",
        margin=dict(l=60, r=20, t=40, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="closest",
    )
    return fig


# ── Summary builder ───────────────────────────────────────────────────────────


def _build_summary(
    df: pd.DataFrame,
    mask: pd.Series,
    color_col: str | None,
    conditions_active: bool,
) -> list:
    """Build summary card children (list of DMC components).

    Args:
        df: Source data.
        mask: Boolean highlight mask.
        color_col: Optional color column for per-group stats.
        conditions_active: Whether any condition is active.

    Returns:
        List of DMC Badge / Text components.
    """
    if not conditions_active:
        return [dmc.Text("No conditions active — showing all points", size="sm", c="dimmed")]

    n_sel = int(mask.sum())
    n_tot = len(df)
    children: list = [
        dmc.Badge(f"Selected: {n_sel} / {n_tot}", color="blue", variant="light", size="lg"),
    ]

    if color_col:
        for group in sorted(df[color_col].unique()):
            gm = df[color_col] == group
            g_sel = int((gm & mask).sum())
            g_tot = int(gm.sum())
            pct = (g_sel / g_tot * 100) if g_tot > 0 else 0
            children.append(
                dmc.Badge(f"{group}: {g_sel}/{g_tot} ({pct:.1f}%)", variant="outline", size="sm")
            )

    return children


# ── Table helpers ─────────────────────────────────────────────────────────────

_TABLE_COLUMN_DEFS: list[dict] = [
    {
        "field": "gene_name",
        "headerName": "Gene",
        "filter": "agTextColumnFilter",
        "pinned": "left",
        "minWidth": 120,
    },
    {
        "field": "log2fc",
        "headerName": "log2(FC)",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.3f')(params.value)"},
    },
    {
        "field": "neg_log10_pvalue",
        "headerName": "-log10(p)",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.3f')(params.value)"},
    },
    {
        "field": "mean_expression",
        "headerName": "Mean Expr",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.3f')(params.value)"},
    },
    {"field": "cluster", "headerName": "Cluster", "filter": "agTextColumnFilter"},
    {"field": "significance", "headerName": "Significance", "filter": "agTextColumnFilter"},
    {"field": "_highlighted", "hide": True},
]


# ── Registration ──────────────────────────────────────────────────────────────


def register_callbacks(app: Dash, df: pd.DataFrame) -> None:
    """Register all Dash callbacks.

    Args:
        app: The Dash application instance.
        df: The source DataFrame (immutable reference).
    """

    # ── Slider range updates ─────────────────────────────────────
    for idx in (1, 2):
        _register_slider_callback(app, df, idx)
        _register_toggle_callback(app, idx)

    # ── Main view ────────────────────────────────────────────────
    @app.callback(
        Output("main-scatter", "figure"),
        Output("data-table", "rowData"),
        Output("data-table", "columnDefs"),
        Output("summary-content", "children"),
        Output("cond-1-value-display", "children"),
        Output("cond-2-value-display", "children"),
        Input("x-col", "value"),
        Input("y-col", "value"),
        Input("color-col", "value"),
        Input("x-scale", "value"),
        Input("y-scale", "value"),
        Input("cond-1-enabled", "checked"),
        Input("cond-1-col", "value"),
        Input("cond-1-op", "value"),
        Input("cond-1-abs", "checked"),
        Input("cond-1-slider", "value"),
        Input("cond-2-enabled", "checked"),
        Input("cond-2-col", "value"),
        Input("cond-2-op", "value"),
        Input("cond-2-abs", "checked"),
        Input("cond-2-slider", "value"),
    )
    def update_main_view(
        x_col: str,
        y_col: str,
        color_col: str | None,
        x_scale: str,
        y_scale: str,
        c1_on: bool,
        c1_col: str | None,
        c1_op: str,
        c1_abs: bool,
        c1_val: float | None,
        c2_on: bool,
        c2_col: str | None,
        c2_op: str,
        c2_abs: bool,
        c2_val: float | None,
    ) -> tuple:
        """Central callback: compute highlight mask → figure + table + summary."""
        if not x_col or not y_col:
            return no_update, no_update, no_update, no_update, no_update, no_update

        # ── Compute mask ─────────────────────────────────────────
        mask = pd.Series(True, index=df.index)
        active_conds: list[dict] = []
        conditions_active = False

        if c1_on and c1_col and c1_val is not None:
            mask &= _eval_condition(df[c1_col], c1_op, c1_val, c1_abs)
            active_conds.append({"col": c1_col, "op": c1_op, "val": c1_val, "abs": c1_abs})
            conditions_active = True

        if c2_on and c2_col and c2_val is not None:
            mask &= _eval_condition(df[c2_col], c2_op, c2_val, c2_abs)
            active_conds.append({"col": c2_col, "op": c2_op, "val": c2_val, "abs": c2_abs})
            conditions_active = True

        # ── Figure ───────────────────────────────────────────────
        fig = _build_figure(
            df,
            x_col,
            y_col,
            color_col,
            x_scale,
            y_scale,
            mask,
            conditions_active,
            active_conds,
        )

        # ── Table ────────────────────────────────────────────────
        table_df = df.copy()
        table_df["_highlighted"] = mask if conditions_active else True
        row_data = table_df.to_dict("records")

        # ── Summary ──────────────────────────────────────────────
        summary = _build_summary(df, mask, color_col, conditions_active)

        # ── Condition displays ───────────────────────────────────
        c1_display = _build_condition_display(c1_col, c1_op, c1_val or 0, c1_abs, c1_on)
        c2_display = _build_condition_display(c2_col, c2_op, c2_val or 0, c2_abs, c2_on)

        return fig, row_data, _TABLE_COLUMN_DEFS, summary, c1_display, c2_display


def _register_slider_callback(app: Dash, df: pd.DataFrame, idx: int) -> None:
    """Register a slider-range callback for condition `idx`."""

    @app.callback(
        Output(f"cond-{idx}-slider", "min"),
        Output(f"cond-{idx}-slider", "max"),
        Output(f"cond-{idx}-slider", "step"),
        Output(f"cond-{idx}-slider", "value"),
        Output(f"cond-{idx}-slider", "marks"),
        Input(f"cond-{idx}-col", "value"),
        Input(f"cond-{idx}-abs", "checked"),
        prevent_initial_call=True,
    )
    def _update_slider(col: str | None, use_abs: bool) -> tuple:
        if not col:
            return no_update, no_update, no_update, no_update, no_update
        p = _slider_params(df, col, use_abs)
        return p["min"], p["max"], p["step"], p["value"], p["marks"]


def _register_toggle_callback(app: Dash, idx: int) -> None:
    """Register a toggle callback for condition `idx` controls."""

    @app.callback(
        Output(f"cond-{idx}-col", "disabled"),
        Output(f"cond-{idx}-op", "disabled"),
        Output(f"cond-{idx}-abs", "disabled"),
        Output(f"cond-{idx}-slider", "disabled"),
        Input(f"cond-{idx}-enabled", "checked"),
    )
    def _toggle(enabled: bool) -> tuple[bool, bool, bool, bool]:
        return not enabled, not enabled, not enabled, not enabled
