"""Dimensionality-reduction helpers for recipe authors.

All four entry points return a polars DataFrame matching the canonical
``embedding`` schema (see depictio/models/components/advanced_viz/schemas.py):

    sample_id : Utf8
    dim_1 : Float64
    dim_2 : Float64
    (optional) dim_3 : Float64

Inputs are wide sample-by-feature matrices (rows = samples, first column =
sample id) OR a precomputed distance matrix for PCoA. Recipes typically
load the count/abundance table, pivot if needed, then call one of these.

These are pure functions — safe to import from a Celery task body later
without rewiring.
"""

from __future__ import annotations

import numpy as np
import polars as pl


def _split_sample_ids(matrix: pl.DataFrame) -> tuple[list[str], np.ndarray]:
    """Split a wide matrix into (sample_ids, numeric ndarray)."""
    if matrix.is_empty():
        raise ValueError("dim-reduction: input matrix is empty")
    sample_col = matrix.columns[0]
    sample_ids = matrix[sample_col].cast(pl.Utf8).to_list()
    numeric = matrix.drop(sample_col).to_numpy().astype(np.float64, copy=False)
    if np.isnan(numeric).any():
        numeric = np.nan_to_num(numeric, nan=0.0)
    return sample_ids, numeric


def _to_dataframe(sample_ids: list[str], coords: np.ndarray) -> pl.DataFrame:
    """Wrap embedding coords into the canonical embedding DC schema."""
    n_dims = coords.shape[1]
    cols: dict[str, list] = {"sample_id": sample_ids}
    for i in range(min(n_dims, 3)):
        cols[f"dim_{i + 1}"] = coords[:, i].astype(np.float64).tolist()
    return pl.DataFrame(cols).with_columns(
        pl.col("sample_id").cast(pl.Utf8),
        *[pl.col(f"dim_{i + 1}").cast(pl.Float64) for i in range(min(n_dims, 3))],
    )


def run_pca(
    matrix: pl.DataFrame,
    n_components: int = 2,
    scale: bool = True,
) -> pl.DataFrame:
    """Principal Component Analysis on a wide sample×feature matrix."""
    sample_ids, x = _split_sample_ids(matrix)
    if scale:
        std = x.std(axis=0, ddof=0)
        std[std == 0.0] = 1.0
        x = (x - x.mean(axis=0)) / std
    else:
        x = x - x.mean(axis=0)
    # Use SVD directly to avoid pinning a sklearn version.
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    coords = x @ vt[:n_components].T
    return _to_dataframe(sample_ids, coords)


def run_umap(
    matrix: pl.DataFrame,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    n_components: int = 2,
    metric: str = "euclidean",
    random_state: int = 42,
) -> pl.DataFrame:
    """UMAP via the umap-learn library (already a project dependency)."""
    import umap

    sample_ids, x = _split_sample_ids(matrix)
    # Cap n_neighbors at n_samples - 1 to avoid UMAP errors on tiny matrices.
    n_neighbors = max(2, min(n_neighbors, x.shape[0] - 1))
    reducer = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        n_components=n_components,
        metric=metric,
        random_state=random_state,
    )
    coords = reducer.fit_transform(x)
    return _to_dataframe(sample_ids, coords)


def run_tsne(
    matrix: pl.DataFrame,
    perplexity: float = 30.0,
    n_iter: int = 1000,
    learning_rate: float | str = "auto",
    metric: str = "euclidean",
    random_state: int = 42,
    n_components: int = 2,
) -> pl.DataFrame:
    """t-SNE via scikit-learn (transitively available through umap-learn)."""
    from sklearn.manifold import TSNE

    sample_ids, x = _split_sample_ids(matrix)
    # Clamp perplexity below n_samples (TSNE requires perplexity < n_samples).
    safe_perp = min(perplexity, max(2.0, (x.shape[0] - 1) / 3.0))
    tsne = TSNE(
        n_components=n_components,
        perplexity=safe_perp,
        max_iter=n_iter,
        learning_rate=learning_rate,
        metric=metric,
        random_state=random_state,
        init="pca",
    )
    coords = tsne.fit_transform(x)
    return _to_dataframe(sample_ids, coords)


def bray_curtis_distance(matrix_no_id: np.ndarray) -> np.ndarray:
    """Square symmetric Bray-Curtis distance matrix.

    BC(i, j) = sum(|x_i - x_j|) / sum(x_i + x_j). Defined for non-negative
    abundance vectors. Returns zeros on the diagonal.
    """
    n = matrix_no_id.shape[0]
    out = np.zeros((n, n), dtype=np.float64)
    row_sum = matrix_no_id.sum(axis=1)
    for i in range(n):
        for j in range(i + 1, n):
            denom = row_sum[i] + row_sum[j]
            if denom == 0.0:
                d = 0.0
            else:
                d = np.abs(matrix_no_id[i] - matrix_no_id[j]).sum() / denom
            out[i, j] = d
            out[j, i] = d
    return out


def run_pcoa(
    matrix: pl.DataFrame,
    n_components: int = 2,
    distance: str = "bray_curtis",
) -> pl.DataFrame:
    """Principal Coordinates Analysis (classical MDS) on a sample×feature matrix.

    Implements PCoA from numpy directly to avoid scikit-bio as a dependency:
    1) compute Bray-Curtis distance matrix D from rows
    2) double-centre to obtain Gram matrix B = -1/2 J D^2 J,
       J = I - 1/n 11^T
    3) eigendecompose B, take top ``n_components`` positive eigenpairs;
       coordinates = U_k * sqrt(λ_k).
    """
    sample_ids, x = _split_sample_ids(matrix)
    if distance != "bray_curtis":
        raise ValueError(f"run_pcoa: unsupported distance {distance!r}")
    d = bray_curtis_distance(x)
    n = d.shape[0]
    j = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * j @ (d**2) @ j
    eigenvalues, eigenvectors = np.linalg.eigh(b)
    # eigh returns ascending; flip for descending.
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    # Clip negative eigenvalues that arise from numerical noise.
    eigenvalues = np.clip(eigenvalues, a_min=0.0, a_max=None)
    coords = eigenvectors[:, :n_components] * np.sqrt(eigenvalues[:n_components])
    return _to_dataframe(sample_ids, coords)
