"""Canonical-schema Sankey DC for viralrecon lineage / clade typing.

Joins the existing ``pangolin_lineages`` and ``nextclade_results`` DCs on
sample and exposes the typing funnel as ordered categorical columns:

    qc_status -> lineage -> clade

Each row represents one sample's classification chain; the Sankey renderer
aggregates by ``step_cols`` and builds the node/link payload at compute time.
Schema for ``sankey`` is permissive (no required role columns); ``step_cols``
is validated at compute time and via the Pydantic config's ``min_length=2``.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="pangolin", dc_ref="pangolin_lineages"),
    RecipeSource(ref="nextclade", dc_ref="nextclade_results"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "qc_status": pl.Utf8,
    "lineage": pl.Utf8,
    "clade": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join Pangolin + Nextclade on sample, expose qc_status/lineage/clade."""
    pangolin = sources["pangolin"]
    nextclade = sources["nextclade"]

    pango_cols = [c for c in ("sample", "lineage", "qc_status") if c in pangolin.columns]
    if "sample" not in pango_cols:
        raise ValueError("viralrecon sankey: pangolin_lineages must expose `sample`")
    pangolin = pangolin.select(pango_cols)

    nc_cols = [c for c in ("sample", "clade") if c in nextclade.columns]
    if "sample" not in nc_cols or "clade" not in nc_cols:
        raise ValueError("viralrecon sankey: nextclade_results must expose `sample` and `clade`")
    nextclade = nextclade.select(nc_cols)

    df = pangolin.join(nextclade, on="sample", how="full", coalesce=True)

    # Fill nulls so every row participates in the flow.
    fill_cols = [c for c in ("qc_status", "lineage", "clade") if c in df.columns]
    if fill_cols:
        df = df.with_columns([pl.col(c).fill_null("Unassigned").cast(pl.Utf8) for c in fill_cols])

    df = df.with_columns(pl.col("sample").cast(pl.Utf8))

    keep = [c for c in ("sample", "qc_status", "lineage", "clade") if c in df.columns]
    return df.select(keep)
