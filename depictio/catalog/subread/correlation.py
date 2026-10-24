"""Library correlation matrix over the features a featureCounts run detects.

Spearman correlation of ``log2(cpm + 1)`` between every pair of libraries,
over the features detected (10 reads) in at least half of them
(``depictio/recipes/lib/count_matrix.py``, the same selection the PCA of a
template reads). Spearman rather than Pearson because a handful of features
counted in the hundreds of thousands (rRNA, histone clusters) would otherwise
set every coefficient on their own.

Left square, as ``deeptools/correlation_matrix.py`` leaves its matrix: that is
the shape ``complex_heatmap`` binds, an index column plus one value column per
library.

Output schema:
    sample : Utf8       library the row belongs to
    <sample> : Float64  one column per library, its correlation with the row
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.count_matrix import expressed_matrix, spearman

RAW_DC_TAG = "subread_gene_counts"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="counts",
        dc_ref=RAW_DC_TAG,
        input_schema={
            "gene_id": pl.Utf8,
            "sample": pl.Utf8,
            "counts": pl.Int64,
            "log2_cpm": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
# The row-label column is the only fixed one: every other column is a library of
# the run.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    counts = sources["counts"]
    if counts.is_empty():
        raise ValueError("subread_correlation: the count table is empty")
    return spearman(expressed_matrix(counts)).sort("sample")
