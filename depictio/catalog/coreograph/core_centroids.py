"""Coreograph's tissue-microarray core centroids, one row per detected core.

Coreograph (UNetCoreograph) finds the cores of a tissue microarray on a
downsampled nuclear channel and writes ``centroidsY-X.txt``: one line per core,
row then column of the core centre in full-resolution pixels, written by
``numpy.savetxt`` with ``%10.5f`` (space-padded, no header). Core ``n`` of this
file is the ``n.tif`` crop and the ``masks/n_mask.tif`` mask Coreograph writes
next to it, so ``core`` numbers from 1 in file order.

nf-core/mcmicro publishes Coreograph's output under ``tma_dearray/``; when a run
nests it one directory per sample the sample is that directory, otherwise it is
the literal ``tma``.

Output columns:
    sample, core, y_centroid, x_centroid
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_SOURCE_PATH = "_source_path"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="centroids",
        glob_pattern="**/centroidsY-X.txt",
        format="CSV",
        source_path=_SOURCE_PATH,
        # One text column per line: `|` never occurs in the file.
        read_kwargs={"has_header": False, "separator": "|", "new_columns": ["line"]},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "core": pl.Int64,
    "y_centroid": pl.Float64,
    "x_centroid": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["centroids"].filter(pl.col("line").str.strip_chars() != "")
    parent = pl.col(_SOURCE_PATH).str.split("/").list.reverse().list.get(1, null_on_oob=True)
    numbers = pl.col("line").str.extract_all(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
    return (
        df.with_columns(
            pl.when(parent.is_null() | (parent == "tma_dearray"))
            .then(pl.lit("tma"))
            .otherwise(parent)
            .alias("sample"),
            numbers.list.get(0, null_on_oob=True).cast(pl.Float64).alias("y_centroid"),
            numbers.list.get(1, null_on_oob=True).cast(pl.Float64).alias("x_centroid"),
        )
        .with_columns((pl.int_range(pl.len()).over("sample") + 1).cast(pl.Int64).alias("core"))
        .select(*EXPECTED_SCHEMA)
    )
