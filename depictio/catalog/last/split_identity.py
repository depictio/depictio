"""One row per pairwise genome alignment from LAST's one-to-one summary (``*.o2o.tsv``).

``last-split`` reduces the many-to-one alignment of a query genome onto the
target to a one-to-one alignment and writes a one-line summary for MultiQC:
the aligned length, the percent identity with and without gap columns, and the
number and total length of the sequences of both genomes. This recipe keeps
those numbers under stable names and adds the two ratios a reader compares
genomes by: the share of each genome's length the one-to-one alignment covers.
Coverage of the target falls with divergence time and with assembly gaps in the
query, identity falls with divergence only, so the two together separate a
distant genome from a fragmented one.

The pair id ``<target>___<query>`` is split into ``target`` and ``query``;
``query`` is the samplesheet sample and the key the other collections join on.

Output columns:
    pair, target, query, aligned_bp, percent_identity, percent_identity_no_gaps,
    target_sequences, target_length, query_sequences, query_length,
    target_aligned_pct, query_aligned_pct
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.genome_pairs import split_pair

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="identity",
        glob_pattern="alignment/*.o2o.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "pair": pl.Utf8,
    "target": pl.Utf8,
    "query": pl.Utf8,
    "aligned_bp": pl.Int64,
    "percent_identity": pl.Float64,
    "percent_identity_no_gaps": pl.Float64,
    "target_sequences": pl.Int64,
    "target_length": pl.Int64,
    "query_sequences": pl.Int64,
    "query_length": pl.Int64,
    "target_aligned_pct": pl.Float64,
    "query_aligned_pct": pl.Float64,
}

_INTS = {
    "TotalAlignmentLength": "aligned_bp",
    "TargetSequences": "target_sequences",
    "TargetLength": "target_length",
    "QuerySequences": "query_sequences",
    "QueryLength": "query_length",
}
_FLOATS = {
    "PercentIdentity": "percent_identity",
    "PercentIdentityNoGaps": "percent_identity_no_gaps",
}


def _pct(num: str, den: str) -> pl.Expr:
    return (
        pl.when(pl.col(den) > 0)
        .then(pl.col(num).cast(pl.Float64) / pl.col(den).cast(pl.Float64) * 100.0)
        .otherwise(None)
        .round(3)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["identity"]
    df = df.select(
        *split_pair(pl.col("Sample").cast(pl.Utf8).str.strip_chars()),
        *[pl.col(src).cast(pl.Int64, strict=False).alias(dst) for src, dst in _INTS.items()],
        *[
            pl.col(src).cast(pl.Float64, strict=False).round(3).alias(dst)
            for src, dst in _FLOATS.items()
        ],
    )
    df = df.with_columns(
        _pct("aligned_bp", "target_length").alias("target_aligned_pct"),
        _pct("aligned_bp", "query_length").alias("query_aligned_pct"),
    )
    return df.select(list(EXPECTED_SCHEMA)).unique("pair", keep="first").sort("query")
