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


def impute_for_clustering(data: NDArray[np.floating]) -> NDArray[np.floating]:
    """Return *data* with every non-finite cell replaced by its column mean.

    The fallback for metrics other than euclidean when the matrix has holes.
    A column with no finite value at all is filled with 0. The caller's array
    is left untouched.
    """
    arr = np.asarray(data, dtype=float)
    missing = ~np.isfinite(arr)
    if not missing.any():
        return arr
    filled = arr.copy()
    with np.errstate(all="ignore"):
        col_means = np.nanmean(np.where(missing, np.nan, arr), axis=0)
    col_means = np.where(np.isfinite(col_means), col_means, 0.0)
    filled[missing] = np.broadcast_to(col_means, arr.shape)[missing]
    return filled


def masked_euclidean_condensed(data: NDArray[np.floating]) -> NDArray[np.floating]:
    """Condensed euclidean distances over the features each pair of rows shares.

    A matrix with holes (a sample never measured on one feature, two libraries
    that were never compared, so their distance is empty) has no pairwise
    distance scipy will accept. Each pair is measured on the coordinates both
    rows have, scaled up to the full feature count as ``nan_euclidean`` does,
    so a pair with two holes is not closer than a pair with none. A pair with
    nothing in common is put at twice the farthest measured distance: nothing
    says those rows are alike, so they merge last. Filling holes with a column
    mean instead would do the opposite on a block-diagonal distance matrix and
    pair rows across the blocks.
    """
    arr = np.asarray(data, dtype=float)
    present = np.isfinite(arr)
    x = np.where(present, arr, 0.0)
    p = present.astype(float)
    sq = x * x
    # sum over the shared features k of (x_ik - x_jk)^2: x is 0 where absent,
    # so the cross term only ever counts a feature both rows have.
    gram = sq @ p.T + p @ sq.T - 2.0 * (x @ x.T)
    shared = p @ p.T
    n_features = arr.shape[1]
    with np.errstate(divide="ignore", invalid="ignore"):
        d2 = np.where(shared > 0, gram * (n_features / shared), np.nan)
    d = np.sqrt(np.maximum(d2, 0.0))
    cond = d[np.triu_indices(arr.shape[0], k=1)]
    undefined = ~np.isfinite(cond)
    if undefined.any():
        measured = cond[~undefined]
        farthest = float(measured.max()) if measured.size else 0.0
        cond = np.where(undefined, 2.0 * farthest if farthest > 0 else 1.0, cond)
    return cond


def compute_linkage(
    data: NDArray[np.floating],
    method: str = "ward",
    metric: str = "euclidean",
    optimal_ordering: bool = True,
) -> NDArray[np.floating]:
    """Compute a linkage matrix, preferring *fastcluster* when available.

    A matrix with non-finite cells is clustered on the distances each pair of
    rows can be measured on (see :func:`masked_euclidean_condensed`); other
    metrics fall back to column-mean imputation. The heatmap itself keeps
    showing the holes as empty cells: only the ordering uses the fill.
    """
    arr = np.asarray(data, dtype=float)
    if not np.isfinite(arr).all():
        dist = (
            masked_euclidean_condensed(arr)
            if metric == "euclidean"
            else pdist(impute_for_clustering(arr), metric=metric)
        )
        return linkage(dist, method=method, optimal_ordering=optimal_ordering)

    if _HAS_FASTCLUSTER:
        return np.asarray(fastcluster.linkage(arr, method=method, metric=metric))

    dist = pdist(arr, metric=metric)
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
