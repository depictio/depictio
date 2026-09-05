"""Bray-Curtis PCoA over every profiling run in the taxpasta collection.

One point per (sample, profiler, database): profiling runs that agree on what the
community contains land close together, so the ordination reads as a concordance map
rather than as a sample map. Colouring by profiler and using the platform as the point
symbol separates the two axes of disagreement the taxprofiler mock design isolates.

Distances come from ``depictio.recipes.lib.dimreduction.run_pcoa`` on the run x taxon
relative-abundance matrix.

Output: sample_id, dim_1, dim_2, sample, profiler, database, profiler_db, platform.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.dimreduction import run_pcoa

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="profiles", dc_ref="taxpasta_profiles"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "sample": pl.Utf8,
    "profiler": pl.Utf8,
    "database": pl.Utf8,
    "profiler_db": pl.Utf8,
    "platform": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot to run x taxon, then run PCoA on the Bray-Curtis distances."""
    long = sources["profiles"]
    missing = {"sample", "profiler", "database", "profiler_db", "platform", "rel_abundance"} - set(
        long.columns
    )
    if missing:
        raise ValueError(f"taxpasta embedding: profiles is missing {sorted(missing)}")

    tagged = long.with_columns(
        pl.format("{} | {}", pl.col("sample"), pl.col("profiler_db")).alias("sample_id")
    )

    wide = (
        tagged.group_by(["sample_id", "taxonomy_id"])
        .agg(pl.col("rel_abundance").sum().alias("rel_abundance"))
        .pivot(
            values="rel_abundance",
            index="sample_id",
            on="taxonomy_id",
            aggregate_function="sum",
        )
        .fill_null(0.0)
        .sort("sample_id")
    )
    if wide.height < 3:
        raise ValueError(
            f"taxpasta embedding: PCoA needs at least 3 profiling runs, got {wide.height}"
        )

    coords = run_pcoa(wide, n_components=2)

    annotations = tagged.select(
        "sample_id", "sample", "profiler", "database", "profiler_db", "platform"
    ).unique(subset=["sample_id"])

    return (
        coords.join(annotations, on="sample_id", how="left")
        .select(
            "sample_id",
            "dim_1",
            "dim_2",
            "sample",
            "profiler",
            "database",
            "profiler_db",
            "platform",
        )
        .sort("sample_id")
    )
