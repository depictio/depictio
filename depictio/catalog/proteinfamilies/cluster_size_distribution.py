"""Initial MMseqs2 cluster size distribution per sample.

Consumes the raw ``proteinfamilies_cluster_distribution_raw`` scan of
``<sample>_clustering_distribution_mqc.csv`` (the pipeline's
CALCULATE_CLUSTER_DISTRIBUTION step): MultiQC custom-content header lines
starting with ``#`` (dropped by the scan's ``comment_prefix``), then
``Id,Cluster Size,Number of Clusters``, every column read as text, the file in
``source_path``. The sample is the file name without the suffix.

``n_sequences`` is the sequences the clusters of that size hold (size times
count) and ``sequence_share`` their share of the sample's clustered
sequences, so the long singleton tail and the few large clusters families are
built from read on the same axis.

Output schema:
    sample : Utf8              sample the clustering ran on
    cluster_size : Int64       members per cluster
    n_clusters : Int64         clusters of that size
    n_sequences : Int64        sequences in clusters of that size
    sequence_share : Float64   share of the sample's sequences, 0-1
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "proteinfamilies_cluster_distribution_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="distribution", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cluster_size": pl.Int64,
    "n_clusters": pl.Int64,
    "n_sequences": pl.Int64,
    "sequence_share": pl.Float64,
}

_SUFFIX = r"_clustering_distribution_mqc\.csv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, cluster size)."""
    raw = sources["distribution"]
    if raw is None or raw.height == 0 or "Cluster Size" not in raw.columns:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    df = (
        raw.select(
            pl.col("source_path")
            .str.replace_all(r"\\", "/")
            .str.extract(r"([^/]+)$", 1)
            .str.replace(_SUFFIX, "")
            .alias("sample"),
            pl.col("Cluster Size").cast(pl.Int64, strict=False).alias("cluster_size"),
            pl.col("Number of Clusters").cast(pl.Int64, strict=False).alias("n_clusters"),
        )
        .drop_nulls(["cluster_size", "n_clusters"])
        .group_by(["sample", "cluster_size"])
        .agg(pl.col("n_clusters").sum())
        .with_columns((pl.col("cluster_size") * pl.col("n_clusters")).alias("n_sequences"))
    )
    return (
        df.with_columns(
            (pl.col("n_sequences") / pl.col("n_sequences").sum().over("sample"))
            .round(3)
            .alias("sequence_share")
        )
        .sort(["sample", "cluster_size"])
        .select(list(EXPECTED_SCHEMA))
        .cast(EXPECTED_SCHEMA)  # type: ignore[arg-type]
    )
