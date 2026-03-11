"""
Plotly figure generation for Hi-C contact maps — JBrowse-style layout.

Creates a stacked view:
- Row 1: Hi-C contact map heatmap (square or upper-triangle)
- Row 2: Linear genome ruler track with position markers

Both share the same x-axis for synchronized navigation.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from hic_data import HiCData
from plotly.subplots import make_subplots

# Color scales suitable for Hi-C data
HIC_COLORSCALES = {
    "Red (classic)": [
        [0, "white"],
        [0.3, "#fee5d9"],
        [0.5, "#fc9272"],
        [0.7, "#de2d26"],
        [1.0, "#67000d"],
    ],
    "YlOrRd": "YlOrRd",
    "Hot": "Hot",
    "Inferno": "Inferno",
    "Viridis": "Viridis",
    "RdBu_r": "RdBu_r",
    "Plasma": "Plasma",
    "Reds": "Reds",
}

DEFAULT_COLORSCALE = "Red (classic)"


def create_browser_figure(
    data: HiCData,
    colorscale: str = DEFAULT_COLORSCALE,
    log_scale: bool = True,
    value_cap_percentile: float = 99.5,
    view_start_bp: int | None = None,
    view_end_bp: int | None = None,
    upper_triangle: bool = False,
    dark_mode: bool = False,
) -> go.Figure:
    """
    Create a JBrowse-style Hi-C browser figure with genome ruler.

    The figure has two vertically stacked panels sharing the x-axis:
    - Top: Hi-C contact map heatmap
    - Bottom: Linear genome position ruler

    Parameters
    ----------
    data : HiCData
        Contact map data.
    view_start_bp, view_end_bp : int | None
        Current viewport in base pairs. None = full chromosome.
    upper_triangle : bool
        Mask the lower triangle to show only upper (like JBrowse).
    """
    matrix = data.matrix.copy()
    n_total = matrix.shape[0]

    # Compute bin range for the current viewport
    if view_start_bp is not None and view_end_bp is not None:
        bin_lo = max(0, (view_start_bp - data.start) // data.resolution)
        bin_hi = min(n_total, (view_end_bp - data.start + data.resolution - 1) // data.resolution)
    else:
        bin_lo, bin_hi = 0, n_total
        view_start_bp = data.start
        view_end_bp = data.end

    matrix = matrix[bin_lo:bin_hi, bin_lo:bin_hi]
    n = matrix.shape[0]

    if n == 0:
        return _empty_figure("No data in selected region", dark_mode)

    # Upper triangle mask
    if upper_triangle:
        mask = np.tril(np.ones_like(matrix, dtype=bool), k=-1)
        matrix = np.where(mask, np.nan, matrix)

    # Log transform
    if log_scale:
        matrix = np.log10(matrix + 1)

    # Cap extreme values
    valid_vals = matrix[np.isfinite(matrix) & (matrix > 0)]
    if len(valid_vals) > 0 and value_cap_percentile < 100:
        cap = np.percentile(valid_vals, value_cap_percentile)
        matrix = np.clip(matrix, 0, cap)

    # Genomic x-coordinates in Mb for each bin
    x_coords_bp = np.array([data.start + (bin_lo + i) * data.resolution for i in range(n)])
    x_coords_mb = x_coords_bp / 1_000_000

    # Create subplots: heatmap (top) + genome ruler (bottom)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.88, 0.12],
        vertical_spacing=0.02,
    )

    # Resolve colorscale
    cs = HIC_COLORSCALES.get(colorscale, colorscale)

    zmax = float(np.nanmax(matrix)) if np.nanmax(matrix) > 0 else 1

    # ── Row 1: Hi-C heatmap ──
    fig.add_trace(
        go.Heatmap(
            z=matrix,
            x=x_coords_mb,
            y=x_coords_mb,
            colorscale=cs,
            zmin=0,
            zmax=zmax,
            colorbar=dict(
                title=dict(text="log₁₀(counts+1)" if log_scale else "counts"),
                thickness=12,
                len=0.5,
                y=0.6,
                yanchor="middle",
            ),
            hovertemplate=(
                f"{data.chrom}:%{{x:.2f}}Mb × {data.chrom}:%{{y:.2f}}Mb<br>"
                "Value: %{z:.2f}<extra></extra>"
            ),
            showscale=True,
        ),
        row=1,
        col=1,
    )

    # ── Row 2: Linear genome ruler ──
    ruler_start_mb = view_start_bp / 1_000_000
    ruler_end_mb = view_end_bp / 1_000_000

    # Chromosome bar
    fig.add_trace(
        go.Bar(
            x=[ruler_end_mb - ruler_start_mb],
            y=[""],
            orientation="h",
            base=ruler_start_mb,
            marker=dict(color="#4dabf7", opacity=0.3, line=dict(color="#4dabf7", width=1)),
            hoverinfo="skip",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Centromere-style midpoint marker
    mid_mb = (ruler_start_mb + ruler_end_mb) / 2
    fig.add_trace(
        go.Scatter(
            x=[mid_mb],
            y=[""],
            mode="markers",
            marker=dict(symbol="diamond", size=8, color="#4dabf7"),
            hoverinfo="skip",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Tick marks on the ruler
    tick_positions_mb, tick_labels = _make_ruler_ticks(view_start_bp, view_end_bp, data.chrom)
    for pos_mb, label in zip(tick_positions_mb, tick_labels):
        fig.add_annotation(
            x=pos_mb,
            y=0,
            text=label,
            showarrow=False,
            font=dict(size=9, color="#868e96" if not dark_mode else "#adb5bd"),
            yref="y2",
            xref="x2",
            yshift=-12,
        )

    # ── Layout styling ──
    text_color = "#c9d1d9" if dark_mode else "#333"
    bg = "rgba(0,0,0,0)"

    res_label = _format_resolution(data.resolution)
    title = f"{data.chrom} — {_format_bp(view_start_bp)} to {_format_bp(view_end_bp)} ({res_label} resolution)"

    fig.update_layout(
        title=dict(text=title, font=dict(size=14), x=0.01, xanchor="left"),
        paper_bgcolor=bg,
        plot_bgcolor=bg,
        font=dict(color=text_color, size=11),
        autosize=True,
        margin=dict(l=60, r=20, t=40, b=30),
        # Heatmap axes (row 1)
        yaxis=dict(
            title=f"Position ({data.chrom})",
            autorange="reversed",
            scaleanchor="x",
            constrain="domain",
            showgrid=False,
            ticksuffix=" Mb",
        ),
        xaxis=dict(
            showgrid=False,
        ),
        # Ruler axes (row 2)
        xaxis2=dict(
            title=f"{data.chrom} position (Mb)",
            showgrid=False,
            range=[ruler_start_mb, ruler_end_mb],
            ticksuffix=" Mb",
        ),
        yaxis2=dict(
            visible=False,
            fixedrange=True,
        ),
        dragmode="zoom",
    )

    return fig


def _make_ruler_ticks(start_bp: int, end_bp: int, chrom: str) -> tuple[list[float], list[str]]:
    """Generate ruler tick positions (in Mb) and labels."""
    span_bp = end_bp - start_bp
    # Choose nice tick interval
    nice = [
        1_000,
        5_000,
        10_000,
        25_000,
        50_000,
        100_000,
        250_000,
        500_000,
        1_000_000,
        2_500_000,
        5_000_000,
        10_000_000,
        25_000_000,
        50_000_000,
        100_000_000,
    ]
    target = span_bp / 6
    interval = nice[0]
    for n in nice:
        if n >= target:
            interval = n
            break

    # Generate ticks
    first_tick = ((start_bp // interval) + 1) * interval
    positions_mb = []
    labels = []
    bp = first_tick
    while bp < end_bp:
        positions_mb.append(bp / 1_000_000)
        labels.append(_format_bp(bp))
        bp += interval

    return positions_mb, labels


def _format_bp(bp: int) -> str:
    """Format base pair position as human-readable string."""
    if bp >= 1_000_000:
        return f"{bp / 1_000_000:.1f} Mb"
    if bp >= 1_000:
        return f"{bp / 1_000:.0f} kb"
    return f"{bp} bp"


def _format_resolution(res: int) -> str:
    """Format resolution as human-readable string."""
    if res >= 1_000_000:
        return f"{res // 1_000_000} Mb"
    if res >= 1_000:
        return f"{res // 1_000} kb"
    return f"{res} bp"


def _empty_figure(message: str, dark_mode: bool = False) -> go.Figure:
    """Return an empty figure with a centered message."""
    text_color = "#c9d1d9" if dark_mode else "#333"
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=18, color=text_color),
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig
