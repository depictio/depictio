"""Fragment-length distribution of a mapped library, from DamageProfiler.

``lgdistribution.txt`` is DamageProfiler's read-length table: four ``#`` comment
lines, then a real header and one row per (strand, length)::

    # table produced by calculations.DamageProfiler
    # using mapped file COD076E1bL1_rmdup.bam
    # Sample ID: COD076E1bL1_rmdup.bam
    # Std: strand of reads
    Std   Length  Occurrences
    +     30      103467
    +     31      115882

Fragment length is the second authenticity signal after the misincorporation
profile: ancient DNA is fragmented by depurination and rarely survives past
~100 bp, so an extract whose length distribution looks like a modern library's
is a contamination flag even when the damage curve looks acceptable.

The forward and reverse strands are kept as separate rows because DamageProfiler
reports them separately and a strand asymmetry is itself informative, and a
``series`` column pairing library and strand is derived so the ``profile`` kind
can draw one curve per (library, strand) without a composite binding.

The sample is recovered from the table's parent directory
(``<library>_rmdup/``), not from the ``Sample ID`` comment, which quotes the BAM
file name including the dedupper's suffix.

Input: a data collection scanning the tables as the TSV they are, with the
comment lines skipped::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*lgdistribution\\.txt$'}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          comment_prefix: "#"
          include_file_paths: "source_path"

Output schema:
    sample : Utf8        library DamageProfiler ran on
    strand : Utf8        + or -, the strand the reads mapped to
    series : Utf8        "<sample> (<strand>)", one curve of the profile
    length : Int64       fragment length, bp
    occurrences : Int64  reads of that length on that strand
    fraction : Float64   share of that (sample, strand)'s reads, 0-1
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan the tables into.
RAW_DC_TAG = "damageprofiler_lgdistribution_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lengths", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "strand": pl.Utf8,
    "series": pl.Utf8,
    "length": pl.Int64,
    "occurrences": pl.Int64,
    "fraction": pl.Float64,
}

SOURCE_PATH_COL = "source_path"

#: Trailing underscore-separated tokens of the per-sample directory that name
#: the dedupper stage rather than the library.
_STAGE_TOKENS = frozenset({"rmdup", "dedup", "sorted", "markdup"})


def _sample_from_dir(source_path: str) -> str:
    tokens = Path(str(source_path)).parent.name.split("_")
    while len(tokens) > 1 and tokens[-1].lower() in _STAGE_TOKENS:
        tokens.pop()
    return "_".join(tokens)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, strand, fragment length)."""
    raw = sources["lengths"]
    if raw.is_empty():
        raise ValueError("damageprofiler_lgdistribution: the scanned tables are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "damageprofiler_lgdistribution: no source_path column, the data "
            "collection must scan with include_file_paths: source_path"
        )
    missing = {"Std", "Length", "Occurrences"} - set(raw.columns)
    if missing:
        raise ValueError(f"damageprofiler_lgdistribution: missing columns {sorted(missing)}")

    frame = (
        raw.select(
            pl.col(SOURCE_PATH_COL)
            .map_elements(_sample_from_dir, return_dtype=pl.Utf8)
            .alias("sample"),
            pl.col("Std").cast(pl.Utf8).str.strip_chars().alias("strand"),
            pl.col("Length")
            .cast(pl.Float64, strict=False)
            .cast(pl.Int64, strict=False)
            .alias("length"),
            pl.col("Occurrences")
            .cast(pl.Float64, strict=False)
            .cast(pl.Int64, strict=False)
            .alias("occurrences"),
        )
        .drop_nulls(["length", "occurrences"])
        .filter(pl.col("strand").is_not_null())
    )
    if frame.is_empty():
        raise ValueError("damageprofiler_lgdistribution: no row carried a length and a count")

    total = pl.col("occurrences").sum().over(["sample", "strand"])
    return (
        frame.with_columns(
            pl.format("{} ({})", pl.col("sample"), pl.col("strand")).alias("series"),
            pl.when(total > 0)
            .then(pl.col("occurrences") / total)
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("fraction"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "strand", "length"])
    )
