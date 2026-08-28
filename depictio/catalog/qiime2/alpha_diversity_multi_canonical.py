"""Per-sample multi-metric alpha-diversity DC for ampliseq.

Joins the four QIIME2 per-sample alpha-diversity vector TSVs (shannon,
observed_features, faith_pd, evenness) into a single wide DataFrame keyed by
sample id. Used by the regular Plotly boxplot-by-habitat tile on the new
Alpha Diversity tab.

Output schema:
    sample_id : Utf8
    + passthrough sample-metadata columns as Utf8 (locality, habitat, ...)
    shannon : Float64
    observed_features : Float64
    faith_pd : Float64
    evenness : Float64

Source TSVs (QIIME2 metadata.tsv shape; the ``#q2:types`` row after the
header is skipped via read_kwargs):
    id, <sample metadata columns...>, <metric_col>
where <metric_col> is one of ``shannon_entropy``, ``observed_features``,
``faith_pd``, ``pielou_evenness``.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# File-based sources: QIIME2 writes one metadata.tsv per metric vector dir.
# These used to be `dc_ref`s to DCs no template declared (seed-only). The
# second row of each file is QIIME2's `#q2:types` marker — skipping it keeps
# the metric column numeric instead of poisoning dtype inference to String.
_VECTOR_KWARGS = {"skip_rows_after_header": 1}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="shannon",
        path="qiime2/diversity/alpha_diversity/shannon_vector/metadata.tsv",
        format="TSV",
        read_kwargs=_VECTOR_KWARGS,
    ),
    RecipeSource(
        ref="observed_features",
        path="qiime2/diversity/alpha_diversity/observed_features_vector/metadata.tsv",
        format="TSV",
        read_kwargs=_VECTOR_KWARGS,
    ),
    RecipeSource(
        ref="faith_pd",
        path="qiime2/diversity/alpha_diversity/faith_pd_vector/metadata.tsv",
        format="TSV",
        read_kwargs=_VECTOR_KWARGS,
    ),
    RecipeSource(
        ref="evenness",
        path="qiime2/diversity/alpha_diversity/evenness_vector/metadata.tsv",
        format="TSV",
        read_kwargs=_VECTOR_KWARGS,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
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


def _slim(df: pl.DataFrame, keep_annotations: bool) -> pl.DataFrame:
    """Keep id + the single metric column (renamed canonically).

    The first source also keeps every other column — QIIME2 copies the run's
    sample metadata (locality, habitat, platform, ...) into each vector file,
    and downstream components address those columns by their real names
    (``{GROUP_COL}``). Annotations are cast to Utf8 so no metadata column can
    masquerade as a metric.
    """
    metric_col = next((c for c in df.columns if c in _METRIC_RENAMES), None)
    if metric_col is None:
        raise ValueError(
            f"alpha_diversity_multi: expected one of {list(_METRIC_RENAMES)} in {df.columns}"
        )
    anno_cols = [c for c in df.columns if c not in ("id", metric_col)] if keep_annotations else []
    return (
        df.select(["id", *anno_cols, metric_col])
        .rename({"id": "sample_id", metric_col: _METRIC_RENAMES[metric_col]})
        .with_columns(
            pl.col("sample_id").cast(pl.Utf8),
            *[pl.col(c).cast(pl.Utf8, strict=False) for c in anno_cols],
            pl.col(_METRIC_RENAMES[metric_col]).cast(pl.Float64, strict=False),
        )
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join 4 per-sample alpha-diversity vectors into a single wide DataFrame."""
    order = ("shannon", "observed_features", "faith_pd", "evenness")
    pieces = [_slim(sources[k], keep_annotations=(k == order[0])) for k in order]
    df = pieces[0]
    for piece in pieces[1:]:
        # annotations ride only on the first source — later pieces are id+metric.
        df = df.join(piece, on="sample_id", how="full", coalesce=True)
    # Metrics last, annotations in the middle: keeps the table scannable.
    metrics = [
        m for m in ("shannon", "observed_features", "faith_pd", "evenness") if m in df.columns
    ]
    rest = [c for c in df.columns if c != "sample_id" and c not in metrics]
    return df.select(["sample_id", *rest, *metrics]).sort("sample_id")
