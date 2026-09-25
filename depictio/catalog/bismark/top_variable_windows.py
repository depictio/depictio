"""The windows whose methylation moves most across the cohort.

A correlation heatmap says the libraries differ; this says *where*. Ranking the
windows of ``bismark_binned_methylation`` by their variance across libraries and
keeping the top ``TOP_N`` gives the region-level equivalent of a top-variable-gene
heatmap: rows are windows, columns are libraries, and the block structure that
appears is the part of the methylome the design actually moved.

Variance across samples rather than a test statistic on purpose: this tile is
exploratory and has no design behind it, so it stays honest about being a
ranking and leaves significance to ``bismark_window_group_compare``. Windows
whose methylation is flat everywhere carry no information about the cohort, and
there are tens of thousands of them, so dropping them is what makes the heatmap
readable at all.

The frame is wide (one column per library), the shape ``complex_heatmap`` binds.
``chromosome`` rides along as a string, so it annotates rows without being read
as a value column, and ``start`` / ``end`` are deliberately absent for the same
reason: an integer coordinate column would land in the matrix as data.

Output schema:
    window_id : Utf8       ``chr1:10000-20000``, the heatmap's row label
    chromosome : Utf8      contig the window sits on, for a row annotation strip
    window_variance : Float64  variance of the window's methylation across libraries
    <sample> : Float64     one column per library, its % methylation in the window
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.genomic_bins import window_id_expr

MATRIX_DC_TAG = "bismark_binned_methylation"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="windows", dc_ref=MATRIX_DC_TAG),
]

# Every remaining column is a library of the run; see `window_correlation.py`.
EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "window_id": pl.Utf8,
    "chromosome": pl.Utf8,
    "window_variance": pl.Float64,
}

#: How many windows the heatmap keeps. Enough rows to show a block structure,
#: few enough that a row label stays legible at the tile's height.
TOP_N = 150


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rank the windows by cross-library variance, keep the top slice, pivot."""
    windows = sources["windows"]
    required = {"sample", "chromosome", "start", "end", "methylation_pct"}
    missing = required - set(windows.columns)
    if missing:
        raise ValueError(
            f"bismark_top_variable_windows: '{MATRIX_DC_TAG}' lacks {sorted(missing)}, "
            f"got {windows.columns}"
        )

    labelled = windows.with_columns(window_id_expr())
    ranked = (
        labelled.group_by(["window_id", "chromosome"])
        .agg(pl.col("methylation_pct").var().alias("window_variance"))
        .drop_nulls("window_variance")
        .sort("window_variance", descending=True)
        .head(TOP_N)
    )
    if ranked.is_empty():
        raise ValueError(
            "bismark_top_variable_windows: no window varies across the libraries; the "
            "cohort has a single library or an identical methylome in all of them"
        )

    wide = (
        labelled.join(ranked.select("window_id"), on="window_id", how="inner")
        .pivot(on="sample", index="window_id", values="methylation_pct")
        .join(ranked, on="window_id", how="inner")
    )
    sample_columns = [
        c for c in wide.columns if c not in {"window_id", "chromosome", "window_variance"}
    ]
    return wide.select(
        pl.col("window_id").cast(pl.Utf8),
        pl.col("chromosome").cast(pl.Utf8),
        pl.col("window_variance").cast(pl.Float64),
        *[pl.col(name).cast(pl.Float64) for name in sorted(sample_columns)],
    ).sort("window_variance", descending=True)
