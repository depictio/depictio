"""A PCA of the single-cell profiles: where each cell sits in feature space.

Every Float64 feature of the single-cell table is standardised (centred, scaled
to unit variance; nulls imputed with the feature's median; constant features
dropped) and projected on its first three principal components. PCA is exact,
cheap (an eigen-decomposition of the feature covariance, whose size depends on
the number of features, not of cells) and deterministic, so the map is the same
at every ingest; a UMAP would need a dependency the slim CLI environment does
not ship, and the embedding renderer can compute one live from the per-cell
feature matrix when a reader wants it.

Each cell carries its well and the value of the run's grouping column from the
``samples`` plate-map hub (``group_col`` param), plus four raw features to
colour by, so a reader can see whether cells separate by perturbation group, by
well (a plate effect) or simply by size and DNA content (cell cycle).

``pc_1_variance`` .. ``pc_3_variance`` repeat, on every row, the share of the
total variance (%) each component explains, for the axis titles and the cards.

Sources: the ``cp-cells`` single-cell table and, optionally, the ``samples`` hub.

Output schema:
    cell_id : Utf8                  ``<plate>_<well>_s<site>_<object_number>``
    well_id : Utf8                  ``<plate>_<well>``
    well : Utf8                     well
    group : Utf8                    the well's value of the grouping column
    pc_1, pc_2, pc_3 : Float64      principal-component scores
    pc_1_variance .. pc_3_variance : Float64   variance explained, %
    cell_area : Float64             cell area, pixels
    nucleus_area : Float64          nucleus area, pixels
    nucleus_dna_integrated : Float64  integrated nuclear DNA intensity
    cell_mito_mean : Float64        mean mitochondrial stain intensity in the cell
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

CELLS_DC_TAG = "cp-cells"
SAMPLES_DC_TAG = "samples"
HUB_KEY = "well_id"
DEFAULT_GROUP_COL = "pert_type"
NO_HUB_GROUP = "All wells"
UNLISTED_GROUP = "Not in plate map"
NON_FEATURES = frozenset({"x", "y"})
COLOUR_FEATURES = ("cell_area", "nucleus_area", "nucleus_dna_integrated", "cell_mito_mean")
N_COMPONENTS = 3

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="cells", dc_ref=CELLS_DC_TAG),
    RecipeSource(ref="samples", dc_ref=SAMPLES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "cell_id": pl.Utf8,
    "well_id": pl.Utf8,
    "well": pl.Utf8,
    "group": pl.Utf8,
    "pc_1": pl.Float64,
    "pc_2": pl.Float64,
    "pc_3": pl.Float64,
    "pc_1_variance": pl.Float64,
    "pc_2_variance": pl.Float64,
    "pc_3_variance": pl.Float64,
    **{name: pl.Float64 for name in COLOUR_FEATURES},
}


def hub_groups(
    samples: pl.DataFrame | None, group_col: str | None
) -> tuple[pl.DataFrame | None, str]:
    """``(well_id, group)`` from the hub, and the label of wells it misses."""
    if samples is None or samples.is_empty() or HUB_KEY not in samples.columns:
        return None, NO_HUB_GROUP
    column = group_col if group_col and group_col in samples.columns else None
    if column is None:
        column = DEFAULT_GROUP_COL if DEFAULT_GROUP_COL in samples.columns else None
    if column is None:
        return None, NO_HUB_GROUP
    groups = samples.select(pl.col(HUB_KEY), pl.col(column).cast(pl.Utf8).alias("group")).unique(
        subset=HUB_KEY
    )
    return groups, UNLISTED_GROUP


def pca(matrix: np.ndarray, n_components: int) -> tuple[np.ndarray, np.ndarray]:
    """Scores and % variance explained of the standardised ``matrix`` (cells x features)."""
    medians = np.nanmedian(matrix, axis=0)
    matrix = np.where(np.isnan(matrix), medians, matrix)
    std = matrix.std(axis=0)
    keep = std > 0
    z = (matrix[:, keep] - matrix[:, keep].mean(axis=0)) / std[keep]
    n_obs, n_feat = z.shape
    scores = np.zeros((n_obs, n_components))
    explained = np.zeros(n_components)
    if n_obs < 2 or n_feat == 0:
        return scores, explained
    cov = (z.T @ z) / (n_obs - 1)
    eigval, eigvec = np.linalg.eigh(cov)
    order = np.argsort(eigval)[::-1]
    eigval, eigvec = eigval[order], eigvec[:, order]
    k = min(n_components, n_feat)
    # Fix each component's sign (largest loading positive) so the map does not
    # mirror between ingests of the same data.
    signs = np.sign(eigvec[np.abs(eigvec[:, :k]).argmax(axis=0), range(k)])
    signs[signs == 0] = 1
    scores[:, :k] = (z @ eigvec[:, :k]) * signs
    total = eigval.clip(min=0).sum()
    if total > 0:
        explained[:k] = 100.0 * eigval[:k].clip(min=0) / total
    return scores, explained


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    cells = sources["cells"]
    features = [
        name
        for name, dtype in cells.schema.items()
        if dtype == pl.Float64 and name not in NON_FEATURES
    ]
    matrix = cells.select(features).to_numpy().astype(np.float64)
    scores, explained = pca(matrix, N_COMPONENTS)
    groups, fallback = hub_groups(sources.get("samples"), (params or {}).get("group_col"))
    if groups is not None:
        cells = cells.join(groups, on=HUB_KEY, how="left", maintain_order="left")
    else:
        cells = cells.with_columns(pl.lit(None, dtype=pl.Utf8).alias("group"))
    out = cells.select(
        "cell_id",
        "well_id",
        "well",
        pl.col("group").fill_null(fallback).cast(pl.Utf8),
        *[pl.col(c).cast(pl.Float64) for c in COLOUR_FEATURES],
    ).with_columns(
        *[pl.Series(f"pc_{i + 1}", scores[:, i], dtype=pl.Float64) for i in range(N_COMPONENTS)],
        *[
            pl.lit(float(round(explained[i], 2)), dtype=pl.Float64).alias(f"pc_{i + 1}_variance")
            for i in range(N_COMPONENTS)
        ],
    )
    return out.select([pl.col(name).cast(dtype) for name, dtype in EXPECTED_SCHEMA.items()])
