"""Mapping quality along the reference, from Qualimap BamQC's windowed table.

``raw_data_qualimapReport/mapping_quality_across_reference.txt`` sits beside
the ``coverage_across_reference.txt`` the catalog recipe
``qualimap/coverage_across_reference.py`` reads, over the same windows, with
two tab-separated columns after a ``#``-prefixed header::

    #Position (bp)  mapping quality
    837459.0        36.36934952613818

As for depth, the position is the window centre on the concatenated
reference, so this recipe maps each window back onto its contig from the
``Coverage per contig`` block of the same run's ``genome_results.txt`` (the
raw scan ``qualimap_bamqc_genome_results_raw`` already holds). The output
names its coordinate columns exactly like the depth collection
(``chromosome`` / ``position``), which is what lets the eager Coverage tab's
locus navigator (a ``genome_view`` on the depth windows) carry its region onto
this track through a ``region`` link.

It stays pipeline-local: eager is the only template that publishes Qualimap's
raw windowed tables, and it backs a single track.

Input: two data collections scanned one LINE per row with
``include_file_paths: source_path`` (see ``template.yaml``).

Output schema:
    sample : Utf8              library Qualimap ran on
    chromosome : Utf8          contig the window falls in ("genome" without the contig map)
    position : Int64           window centre on that contig, bp
    mapping_quality : Float64  mean MAPQ of the reads in the window
    global_position : Int64    window centre on the concatenated reference, bp
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.qualimap_raw import (
    RAW_LINE_COL,
    SOURCE_PATH_COL,
    contig_coverage_block,
    split_columns,
)

RAW_DC_TAG = "qualimap_mapq_across_reference_raw"
CONTIG_DC_TAG = "qualimap_bamqc_genome_results_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="windows", dc_ref=RAW_DC_TAG),
    RecipeSource(ref="reports", dc_ref=CONTIG_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "chromosome": pl.Utf8,
    "position": pl.Int64,
    "mapping_quality": pl.Float64,
    "global_position": pl.Int64,
}

_RECIPE = "eager_mapq_across_reference"
_WHOLE_GENOME = "genome"


def _contig_starts(reports: pl.DataFrame | None) -> pl.DataFrame | None:
    """One row per (sample, contig) with its start on the concatenated axis, or None."""
    if reports is None or reports.is_empty():
        return None
    if RAW_LINE_COL not in reports.columns or SOURCE_PATH_COL not in reports.columns:
        return None
    contigs = contig_coverage_block(reports, recipe=_RECIPE)
    if contigs.is_empty():
        return None
    return contigs.select(
        "sample",
        "chromosome",
        (pl.col("length").cum_sum() - pl.col("length"))
        .over("sample")
        .cast(pl.Int64)
        .alias("contig_start"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, window), placed on its contig when the map is known."""
    windows = (
        split_columns(sources["windows"], ["global_position", "mapping_quality"], recipe=_RECIPE)
        .with_columns(
            pl.col("global_position").cast(pl.Float64, strict=False).cast(pl.Int64),
            pl.col("mapping_quality").cast(pl.Float64, strict=False),
        )
        .drop_nulls(["global_position", "mapping_quality"])
    )
    if windows.is_empty():
        raise ValueError(f"{_RECIPE}: no window carried a position and a mapping quality")

    contigs = _contig_starts(sources.get("reports"))
    if contigs is None:
        placed = windows.with_columns(
            pl.lit(_WHOLE_GENOME, dtype=pl.Utf8).alias("chromosome"),
            pl.col("global_position").alias("position"),
        )
    else:
        placed = (
            windows.sort("global_position")
            .join_asof(
                contigs.sort("contig_start"),
                left_on="global_position",
                right_on="contig_start",
                by="sample",
                strategy="backward",
            )
            .with_columns(
                pl.col("chromosome").fill_null(_WHOLE_GENOME),
                (pl.col("global_position") - pl.col("contig_start").fill_null(0))
                .cast(pl.Int64)
                .alias("position"),
            )
        )

    return placed.select(list(EXPECTED_SCHEMA)).sort(["sample", "global_position"])
