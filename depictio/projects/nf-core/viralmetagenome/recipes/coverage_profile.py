"""Depth along each genome, with the virus segment it is.

``coverage_bins`` (catalog ``mosdepth/per_base_bins``) holds the binned depth of
every mapping, keyed ``genome_id``; it knows nothing of the virus. A segmented
virus is read segment by segment, so this recipe joins the genome hub's
``virus_segment`` onto every bin, for a depth profile faceted by segment.

Sources:
    bins     ``coverage_bins``
    genomes  ``genomes``, the genome hub, optional

Output schema: the ``coverage_bins`` columns, then
    virus, segment, virus_segment, route : Utf8
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_BINS = {
    "sample": pl.Utf8,
    "reference": pl.Utf8,
    "genome_id": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "position": pl.Int64,
    "mean_depth": pl.Float64,
    "min_depth": pl.Int64,
}

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="bins",
        dc_ref="coverage_bins",
        input_schema={"genome_id": pl.Utf8, "chrom": pl.Utf8, "start": pl.Int64, "end": pl.Int64},
    ),
    RecipeSource(
        ref="genomes", dc_ref="genomes", optional=True, input_schema={"genome_id": pl.Utf8}
    ),
]

_HUB = {"virus": pl.Utf8, "segment": pl.Utf8, "virus_segment": pl.Utf8, "route": pl.Utf8}

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    **_BINS,
    **_HUB,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    bins = sources["bins"]
    for col, dtype in _BINS.items():
        if col not in bins.columns:
            bins = bins.with_columns(pl.lit(None, dtype=dtype).alias(col))
    genomes = sources.get("genomes")
    have = [c for c in _HUB if genomes is not None and c in genomes.columns]
    if have and not genomes.is_empty():
        bins = bins.join(
            genomes.select("genome_id", *have).unique(subset="genome_id"),
            on="genome_id",
            how="left",
        )
    for col, dtype in _HUB.items():
        if col not in bins.columns:
            bins = bins.with_columns(pl.lit(None, dtype=dtype).alias(col))
    # A genome the hub does not hold still draws, under its own key.
    bins = bins.with_columns(pl.col("virus_segment").fill_null(pl.col("genome_id")))
    return bins.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["sample", "genome_id", "chrom", "start"]
    )
