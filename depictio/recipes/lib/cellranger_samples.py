"""Recover the sample id a Cell Ranger output sits under, from its path.

Cell Ranger writes one directory per sample and no sample column inside the
files, so every recipe reading a raw scan of ``cellranger/count/<sample>/outs/``
has to pull the sample out of ``source_path``. The directory the sample name
sits in differs per output (``filtered_feature_bc_matrix/``, ``analysis/``,
``analysis/diffexp/``), so the caller owns the pattern; what is shared is the
two guards around it, which are what turn a mis-declared data collection into a
message naming the collection instead of a null column that quietly drops rows.

Shared here rather than copied because several recipes in the tool need exactly
this, and recipes may not import one another.
"""

from __future__ import annotations

import polars as pl

SOURCE_PATH_COL = "source_path"


def with_sample_column(df: pl.DataFrame, pattern: str, dc_name: str, recipe: str) -> pl.DataFrame:
    """``df`` plus a ``sample`` column, group 1 of ``pattern`` over ``source_path``.

    Raises ``ValueError`` when the data collection was not scanned with
    ``include_file_paths``, or when a row's path does not carry a sample.
    """
    if SOURCE_PATH_COL not in df.columns:
        raise ValueError(
            f"{recipe}: '{dc_name}' has no '{SOURCE_PATH_COL}' column, "
            "it must be scanned with polars_kwargs.include_file_paths"
        )
    out = df.with_columns(pl.col(SOURCE_PATH_COL).str.extract(pattern, 1).alias("sample"))
    if out.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            f"{recipe}: a row's {SOURCE_PATH_COL} in '{dc_name}' did not match {pattern!r}"
        )
    return out
