"""How much of each assembly RepeatMasker masked, from the header of its ``.tbl``.

One row per assembly: sequences, length with and without runs of N, GC level
and the bases masked, with the interspersed share and the main class shares
read off the body of the same table, so a card or a scatter needs no join.
The parsing lives in ``depictio.recipes.lib.repeatmasker_tbl``.

Input: every ``*.tbl`` under the run, one line per row, with its path in
``source_path``.

Output schema:
    genome : Utf8                 assembly, from the file name
    sequences : Int64             sequences in the masked FASTA
    total_length : Int64          bases, runs of N included
    length_excl_n : Int64         bases outside runs of N or X
    gc_pct : Float64              GC level, percent
    masked_bp : Int64             bases masked
    masked_pct : Float64          their share, percent
    interspersed_pct : Float64    Total interspersed repeats, percent of the assembly
    retroelements_pct : Float64   Retroelements, percent
    dna_transposons_pct : Float64 DNA transposons, percent
    unclassified_pct : Float64    Unclassified, percent
    simple_repeats_pct : Float64  Simple repeats, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.repeatmasker_tbl import (
    RAW_LINE_COL,
    READ_KWARGS,
    SOURCE_PATH_COL,
    parse_classes,
    parse_summaries,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="tables",
        glob_pattern="**/*.tbl",
        format="csv",
        read_kwargs=READ_KWARGS,
        source_path=SOURCE_PATH_COL,
        input_schema={RAW_LINE_COL: pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "sequences": pl.Int64,
    "total_length": pl.Int64,
    "length_excl_n": pl.Int64,
    "gc_pct": pl.Float64,
    "masked_bp": pl.Int64,
    "masked_pct": pl.Float64,
    "interspersed_pct": pl.Float64,
    "retroelements_pct": pl.Float64,
    "dna_transposons_pct": pl.Float64,
    "unclassified_pct": pl.Float64,
    "simple_repeats_pct": pl.Float64,
}

#: Output column -> the class line it reads, lower-cased.
CLASS_COLUMNS: dict[str, str] = {
    "interspersed_pct": "total interspersed repeats",
    "retroelements_pct": "retroelements",
    "dna_transposons_pct": "dna transposons",
    "unclassified_pct": "unclassified",
    "simple_repeats_pct": "simple repeats",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["tables"]
    summary = parse_summaries(raw)
    if summary.is_empty():
        raise ValueError("repeatmasker_masking_summary: no RepeatMasker table header found")
    classes = parse_classes(raw).filter(pl.col("parent_class").is_null())
    for column, line in CLASS_COLUMNS.items():
        share = classes.filter(pl.col("repeat_class").str.to_lowercase() == line).select(
            "genome", pl.col("genome_pct").alias(column)
        )
        summary = summary.join(share.unique("genome"), on="genome", how="left")
    return summary.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort("genome")
