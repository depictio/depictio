"""Backsub's adjusted marker sheet, one row per channel of the corrected image.

Backsub subtracts, channel by channel, a background channel scaled by the ratio
of exposure times, and writes the marker sheet that matches its output image:
``channel_number``, ``cycle_number``, ``marker_name``, ``exposure`` and
``background`` (the channel subtracted from this one, empty when none). Channels
flagged ``remove`` in the input sheet are dropped from the image and from this
sheet, so it is the authoritative channel list of the background-corrected
image the segmenters and MCQUANT read.

The sheet carries no sample column, so the sample is read off the file name
(``<sample>_backsub.csv``). ``background_subtracted`` is true for a channel that
had a background channel removed.

Output columns:
    sample, channel_number, cycle_number, marker_name, exposure, background,
    background_subtracted
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_SOURCE_PATH = "_source_path"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="markers",
        glob_pattern="**/backsub/*.csv",
        format="CSV",
        source_path=_SOURCE_PATH,
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "channel_number": pl.Int64,
    "cycle_number": pl.Int64,
    "marker_name": pl.Utf8,
    "exposure": pl.Float64,
    "background": pl.Utf8,
    "background_subtracted": pl.Boolean,
}


def _col(frame: pl.DataFrame, name: str, dtype: type[pl.DataType]) -> pl.Expr:
    if name not in frame.columns:
        return pl.lit(None, dtype=dtype).alias(name)
    expr = pl.col(name).str.strip_chars().replace("", None)
    return expr.cast(dtype, strict=False).alias(name) if dtype is not pl.Utf8 else expr.alias(name)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["markers"]
    if "marker_name" not in df.columns:
        raise ValueError("backsub markers: the sheet has no marker_name column")
    sample = (
        pl.col(_SOURCE_PATH)
        .str.split("/")
        .list.last()
        .str.replace(r"\.csv$", "")
        .str.replace(r"_backsub$", "")
        .alias("sample")
    )
    out = df.select(
        sample,
        _col(df, "channel_number", pl.Int64),
        _col(df, "cycle_number", pl.Int64),
        _col(df, "marker_name", pl.Utf8),
        _col(df, "exposure", pl.Float64),
        _col(df, "background", pl.Utf8),
    ).with_columns(pl.col("background").is_not_null().alias("background_subtracted"))
    return out.sort("sample", "channel_number").select(*EXPECTED_SCHEMA)
