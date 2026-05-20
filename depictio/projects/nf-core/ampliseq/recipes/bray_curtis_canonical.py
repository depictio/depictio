"""Canonical-schema Bray-Curtis distance DC for ampliseq.

Computes a symmetric sample × sample Bray-Curtis distance matrix from the
long-format ``taxonomy_rel_abundance`` DC. Output shape is a square wide
matrix suitable for the ComplexHeatmap renderer with ``index_column=sample``.

Schema for ``complex_heatmap`` requires only a String ``index`` column;
matrix columns are inferred from the rest of the schema at compute time.
The renderer's existing clustering path will rediscover the matrix' symmetry
and produce coherent row/column dendrograms — symmetric-mode UX polish
(shared / triangular dendrograms) is a follow-up framework enhancement.
"""

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="rel_abundance", dc_ref="taxonomy_rel_abundance"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
}
# Per-sample distance columns are dynamic — validated via OPTIONAL_SCHEMA = {}.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Build sample × sample Bray-Curtis distance matrix."""
    df = sources["rel_abundance"]

    if "sample" not in df.columns or "rel_abundance" not in df.columns:
        raise ValueError(
            "ampliseq bray_curtis: taxonomy_rel_abundance must expose sample + rel_abundance"
        )

    if "taxonomy" not in df.columns:
        raise ValueError("ampliseq bray_curtis: taxonomy_rel_abundance must expose taxonomy")

    wide = df.pivot(
        values="rel_abundance",
        index="taxonomy",
        on="sample",
        aggregate_function="sum",
    ).fill_null(0.0)

    sample_cols = [c for c in wide.columns if c != "taxonomy"]
    matrix = wide.select(sample_cols).to_numpy().T  # shape (n_samples, n_taxa)

    # Vectorised Bray-Curtis: |a-b|.sum() / (a+b).sum() across the taxa axis.
    diff_sum = np.abs(matrix[:, None, :] - matrix[None, :, :]).sum(axis=2)
    add_sum = (matrix[:, None, :] + matrix[None, :, :]).sum(axis=2)
    distances = np.divide(diff_sum, add_sum, out=np.zeros_like(diff_sum), where=add_sum > 0)

    return pl.DataFrame(
        {
            "sample": sample_cols,
            **{sample_cols[j]: distances[:, j].tolist() for j in range(distances.shape[1])},
        }
    )
