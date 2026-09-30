"""Spots per cluster of every sample, per clustering, as counts and shares.

Reads the normalised spots table (``spatialdata/visium_spots``, under the
``spatialdata_visium_spots`` data-collection tag) and counts spots per sample
and cluster twice: for the per-sample Leiden clustering (``cluster``) and, when
integration ran, for the integrated one (``cluster_integrated``). Per-sample
cluster labels are not comparable across samples (each sample is clustered on
its own); integrated labels are.

The twelve largest clusters of each clustering over the run keep their label,
the rest are pooled as ``Other``, so a stacked bar stays readable.

Output schema:
    sample : Utf8       sample id
    clustering : Utf8   "per sample" | "integrated"
    cluster : Utf8      cluster label, or Other
    n_spots : Int64     spots of the sample in the cluster
    pct_spots : Float64 share of the sample's spots, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SPOTS_DC_TAG = "spatialdata_visium_spots"

SOURCES: list[RecipeSource] = [RecipeSource(ref="spots", dc_ref=SPOTS_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "clustering": pl.Utf8,
    "cluster": pl.Utf8,
    "n_spots": pl.Int64,
    "pct_spots": pl.Float64,
}

TOP_N = 12
_CLUSTERINGS = {"cluster": "per sample", "cluster_integrated": "integrated"}


def _one(spots: pl.DataFrame, column: str, label: str) -> pl.DataFrame | None:
    if column not in spots.columns:
        return None
    rows = spots.filter(pl.col(column).is_not_null())
    if rows.is_empty():
        return None
    top = (
        rows.group_by(column)
        .agg(pl.len().alias("_n"))
        .sort(["_n", column], descending=[True, False])
        .head(TOP_N)[column]
        .cast(pl.Utf8)
        .to_list()
    )
    labelled = rows.with_columns(
        pl.when(pl.col(column).cast(pl.Utf8).is_in(top))
        .then(pl.col(column).cast(pl.Utf8))
        .otherwise(pl.lit("Other"))
        .alias("cluster_label")
    )
    counts = labelled.group_by(["sample", "cluster_label"]).agg(
        pl.len().cast(pl.Int64).alias("n_spots")
    )
    return counts.with_columns(
        pl.lit(label).alias("clustering"),
        (pl.col("n_spots") / pl.col("n_spots").sum().over("sample") * 100)
        .cast(pl.Float64)
        .alias("pct_spots"),
    ).rename({"cluster_label": "cluster"})


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    spots = sources["spots"]
    parts = [p for c, lab in _CLUSTERINGS.items() if (p := _one(spots, c, lab)) is not None]
    if not parts:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    out = pl.concat([p.select(list(EXPECTED_SCHEMA)) for p in parts])
    return out.sort(["clustering", "sample", "n_spots"], descending=[False, False, True])
