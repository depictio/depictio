"""Canonical-schema rarefaction DC for ampliseq (multi-metric).

Combines the three QIIME2 alpha-rarefaction CSVs (shannon, observed_features,
faith_pd) into a single wide-format DataFrame suitable for the React
``RarefactionRenderer`` which switches between metrics via a tab strip.

Output schema (wide):
    sample_id : Utf8
    depth : Int64
    iter : Int64
    shannon : Float64
    observed_features : Float64
    faith_pd : Float64
    group : Utf8 (optional, joined from metadata)

Input source CSVs come in wide rarefaction form:
    sample-id, depth-1_iter-1, depth-1_iter-2, ..., depth-N_iter-M
Each cell is the alpha-diversity value at that depth × iteration. The recipe
unpivots the per-iteration columns to long, parses depth and iter from the
column names, then pivots the metric_name back to wide so each metric becomes
its own column.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="shannon", dc_ref="alpha_rarefaction_shannon"),
    RecipeSource(ref="observed_features", dc_ref="alpha_rarefaction_observed_features"),
    RecipeSource(ref="faith_pd", dc_ref="alpha_rarefaction_faith_pd"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "depth": pl.Int64,
    "iter": pl.Int64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "shannon": pl.Float64,
    "observed_features": pl.Float64,
    "faith_pd": pl.Float64,
    "group": pl.Utf8,
}

_METADATA_ID_COL = "ID"
_PREFERRED_GROUP_COLS = ("habitat",)


def _unpivot_metric(df: pl.DataFrame, metric_name: str) -> pl.DataFrame:
    """Unpivot a QIIME2 rarefaction CSV (wide depth-X_iter-Y cols) → long."""
    sample_col = df.columns[0]
    value_cols = [c for c in df.columns if c.startswith("depth-")]
    long = df.unpivot(
        on=value_cols,
        index=[sample_col],
        variable_name="depth_iter",
        value_name=metric_name,
    )
    parsed = long.with_columns(
        pl.col("depth_iter").str.extract(r"depth-(\d+)_iter-\d+").cast(pl.Int64).alias("depth"),
        pl.col("depth_iter").str.extract(r"depth-\d+_iter-(\d+)").cast(pl.Int64).alias("iter"),
    )
    return parsed.rename({sample_col: "sample_id"}).select(
        "sample_id", "depth", "iter", metric_name
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Merge 3 rarefaction metrics into a single wide DataFrame."""
    pieces = [
        _unpivot_metric(sources["shannon"], "shannon"),
        _unpivot_metric(sources["observed_features"], "observed_features"),
        _unpivot_metric(sources["faith_pd"], "faith_pd"),
    ]
    df = pieces[0]
    for piece in pieces[1:]:
        df = df.join(piece, on=["sample_id", "depth", "iter"], how="full", coalesce=True)
    df = df.with_columns(
        pl.col("sample_id").cast(pl.Utf8),
        pl.col("depth").cast(pl.Int64),
        pl.col("iter").cast(pl.Int64),
    )

    metadata = sources.get("metadata")
    if metadata is not None:
        sample_id_col = next(
            (c for c in (_METADATA_ID_COL, "sample") if c in metadata.columns), None
        )
        group_col = next((c for c in _PREFERRED_GROUP_COLS if c in metadata.columns), None)
        if sample_id_col is not None and group_col is not None:
            meta_slim = (
                metadata.select(sample_id_col, group_col)
                .unique(subset=[sample_id_col])
                .rename({sample_id_col: "sample_id", group_col: "group"})
                .with_columns(pl.col("group").cast(pl.Utf8))
            )
            df = df.join(meta_slim, on="sample_id", how="left")

    keep = [
        c
        for c in (
            "sample_id",
            "depth",
            "iter",
            "shannon",
            "observed_features",
            "faith_pd",
            "group",
        )
        if c in df.columns
    ]
    return df.select(keep).sort("sample_id", "depth", "iter")
