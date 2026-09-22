"""Pairwise correlation of the libraries over their binned methylomes.

The sample x window matrix left by ``bismark_binned_methylation`` correlated
against itself: a square frame, one row and one column per library, holding the
Pearson correlation of their window-level methylation. Clustered, it is the
cohort's structure in one picture. Replicates of a condition correlate with each
other and less with everything else; a library that correlates with the wrong
block is a swap, a mislabelled sheet, or a conversion failure that flattened its
methylome.

Correlation rather than distance because the scale is already comparable
(percentages of the same windows) and because a reader reads 0.98 versus 0.91
faster than two arbitrary distances. The frame is left square rather than melted
into triples, which is the shape ``complex_heatmap`` binds: an index column plus
one value column per library.

Output schema:
    sample : Utf8       library the row belongs to
    <sample> : Float64  one column per library, its correlation with the row
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.genomic_bins import window_matrix

MATRIX_DC_TAG = "bismark_binned_methylation"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="windows", dc_ref=MATRIX_DC_TAG),
]

# Every column but the row label is a library of the run, so only the index is
# declarable here; the rest is checked against the fixture, as in
# `deeptools/correlation_matrix.py`.
EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Correlate the libraries over the windows they share."""
    matrix = window_matrix(sources["windows"])
    if matrix.height < 2:
        raise ValueError(
            f"bismark_window_correlation: a correlation needs at least two libraries, "
            f"got {matrix.height}"
        )

    samples = matrix.get_column("sample").cast(pl.Utf8).to_list()
    values = matrix.drop("sample").to_numpy().astype(np.float64, copy=False)
    # A complete matrix is the binning recipe's contract, but a window that is
    # constant across every library would still give a zero-variance column;
    # nan_to_num keeps such a pair at 0 rather than propagating NaN over the row.
    correlation = np.nan_to_num(np.corrcoef(values), nan=0.0)

    return pl.DataFrame(
        {
            "sample": samples,
            **{
                name: correlation[:, index].astype(np.float64).tolist()
                for index, name in enumerate(samples)
            },
        }
    ).with_columns(
        pl.col("sample").cast(pl.Utf8),
        *[pl.col(name).cast(pl.Float64) for name in samples],
    )
