"""Per-sample multi-metric alpha-diversity DC for ampliseq.

Joins the four QIIME2 per-sample alpha-diversity vector TSVs (shannon,
observed_features, faith_pd, evenness) into a single wide DataFrame keyed by
sample id. Used by the regular Plotly boxplot-by-habitat tile on the new
Alpha Diversity tab.

Output schema:
    sample_id : Utf8
    habitat : Utf8
    shannon : Float64
    observed_features : Float64
    faith_pd : Float64
    evenness : Float64

Source TSVs (QIIME2 metadata.tsv shape, with the leading ``#q2:types`` row
skipped by the generator script):
    id, habitat, Riv_vs_Gro, Sed_vs_Soil, <metric_col>
where <metric_col> is one of ``shannon_entropy``, ``observed_features``,
``faith_pd``, ``pielou_evenness``.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="shannon", dc_ref="alpha_diversity_shannon"),
    RecipeSource(ref="observed_features", dc_ref="alpha_diversity_observed_features"),
    RecipeSource(ref="faith_pd", dc_ref="alpha_diversity_faith_pd"),
    RecipeSource(ref="evenness", dc_ref="alpha_diversity_evenness"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "habitat": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "shannon": pl.Float64,
    "observed_features": pl.Float64,
    "faith_pd": pl.Float64,
    "evenness": pl.Float64,
}

_METRIC_RENAMES = {
    "shannon_entropy": "shannon",
    "observed_features": "observed_features",
    "faith_pd": "faith_pd",
    "pielou_evenness": "evenness",
}


def _slim(df: pl.DataFrame) -> pl.DataFrame:
    """Keep id + habitat + the single metric column, renamed canonically."""
    metric_col = next((c for c in df.columns if c in _METRIC_RENAMES), None)
    if metric_col is None:
        raise ValueError(
            f"alpha_diversity_multi: expected one of {list(_METRIC_RENAMES)} in {df.columns}"
        )
    return (
        df.select("id", "habitat", metric_col)
        .rename({"id": "sample_id", metric_col: _METRIC_RENAMES[metric_col]})
        .with_columns(
            pl.col("sample_id").cast(pl.Utf8),
            pl.col("habitat").cast(pl.Utf8),
            pl.col(_METRIC_RENAMES[metric_col]).cast(pl.Float64, strict=False),
        )
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join 4 per-sample alpha-diversity vectors into a single wide DataFrame."""
    pieces = [_slim(sources[k]) for k in ("shannon", "observed_features", "faith_pd", "evenness")]
    df = pieces[0]
    for piece in pieces[1:]:
        # habitat is duplicated across sources — drop it from the right side.
        df = df.join(piece.drop("habitat"), on="sample_id", how="full", coalesce=True)
    return df.sort("sample_id")
