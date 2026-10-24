"""Each chromosome's share of the nascent signal, per time point.

The coarsest reading of the strand coverage: how the library's signal on the
chromosomes splits between them (``bedtools_strand_bins``, both strands, per
million of the library), per time point, libraries of one time point averaged.
A chromosome whose share moves over time carries a large response, or a
hotspot (the ribosomal DNA arrays on the acrocentric chromosomes) whose share
follows how well each library was depleted.

Sources:
    bins     ``bedtools_strand_bins`` (catalog ``bedtools/strand_bins.py``)
    samples  ``samples`` (the sample hub)

Output schema:
    chromosome, time_point : Utf8
    time_h : Float64, time_order : Int64, time_axis : Float64, phase : Utf8
    share_pct : Float64        the chromosome's share of the signal on the chromosomes, in percent
    plus_share_pct : Float64   the plus strand's share of the chromosome's signal, in percent
    contig_order : Int64       chromosome rank in karyotype order, chr1 first
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib import strand_coverage as sc
from depictio.recipes.lib import time_course as tc

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="bins",
        dc_ref="bedtools_strand_bins",
        input_schema={
            "sample": pl.Utf8,
            "chromosome": pl.Utf8,
            "plus_rpm": pl.Float64,
            "signal_rpm": pl.Float64,
        },
    ),
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={
            "sample": pl.Utf8,
            "time_point": pl.Utf8,
            "time_h": pl.Float64,
            "time_order": pl.Int64,
            "time_axis": pl.Float64,
            "phase": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "chromosome": pl.Utf8,
    "time_point": pl.Utf8,
    "time_h": pl.Float64,
    "time_order": pl.Int64,
    "time_axis": pl.Float64,
    "phase": pl.Utf8,
    "share_pct": pl.Float64,
    "plus_share_pct": pl.Float64,
    "contig_order": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    per_library = (
        sources["bins"]
        .group_by("sample", "chromosome")
        .agg(pl.col("signal_rpm").sum().alias("signal"), pl.col("plus_rpm").sum().alias("plus"))
        .with_columns(
            (pl.col("signal") / pl.col("signal").sum().over("sample") * 100).alias("share_pct"),
            (pl.col("plus") / pl.col("signal").replace(0.0, None) * 100).alias("plus_share_pct"),
        )
    )
    times = (
        sources["samples"]
        .select("sample", *tc.TIME_POINT_COLUMNS)
        .filter(pl.col("time_order").is_not_null())
    )
    per_point = (
        per_library.join(times, on="sample", how="inner")
        .group_by("chromosome", *tc.TIME_POINT_COLUMNS)
        .agg(pl.col("share_pct").mean(), pl.col("plus_share_pct").mean())
    )
    contigs = (
        per_point.select("chromosome")
        .unique()
        .with_columns(sc.contig_order_expr("chromosome"))
        .sort(["_contig_number", "chromosome"], nulls_last=True)
        .with_row_index("contig_order", offset=1)
        .select("chromosome", pl.col("contig_order").cast(pl.Int64))
    )
    return (
        per_point.join(contigs, on="chromosome")
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["contig_order", "time_order"])
    )
