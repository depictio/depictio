"""Which profilers detected which taxon, as an UpSet membership matrix.

One row per (sample, taxon), one 0/1 column per profiler. The intersections answer the
question a multi-profiler run exists to ask: how much of the community every classifier
agrees on, and how large each profiler's private tail is.

Rows are kept per sample rather than pooled so a dashboard sample filter narrows the
UpSet to one community; pooling would blur three mock communities into one set.

Output: sample, taxonomy_id, taxon, rank, n_profilers, one Int64 0/1 column per profiler.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="profiles", dc_ref="taxpasta_profiles"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "taxonomy_id": pl.Utf8,
    "taxon": pl.Utf8,
    "rank": pl.Utf8,
    "n_profilers": pl.Int64,
}

# One 0/1 column per profiler; the names are run-dependent, so they are not declared.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot detections into a per-profiler binary membership matrix."""
    long = sources["profiles"]
    missing = {"sample", "profiler", "taxonomy_id", "name", "rank"} - set(long.columns)
    if missing:
        raise ValueError(f"taxpasta presence: profiles is missing {sorted(missing)}")

    detections = (
        long.filter(pl.col("count") > 0)
        .group_by(["sample", "taxonomy_id", "profiler"])
        .agg(pl.col("name").first().alias("taxon"), pl.col("rank").first().alias("rank"))
        .with_columns(pl.lit(1, dtype=pl.Int64).alias("detected"))
    )

    profilers = sorted(detections["profiler"].unique().to_list())
    if len(profilers) < 2:
        raise ValueError("taxpasta presence: an UpSet needs at least 2 profilers")

    labels = (
        detections.group_by(["sample", "taxonomy_id"])
        .agg(pl.col("taxon").first().alias("taxon"), pl.col("rank").first().alias("rank"))
        .with_columns(pl.col("rank").fill_null("unknown"))
    )

    matrix = (
        detections.pivot(
            values="detected",
            index=["sample", "taxonomy_id"],
            on="profiler",
            aggregate_function="max",
        )
        .fill_null(0)
        .with_columns(pl.col(p).cast(pl.Int64) for p in profilers)
    )

    return (
        matrix.join(labels, on=["sample", "taxonomy_id"], how="left")
        .with_columns(pl.sum_horizontal(profilers).cast(pl.Int64).alias("n_profilers"))
        .select(["sample", "taxonomy_id", "taxon", "rank", "n_profilers", *profilers])
        .sort(["sample", "n_profilers", "taxon"], descending=[False, True, False])
    )
