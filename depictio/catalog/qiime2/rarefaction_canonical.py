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
    + passthrough metadata/annotation columns as Utf8 (locality, platform, ...)

Input source CSVs come in wide rarefaction form:
    sample-id, depth-1_iter-1, depth-1_iter-2, ..., depth-N_iter-M
Each cell is the alpha-diversity value at that depth × iteration. The recipe
unpivots the per-iteration columns to long, parses depth and iter from the
column names, then pivots the metric_name back to wide so each metric becomes
its own column.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# File-based sources: the three QIIME2 CSVs are read straight from the run
# directory. They used to be `dc_ref`s to intermediate DCs that no template
# ever declared, which made this recipe seed-only — every fresh ingestion
# skipped the DC and the rarefaction advanced viz with it.
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="shannon", path="qiime2/alpha-rarefaction/shannon.csv", format="CSV"),
    RecipeSource(
        ref="observed_features",
        path="qiime2/alpha-rarefaction/observed_features.csv",
        format="CSV",
    ),
    RecipeSource(ref="faith_pd", path="qiime2/alpha-rarefaction/faith_pd.csv", format="CSV"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "depth": pl.Int64,
    "iter": pl.Int64,
    # The three metric sources are required (non-optional RecipeSources) and the
    # transform unconditionally unpivots all three, so these columns are always
    # produced — guaranteed enough for an advanced_viz `metric` role to bind.
    "shannon": pl.Float64,
    "observed_features": pl.Float64,
    "faith_pd": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    # Passthrough metadata columns (locality, platform, ...) are extra and
    # allowed; nothing beyond the metrics is guaranteed.
}

_METADATA_ID_COL = "ID"


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
    return (
        parsed.rename({sample_col: "sample_id"})
        .select("sample_id", "depth", "iter", metric_name)
        # observed_features arrives as Int64 from pl.read_csv; the canonical
        # schema (and the renderer) want one numeric dtype across metrics.
        .with_columns(pl.col(metric_name).cast(pl.Float64, strict=False))
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

    # Group/annotation columns, so the advanced viz's `group_col: '{GROUP_COL}'`
    # (a literal metadata column name, e.g. `locality`) can bind. Two homes:
    # a `--metadata` run appends the metadata columns to the rarefaction CSVs
    # themselves (everything after the depth-*_iter-* block); otherwise fall
    # back to joining the metadata DC. Either way the columns are cast to Utf8
    # so the renderer's numeric-column metric auto-discovery never mistakes an
    # annotation for a metric.
    first = sources["shannon"]
    sample_col = first.columns[0]
    trailing = [c for c in first.columns if c != sample_col and not c.startswith("depth-")]
    if trailing:
        anno = (
            first.select([sample_col, *trailing])
            .unique(subset=[sample_col])
            .rename({sample_col: "sample_id"})
            .with_columns([pl.col(c).cast(pl.Utf8, strict=False) for c in trailing])
        )
        df = df.join(anno, on="sample_id", how="left")
    else:
        metadata = sources.get("metadata")
        if metadata is not None:
            sample_id_col = next(
                (c for c in (_METADATA_ID_COL, "sample") if c in metadata.columns), None
            )
            if sample_id_col is not None:
                meta_cols = [c for c in metadata.columns if c != sample_id_col]
                meta_slim = (
                    metadata.unique(subset=[sample_id_col])
                    .rename({sample_id_col: "sample_id"})
                    .with_columns([pl.col(c).cast(pl.Utf8, strict=False) for c in meta_cols])
                )
                df = df.join(meta_slim, on="sample_id", how="left")

    core = ["sample_id", "depth", "iter", "shannon", "observed_features", "faith_pd"]
    rest = [c for c in df.columns if c not in core]
    return df.select(core + rest).sort("sample_id", "depth", "iter")
