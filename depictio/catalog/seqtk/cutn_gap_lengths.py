"""Length distribution of the assembly gaps of each genome (``seqtk cutN`` BED).

Scaffolding gaps come in characteristic sizes: an assembler that joins contigs
with unsized links writes a fixed run of N (often 100 bp), optical or Hi-C
scaffolding writes estimated sizes, and a reference assembly keeps the large
centromere and heterochromatin placeholders. The gap length profile of a genome
therefore tells how it was scaffolded, which the gap count alone does not.

Lengths are binned on a log10 scale (four bins per decade, from 1 bp) and each
genome becomes one curve of gap counts per bin, which keeps a genome with a
hundred thousand gaps at a few dozen points. ``gap_length_bp`` is the lower
edge of the bin. ``gaps_pct`` is the share of the genome's runs of N that fall
in the bin, so genomes with a handful and with a hundred thousand gaps compare
on one colour scale: a fixed filler length shows as one bin near 100 percent.
The genome id comes from the file name (``cutn/<genome>.bed``).

Output columns:
    genome, gap_length_bp, log10_gap_length, gaps, gaps_pct, gap_bp
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

BINS_PER_DECADE = 4
_SOURCE_PATH = "_source_path"
_SUFFIX = ".bed"

# Same source as ``seqtk/cutn_gaps.py``: every poly-N BED of the run.
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="gaps",
        glob_pattern="cutn/*.bed",
        format="TSV",
        source_path=_SOURCE_PATH,
        # No renaming at read time: an empty BED (a genome without gaps) has no
        # columns to rename. Polars names them column_1, column_2, column_3.
        read_kwargs={
            "has_header": False,
            "infer_schema_length": 0,
            "quote_char": None,
            "comment_prefix": "#",
            "raise_if_empty": False,
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "gap_length_bp": pl.Int64,
    "log10_gap_length": pl.Float64,
    "gaps": pl.Int64,
    "gaps_pct": pl.Float64,
    "gap_bp": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    gaps = (
        sources["gaps"]
        .with_columns(
            pl.col(_SOURCE_PATH)
            .str.split("/")
            .list.last()
            .str.strip_suffix(_SUFFIX)
            .alias("genome"),
            (
                pl.col("column_3").cast(pl.Int64, strict=False)
                - pl.col("column_2").cast(pl.Int64, strict=False)
            ).alias("length"),
        )
        .filter(pl.col("length").is_not_null() & (pl.col("length") > 0))
    )
    binned = gaps.with_columns(
        (pl.col("length").cast(pl.Float64).log10() * BINS_PER_DECADE)
        .floor()
        .truediv(BINS_PER_DECADE)
        .round(4)
        .alias("log10_gap_length")
    )
    out = binned.group_by("genome", "log10_gap_length").agg(
        pl.len().cast(pl.Int64).alias("gaps"),
        pl.col("length").sum().cast(pl.Int64).alias("gap_bp"),
    )
    out = out.with_columns(
        (pl.lit(10.0).pow(pl.col("log10_gap_length")))
        .round(0)
        .cast(pl.Int64)
        .alias("gap_length_bp"),
        (pl.col("gaps") * 100.0 / pl.col("gaps").sum().over("genome")).round(3).alias("gaps_pct"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort("genome", "log10_gap_length")
