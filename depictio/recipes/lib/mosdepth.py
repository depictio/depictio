"""Pass selection shared by the mosdepth recipes.

A sarek run publishes mosdepth once per processing stage, so a sample can carry
several passes of the same table. The recipes keep a single pass per sample, the
most processed one, and recipes may not import each other, so the rule lives here.
"""

from __future__ import annotations

import polars as pl

STAGE_PREFERENCE = ("recal", "md", "sorted")


def keep_one_stage(df: pl.DataFrame) -> pl.DataFrame:
    """Rows of one mosdepth pass per sample (see ``STAGE_PREFERENCE``)."""
    rank = pl.col("stage").replace_strict(
        {s: i for i, s in enumerate(STAGE_PREFERENCE)},
        default=len(STAGE_PREFERENCE),
        return_dtype=pl.Int64,
    )
    kept = (
        df.select("sample", "stage")
        .unique()
        .with_columns(rank.alias("_rank"))
        .sort(["sample", "_rank", "stage"])
        .unique(subset="sample", keep="first", maintain_order=True)
        .select("sample", "stage")
    )
    return df.join(kept, on=["sample", "stage"], how="semi")


#: The column polars names a fifth field when the scan declares four.
_NAMED_TARGET_DEPTH_COL = "column_5"


def region_depth(df: pl.DataFrame) -> pl.Expr:
    """The mean depth of a ``regions.bed.gz`` row, as Float64.

    mosdepth copies the ``--by`` bed's columns before the depth, so a capture bed
    with a name column (gene names, as most vendor exome beds have) yields
    ``chrom start end name depth``. The scan names four columns, so there the
    fourth holds the name and the depth lands in a fifth: read it when present.
    """
    coverage = pl.col("coverage").cast(pl.Float64, strict=False)
    if _NAMED_TARGET_DEPTH_COL not in df.columns:
        return coverage
    return pl.coalesce(pl.col(_NAMED_TARGET_DEPTH_COL).cast(pl.Float64, strict=False), coverage)
