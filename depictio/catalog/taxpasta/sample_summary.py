"""One row per profiling run: how much each profiler found, and how evenly.

Collapses the long taxpasta collection into per (sample, profiler, database) statistics
that make profilers directly comparable: how many taxa were reported, how many reads
were assigned, how concentrated the profile is on its top hit, and Shannon diversity
with Pielou evenness. A profiler that reports a long tail of low-count taxa and one that
reports a handful of dominant ones separate immediately on these four numbers.

Output: sample, profiler, database, profiler_db, platform, taxa_observed,
assigned_count, top_taxon, top_taxon_fraction, shannon, evenness.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="profiles", dc_ref="taxpasta_profiles"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "profiler": pl.Utf8,
    "database": pl.Utf8,
    "profiler_db": pl.Utf8,
    "platform": pl.Utf8,
    "taxa_observed": pl.Int64,
    "assigned_count": pl.Float64,
    "top_taxon": pl.Utf8,
    "top_taxon_fraction": pl.Float64,
    "shannon": pl.Float64,
    "evenness": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_GROUP = ["sample", "profiler", "database", "profiler_db", "platform"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Aggregate the long profiles into per-run richness and diversity statistics."""
    long = sources["profiles"]
    missing = {*_GROUP, "name", "count", "rel_abundance"} - set(long.columns)
    if missing:
        raise ValueError(f"taxpasta sample summary: profiles is missing {sorted(missing)}")

    positive = long.filter(pl.col("rel_abundance") > 0)
    if positive.is_empty():
        raise ValueError("taxpasta sample summary: no positive abundances to summarise")

    summary = positive.group_by(_GROUP).agg(
        pl.len().cast(pl.Int64).alias("taxa_observed"),
        pl.col("count").sum().cast(pl.Float64).alias("assigned_count"),
        pl.col("name").sort_by("rel_abundance", descending=True).first().alias("top_taxon"),
        pl.col("rel_abundance").max().cast(pl.Float64).alias("top_taxon_fraction"),
        (-(pl.col("rel_abundance") * pl.col("rel_abundance").log()).sum())
        .cast(pl.Float64)
        .alias("shannon"),
    )

    return (
        summary.with_columns(
            pl.when(pl.col("taxa_observed") > 1)
            .then(pl.col("shannon") / pl.col("taxa_observed").cast(pl.Float64).log())
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("evenness")
        )
        .select(
            *_GROUP,
            "taxa_observed",
            "assigned_count",
            "top_taxon",
            "top_taxon_fraction",
            "shannon",
            "evenness",
        )
        .sort(["sample", "profiler", "database"])
    )
