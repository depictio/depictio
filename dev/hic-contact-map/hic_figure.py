"""
Plotly figure generation for Hi-C contact maps.

Creates interactive heatmap visualizations with:
- Log-scale color mapping
- Genomic coordinate axes
- Multiple color scale options
- Region selection / zoom support
- TAD boundary overlay (optional)
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from hic_data import HiCData
from numpy.typing import NDArray

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


def create_contact_map_figure(
    data: HiCData,
    colorscale: str = DEFAULT_COLORSCALE,
    log_scale: bool = True,
    show_diagonal: bool = True,
    value_cap_percentile: float = 99.5,
    region_start: int | None = None,
    region_end: int | None = None,
    dark_mode: bool = False,
) -> go.Figure:
    """
    Create a Plotly figure for a Hi-C contact map.

    Parameters
    ----------
    data : HiCData
        Contact map data container.
    colorscale : str
        Name of the color scale (key from HIC_COLORSCALES).
    log_scale : bool
        Apply log10(1 + x) transformation.
    show_diagonal : bool
        Whether to highlight the diagonal.
    value_cap_percentile : float
        Cap values at this percentile for better contrast.
    region_start, region_end : int | None
        Genomic coordinates to zoom into (in base pairs).
    dark_mode : bool
        Use dark theme styling.
    """
    matrix = data.matrix.copy()

    # Subset to region if specified
    if region_start is not None or region_end is not None:
        rs = region_start or data.start
        re = region_end or data.end
        bin_start = max(0, (rs - data.start) // data.resolution)
        bin_end = min(matrix.shape[0], (re - data.start) // data.resolution)
        matrix = matrix[bin_start:bin_end, bin_start:bin_end]
        actual_start = data.start + bin_start * data.resolution
    else:
        bin_start = 0
        actual_start = data.start

    n = matrix.shape[0]
    if n == 0:
        return _empty_figure("No data in selected region", dark_mode)

    # Log transform
    if log_scale:
        matrix = np.log10(matrix + 1)

    # Cap extreme values for better color contrast
    if value_cap_percentile < 100:
        cap = np.percentile(matrix[matrix > 0], value_cap_percentile)
        matrix = np.clip(matrix, 0, cap)

    # Generate genomic coordinate labels
    tick_positions, tick_labels = _make_genomic_ticks(n, actual_start, data.resolution, data.chrom)

    # Resolve colorscale
    cs = HIC_COLORSCALES.get(colorscale, colorscale)

    # Build heatmap
    fig = go.Figure()

    fig.add_trace(
        go.Heatmap(
            z=matrix,
            x0=0,
            dx=1,
            y0=0,
            dy=1,
            colorscale=cs,
            zmin=0,
            zmax=float(matrix.max()) if matrix.max() > 0 else 1,
            colorbar=dict(
                title=dict(text="log10(counts+1)" if log_scale else "counts"),
                thickness=15,
                len=0.6,
            ),
            hovertemplate=(
                f"{data.chrom}:%{{customdata[0]}} × {data.chrom}:%{{customdata[1]}}<br>"
                "Value: %{z:.2f}<extra></extra>"
            ),
            customdata=_make_hover_data(n, actual_start, data.resolution),
        )
    )

    # Theme
    bg_color = "rgba(0,0,0,0)"
    text_color = "#c9d1d9" if dark_mode else "#333"
    grid_color = "rgba(255,255,255,0.1)" if dark_mode else "rgba(0,0,0,0.1)"

    res_label = _format_resolution(data.resolution)
    title = f"{data.chrom} Contact Map ({res_label})"
    if data.normalization != "raw":
        title += f" — {data.normalization}"

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis=dict(
            title=f"Genomic position ({data.chrom})",
            tickvals=tick_positions,
            ticktext=tick_labels,
            tickangle=45,
            showgrid=False,
            gridcolor=grid_color,
            color=text_color,
            scaleanchor="y",
            constrain="domain",
        ),
        yaxis=dict(
            title=f"Genomic position ({data.chrom})",
            tickvals=tick_positions,
            ticktext=tick_labels,
            showgrid=False,
            gridcolor=grid_color,
            autorange="reversed",
            color=text_color,
            constrain="domain",
        ),
        paper_bgcolor=bg_color,
        plot_bgcolor=bg_color,
        font=dict(color=text_color),
        autosize=True,
        margin=dict(l=80, r=30, t=60, b=80),
    )

    return fig


def _make_genomic_ticks(
    n_bins: int, start: int, resolution: int, chrom: str
) -> tuple[list[int], list[str]]:
    """Generate nicely spaced genomic coordinate tick labels."""
    total_bp = n_bins * resolution
    # Aim for ~8-10 ticks
    nice_intervals = [
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
    ]
    target_n_ticks = 8
    bp_per_tick = total_bp / target_n_ticks

    interval = nice_intervals[0]
    for ni in nice_intervals:
        if ni >= bp_per_tick:
            interval = ni
            break

    positions = []
    labels = []
    bp = 0
    while bp <= total_bp:
        bin_pos = bp // resolution
        if bin_pos < n_bins:
            positions.append(bin_pos)
            labels.append(_format_bp(start + bp))
        bp += interval

    return positions, labels


def _format_bp(bp: int) -> str:
    """Format base pair position as human-readable string."""
    if bp >= 1_000_000:
        return f"{bp / 1_000_000:.1f}Mb"
    if bp >= 1_000:
        return f"{bp / 1_000:.0f}kb"
    return f"{bp}bp"


def _format_resolution(res: int) -> str:
    """Format resolution as human-readable string."""
    if res >= 1_000_000:
        return f"{res // 1_000_000}Mb"
    if res >= 1_000:
        return f"{res // 1_000}kb"
    return f"{res}bp"


def _make_hover_data(n_bins: int, start: int, resolution: int) -> NDArray:
    """Create customdata array with genomic positions for hover."""
    coords = np.array([_format_bp(start + i * resolution) for i in range(n_bins)])
    # Shape: (n_bins, n_bins, 2) — [x_coord, y_coord]
    x_coords = np.tile(coords, (n_bins, 1))  # each row = x labels
    y_coords = np.tile(coords[:, None], (1, n_bins))  # each col = y labels
    return np.stack([x_coords, y_coords], axis=-1)


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
