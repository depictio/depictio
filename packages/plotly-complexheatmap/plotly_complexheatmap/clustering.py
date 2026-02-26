"""Hierarchical clustering and dendrogram computation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import plotly.graph_objects as go
from numpy.typing import NDArray
from scipy.cluster.hierarchy import dendrogram, linkage
from scipy.spatial.distance import pdist

try:
    import fastcluster

    _HAS_FASTCLUSTER = True
except ImportError:
    _HAS_FASTCLUSTER = False


@dataclass
class DendrogramResult:
    """Output of hierarchical clustering with dendrogram geometry."""

    linkage_matrix: NDArray[np.floating]
    leaf_order: NDArray[np.intp]
    icoord: list[list[float]]
    dcoord: list[list[float]]


def compute_linkage(
    data: NDArray[np.floating],
    method: str = "ward",
    metric: str = "euclidean",
    optimal_ordering: bool = True,
) -> NDArray[np.floating]:
    """Compute a linkage matrix, preferring *fastcluster* when available."""
    if _HAS_FASTCLUSTER:
        return np.asarray(fastcluster.linkage(data, method=method, metric=metric))

    dist = pdist(data, metric=metric)
    return linkage(dist, method=method, optimal_ordering=optimal_ordering)


def compute_dendrogram(
    data: NDArray[np.floating],
    method: str = "ward",
    metric: str = "euclidean",
    optimal_ordering: bool = True,
) -> DendrogramResult:
    """Cluster *data* rows and return a :class:`DendrogramResult`."""
    Z = compute_linkage(data, method=method, metric=metric, optimal_ordering=optimal_ordering)
    dn = dendrogram(Z, no_plot=True, color_threshold=0)
    return DendrogramResult(
        linkage_matrix=Z,
        leaf_order=np.array(dn["leaves"]),
        icoord=dn["icoord"],
        dcoord=dn["dcoord"],
    )


def _rescale_coords(coords: list[list[float]], n_leaves: int) -> list[list[float]]:
    """Map scipy's leaf positions (5, 15, 25, …) → (0, 1, 2, …)."""
    return [[(v - 5.0) / 10.0 for v in seg] for seg in coords]


def dendrogram_traces(
    result: DendrogramResult,
    orientation: str = "top",
    line_color: str = "#444444",
    line_width: float = 1.0,
) -> list[go.Scatter]:
    """Convert a :class:`DendrogramResult` into Plotly ``go.Scatter`` line traces.

    Parameters
    ----------
    orientation:
        ``"top"`` — column dendrogram above the heatmap.
        ``"left"`` — row dendrogram to the left of the heatmap.
    """
    n_leaves = len(result.leaf_order)
    icoord = _rescale_coords(result.icoord, n_leaves)
    dcoord = result.dcoord

    traces: list[go.Scatter] = []
    for xs, ys in zip(icoord, dcoord):
        if orientation == "top":
            xv, yv = xs, ys
        elif orientation == "left":
            # Swap axes; negate x so root is on the left
            xv = [-v for v in ys]
            yv = xs
        else:
            raise ValueError(f"Unsupported dendrogram orientation: {orientation!r}")

        traces.append(
            go.Scatter(
                x=xv,
                y=yv,
                mode="lines",
                line={"color": line_color, "width": line_width},
                hoverinfo="none",
                showlegend=False,
            )
        )
    return traces
