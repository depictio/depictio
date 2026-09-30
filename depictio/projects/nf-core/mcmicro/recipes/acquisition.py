"""Acquisition parameters of every sample and cycle, from the pipeline's input checks.

Before stitching, nf-core/mcmicro reads the OME-XML of every raw cycle image and
writes one MultiQC-formatted check table per sample and cycle,
``<sample>_<cycle>_samplesheet_mqc.tsv`` (under ``summary/``, or ``prelude/``
in a prelude run): ``variable_name`` / ``value`` / ``expected`` / ``check`` rows
for the pixel size and its unit, the channel count, the pixel data type, the
tile count and the tile size, plus the sample ``id`` and the ``cycle_number``.

The recipe pivots each file to one row, keyed on the sample and cycle the file
itself names (``id`` and ``cycle_number`` rows), and counts the failed and
warned checks so an inconsistent cycle stands out.

Output columns:
    sample, cycle, pixel_size, pixel_size_unit, channel_count, pixel_datatype,
    tile_count, tile_size_x, tile_size_y, n_checks_failed, n_checks_warned
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_SOURCE_PATH = "_source_path"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="checks",
        glob_pattern="**/*_samplesheet_mqc.tsv",
        format="TSV",
        source_path=_SOURCE_PATH,
        read_kwargs={"infer_schema_length": 0, "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cycle": pl.Int64,
    "pixel_size": pl.Float64,
    "pixel_size_unit": pl.Utf8,
    "channel_count": pl.Int64,
    "pixel_datatype": pl.Utf8,
    "tile_count": pl.Int64,
    "tile_size_x": pl.Int64,
    "tile_size_y": pl.Int64,
    "n_checks_failed": pl.Int64,
    "n_checks_warned": pl.Int64,
}

_VALUES: dict[str, type[pl.DataType]] = {
    "id": pl.Utf8,
    "cycle_number": pl.Int64,
    "pixel_size": pl.Float64,
    "pixel_size_unit": pl.Utf8,
    "channel_count": pl.Int64,
    "pixel_datatype": pl.Utf8,
    "tile_count": pl.Int64,
    "tile_size_x": pl.Int64,
    "tile_size_y": pl.Int64,
}

#: MultiQC check glyphs written by the pipeline.
FAIL = "❌"
WARN = "⚠"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["checks"]
    missing = [c for c in ("variable_name", "value") if c not in df.columns]
    if missing:
        raise ValueError(f"mcmicro acquisition: check tables lack {missing}")
    check = pl.col("check") if "check" in df.columns else pl.lit("")
    df = df.with_columns(
        pl.col("variable_name").str.strip_chars(),
        pl.col("value").str.strip_chars(),
        check.fill_null("").alias("_check"),
    )
    flags = df.group_by(_SOURCE_PATH).agg(
        pl.col("_check").str.contains(FAIL).sum().cast(pl.Int64).alias("n_checks_failed"),
        pl.col("_check").str.contains(WARN).sum().cast(pl.Int64).alias("n_checks_warned"),
    )
    wide = (
        df.filter(pl.col("variable_name").is_in(list(_VALUES)))
        .unique(subset=[_SOURCE_PATH, "variable_name"], keep="first")
        .pivot(on="variable_name", index=_SOURCE_PATH, values="value")
    )
    for name in _VALUES:
        if name not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Utf8).alias(name))
    # A file without an `id` row still names its sample: `<sample>_<cycle>_samplesheet_mqc.tsv`.
    from_name = (
        pl.col(_SOURCE_PATH)
        .str.split("/")
        .list.last()
        .str.replace(r"_samplesheet_mqc\.tsv$", "")
        .str.replace(r"_\d+$", "")
    )
    wide = wide.with_columns(
        pl.coalesce(pl.col("id"), from_name).alias("sample"),
        pl.col("cycle_number").cast(pl.Float64, strict=False).cast(pl.Int64).alias("cycle"),
        pl.col("pixel_size").cast(pl.Float64, strict=False),
        *[
            pl.col(n).cast(pl.Float64, strict=False).cast(pl.Int64)
            for n, t in _VALUES.items()
            if t is pl.Int64 and n != "cycle_number"
        ],
    )
    return (
        wide.join(flags, on=_SOURCE_PATH, how="left")
        .select(*EXPECTED_SCHEMA)
        .sort("sample", "cycle")
    )
