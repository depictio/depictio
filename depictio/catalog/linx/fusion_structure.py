"""LINX fusions as two partner lanes along the fused transcript, in exon units.

Reads ``linx_fusions`` and lays each fusion out the way the ``fusion_structure``
kind draws one: a lane per partner, one bar per exon span, the breakpoint
between them. LINX publishes no amino-acid domain coordinates per fusion, so
the axis is the exon rank along the fused transcript:

* the 5' partner keeps exons ``1..U`` (``U`` = ``fused_exon_up``), drawn from
  0 to ``U``, and loses ``U+1..N5``, drawn after the breakpoint as not retained;
* the 3' partner keeps exons ``D..N3`` (``D`` = ``fused_exon_down``), drawn
  from ``U`` onwards, and loses ``1..D-1``, drawn before the breakpoint as not
  retained;
* ``breakpoint`` is ``U`` for every row of the fusion.

``retained`` is 1 for a kept span and 0 for a lost one, which the kind renders
as a solid or a hollow bar. fusion is the facet title: the partner pair, numbered when one tumor has
the same pair twice and suffixed with the tumor when the run has several. Row
order follows ``linx_fusions`` (reported first,
then in-frame), which is the order the facets are drawn in.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="fusions", dc_ref="linx_fusions")]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "fusion_id": pl.Utf8,
    "fusion": pl.Utf8,
    "sample": pl.Utf8,
    "partner": pl.Utf8,
    "feature": pl.Utf8,
    "start": pl.Float64,
    "end": pl.Float64,
    "retained": pl.Float64,
    "breakpoint": pl.Float64,
    "phased": pl.Utf8,
    "reported": pl.Boolean,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def _span(
    df: pl.DataFrame, partner: pl.Expr, first: pl.Expr, last: pl.Expr, x0: pl.Expr, kept: bool
) -> pl.DataFrame:
    n = last - first + 1
    return df.filter(n > 0).select(
        "fusion_id",
        "fusion",
        "sample",
        partner.alias("partner"),
        pl.format("exons {}-{} {}", first, last, pl.lit("kept" if kept else "lost")).alias(
            "feature"
        ),
        x0.cast(pl.Float64).alias("start"),
        (x0 + n).cast(pl.Float64).alias("end"),
        pl.lit(1.0 if kept else 0.0).alias("retained"),
        pl.col("fused_exon_up").cast(pl.Float64).alias("breakpoint"),
        "phased",
        "reported",
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = (
        sources["fusions"]
        .filter(pl.col("fused_exon_up").is_not_null() & pl.col("fused_exon_down").is_not_null())
        .with_row_index("_order")
    )
    # Facet title: the partner pair, numbered when a tumor has it twice, and
    # suffixed with the tumor only when the run has several.
    nth = pl.col("_order").rank("ordinal").over(["sample", "fusion"]).cast(pl.Utf8)
    repeated = pl.len().over(["sample", "fusion"]) > 1
    label = (
        pl.when(repeated)
        .then(pl.format("{} #{}", pl.col("fusion"), nth))
        .otherwise(pl.col("fusion"))
    )
    if df["sample"].n_unique() > 1:
        label = pl.format("{} ({})", label, pl.col("sample"))
    df = df.with_columns(label.alias("fusion"))
    up_name = pl.concat_str([pl.lit("5' "), pl.col("gene_up")])
    down_name = pl.concat_str([pl.lit("3' "), pl.col("gene_down")])
    u, d = pl.col("fused_exon_up"), pl.col("fused_exon_down")
    n5 = pl.coalesce(pl.col("exons_up_total"), u)
    n3 = pl.coalesce(pl.col("exons_down_total"), d)
    parts = [
        _span(df, up_name, pl.lit(1), u, pl.lit(0), kept=True),
        _span(df, up_name, u + 1, n5, u, kept=False),
        _span(df, down_name, pl.lit(1), d - 1, u - (d - 1), kept=False),
        _span(df, down_name, d, n3, u, kept=True),
    ]
    order = df.select("fusion_id", "_order")
    return (
        pl.concat(parts, how="vertical_relaxed")
        .join(order, on="fusion_id", how="left")
        .sort(["_order", "partner", "start"], descending=[False, True, False])
        .drop("_order")
        .select(list(EXPECTED_SCHEMA))
    )
