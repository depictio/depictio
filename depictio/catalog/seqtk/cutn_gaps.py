"""Assembly gaps per genome, from the poly-N regions ``seqtk cutN`` reports.

``seqtk cutN -g`` lists every run of N in an assembly as a 3-column BED
(sequence, start, end). Runs of N are the scaffolding gaps an assembler left
between contigs, so their number and total length say how finished an assembly
is: a telomere-to-telomere assembly has none, a short-read scaffold assembly has
thousands. They matter for a genome alignment because a gap cannot align, so
it lowers how much of the genome the alignment covers without saying anything
about divergence.

The BED names no genome, so the genome id comes from the file name
(``cutn/<genome>.bed``). An empty BED is a genome without gaps; the glob reader
drops empty files, so such a genome has no row here and the consumers read its
absence as zero gaps.

Output columns:
    genome, gaps, gap_bp, sequences_with_gaps, median_gap_bp, max_gap_bp
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_SOURCE_PATH = "_source_path"
_SUFFIX = ".bed"

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
    "gaps": pl.Int64,
    "gap_bp": pl.Int64,
    "sequences_with_gaps": pl.Int64,
    "median_gap_bp": pl.Float64,
    "max_gap_bp": pl.Int64,
}


def gap_lengths(df: pl.DataFrame) -> pl.DataFrame:
    """``genome``, ``chrom`` and ``length`` per gap, shared with the length profile."""
    return (
        df.with_columns(
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
        .select("genome", pl.col("column_1").alias("chrom"), "length")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    gaps = gap_lengths(sources["gaps"])
    out = gaps.group_by("genome").agg(
        pl.len().cast(pl.Int64).alias("gaps"),
        pl.col("length").sum().cast(pl.Int64).alias("gap_bp"),
        pl.col("chrom").n_unique().cast(pl.Int64).alias("sequences_with_gaps"),
        pl.col("length").median().cast(pl.Float64).alias("median_gap_bp"),
        pl.col("length").max().cast(pl.Int64).alias("max_gap_bp"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort("genome")
