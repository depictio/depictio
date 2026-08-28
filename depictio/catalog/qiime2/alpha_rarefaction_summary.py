"""Per-sample rarefaction summary: one row per (sample, depth), not per iteration.

``alpha_rarefaction`` is the raw QIIME2 table — sample x depth x iteration —
which for a 85-sample run at 25 depths and 100 iterations is 212 500 rows. Every
figure built on it starts by collapsing the iterations, so each render ships the
whole table to draw a couple of thousand points, and any component that wants to
colour by locality or habitat has nothing to colour by: the raw table carries no
metadata.

This collapses it once, at ingest: the median across iterations (the estimate
the curves are already showing), the spread that median hides, and the sample
metadata joined on. Two orders of magnitude smaller, and groupable.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="rarefaction", dc_ref="alpha_rarefaction"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "depth": pl.Int64,
    "faith_pd": pl.Float64,
}
# Metadata annotation columns are whatever the run's metadata file carries.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_METADATA_ID_COL = "ID"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Collapse the iteration axis, then attach the sample metadata."""
    df = sources["rarefaction"]
    metric_cols = [c for c in df.columns if c not in ("sample", "depth", "iter")]
    if not metric_cols:
        raise ValueError("alpha_rarefaction_summary: no metric column to summarise")

    summary = (
        df.group_by(["sample", "depth"])
        .agg(
            [
                *[pl.col(c).median().alias(c) for c in metric_cols],
                # The interquartile spread of the estimate at this depth — what
                # tells a reader whether a curve's plateau is real or noise.
                *[
                    (pl.col(c).quantile(0.75) - pl.col(c).quantile(0.25)).alias(f"{c}_iqr")
                    for c in metric_cols
                ],
                pl.len().alias("iterations"),
            ]
        )
        .sort(["sample", "depth"])
    )

    metadata = sources.get("metadata")
    if metadata is None or metadata.is_empty():
        return summary
    id_col = (
        _METADATA_ID_COL
        if _METADATA_ID_COL in metadata.columns
        else ("sample" if "sample" in metadata.columns else None)
    )
    if id_col is None:
        return summary
    # Annotations are cast to Utf8: they are grouping keys here, and a numeric
    # column would otherwise arrive as a continuous colour scale.
    annotations = [c for c in metadata.columns if c != id_col and c not in summary.columns]
    if not annotations:
        return summary
    joined = metadata.select(
        [pl.col(id_col).alias("sample"), *[pl.col(c).cast(pl.Utf8) for c in annotations]]
    ).unique(subset=["sample"])
    return summary.join(joined, on="sample", how="left")
