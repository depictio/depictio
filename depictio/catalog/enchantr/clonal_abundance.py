"""Rank-abundance curve per sample with its bootstrap confidence band.

``clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/clonal_abundance.tsv``
is alakazam's ``estimateAbundance`` output: for every sample and every clone, the
bootstrapped relative abundance ``p`` with its standard deviation and the lower
and upper edges of the confidence interval, plus the clone's abundance ``rank``
within the sample.

``clone_sizes_table.tsv`` carries rank and frequency too, but only as point
estimates. What this file adds is the band: two repertoires whose head clones
look equally expanded separate as soon as the intervals are drawn, because the
interval width is set by how many sequences back the estimate.

The raw table is one row per clone (238 651 rows on the 5.1.0 megatest), far
more than a curve needs and more than a ``profile`` tile may hold. The recipe
decimates each sample onto a log-spaced rank grid, which is the axis a
rank-abundance curve is read on: every rank up to ``_HEAD_RANKS`` is kept so the
head of the distribution stays exact, and the tail is thinned to at most
``MAX_POINTS`` points per sample.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="abundance",
        path=(
            "clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/"
            "clonal_abundance.tsv"
        ),
        format="TSV",
        # `lower` is an integer 0 for the first few thousand clones and a float
        # afterwards, so an inferred schema picks Int64 and the read fails part
        # way through the file. Read everything as text and cast explicitly.
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "clone_id": pl.Utf8,
    "rank": pl.Int64,
    "p": pl.Float64,
    "p_sd": pl.Float64,
    "lower": pl.Float64,
    "upper": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# A `profile` series is never sampled downstream, so the recipe owns the budget.
MAX_POINTS = 200
# Ranks kept in full, before the log-spaced thinning starts. The head is where
# clonal expansion is read, so it must not be interpolated away.
_HEAD_RANKS = 20


def _subject(df: pl.DataFrame) -> pl.Expr:
    """The clone-definition group. A report without one gets a single group."""
    if "subject_id" in df.columns:
        return pl.col("subject_id").cast(pl.Utf8)
    return pl.lit("all", dtype=pl.Utf8).alias("subject_id")


def _decimate(df: pl.DataFrame) -> pl.DataFrame:
    """Keep the head of every sample's curve and log-thin its tail."""
    # log10(rank) bucketed into MAX_POINTS - _HEAD_RANKS levels over the sample's
    # own rank range: one representative clone per bucket, the first one in it.
    tail_budget = max(MAX_POINTS - _HEAD_RANKS, 1)
    max_rank = pl.col("rank").max().over("sample_id").cast(pl.Float64)
    bucket = (
        (
            pl.col("rank").cast(pl.Float64).log10()
            / pl.max_horizontal(max_rank.log10(), pl.lit(1e-9))
            * tail_budget
        )
        .floor()
        .cast(pl.Int64)
    )
    ranked_in_bucket = pl.col("rank").rank("ordinal").over(["sample_id", "_bucket"])
    return (
        df.with_columns(bucket.alias("_bucket"))
        .filter((pl.col("rank") <= _HEAD_RANKS) | (ranked_in_bucket == 1))
        .drop("_bucket")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Cast the abundance curve to a stable schema and thin it to a plottable size."""
    df = sources["abundance"]
    out = df.select(
        pl.col("sample_id").cast(pl.Utf8),
        _subject(df),
        pl.col("clone_id").cast(pl.Utf8),
        pl.col("rank").cast(pl.Int64),
        pl.col("p").cast(pl.Float64),
        pl.col("p_sd").cast(pl.Float64),
        pl.col("lower").cast(pl.Float64),
        pl.col("upper").cast(pl.Float64),
    ).sort(["sample_id", "rank"])
    return _decimate(out).sort(["sample_id", "rank"])
