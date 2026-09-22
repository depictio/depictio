"""Read depth along the reference, from Qualimap BamQC's own windowed table.

``raw_data_qualimapReport/coverage_across_reference.txt`` is the table behind
the "Coverage across reference" plot: one row per window (Qualimap uses 400
windows by default, more on a large reference), three tab-separated columns
after a ``#``-prefixed header::

    #Position (bp)  Coverage             Std
    837459.0        0.47273506687197037  1.0821253803850588
    2512376.0       0.5067325724200065   1.1138308163242676

The position is the **centre of the window in the concatenated reference**, not
a coordinate on a contig: Qualimap lays every contig end to end and reports one
axis. A coverage track needs a contig name, so this recipe optionally reads the
``Coverage per contig`` block of the same run's ``genome_results.txt`` (the
collection ``qualimap/bamqc_genome_results.py`` already scans), rebuilds the
cumulative offsets from the contig lengths and maps each window back onto the
contig it falls in.

That second source is declared ``optional``: when it is absent the recipe still
produces a track, with a single pseudo-contig named ``genome`` and the
concatenated coordinate. The global coordinate is kept as its own column either
way, so a reader can always line two libraries up on the same axis.

Input: a data collection reading every matched table one LINE per row, e.g.::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*coverage_across_reference\\.txt$'}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\x1f"
          has_header: false
          new_columns: ["raw"]
          comment_prefix: "#"
          include_file_paths: "source_path"
          infer_schema_length: 0

Output schema:
    sample : Utf8            library Qualimap ran on
    chromosome : Utf8        contig the window falls in ("genome" without the contig map)
    position : Int64         window centre on that contig, bp
    coverage : Float64       mean depth in the window, X
    coverage_std : Float64   standard deviation of the depth in the window
    global_position : Int64  window centre on the concatenated reference, bp
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

#: Data-collection tag the template must scan the windowed tables into.
RAW_DC_TAG = "qualimap_coverage_across_reference_raw"
#: Data-collection tag of the BamQC summary reports, read for the contig map.
CONTIG_DC_TAG = "qualimap_bamqc_genome_results_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="windows", dc_ref=RAW_DC_TAG),
    RecipeSource(ref="reports", dc_ref=CONTIG_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "chromosome": pl.Utf8,
    "position": pl.Int64,
    "coverage": pl.Float64,
    "coverage_std": pl.Float64,
    "global_position": pl.Int64,
}

_RECIPE = "qualimap_coverage_across_reference"
#: Pseudo-contig used when no contig map is available.
_WHOLE_GENOME = "genome"


def _contig_map(reports: pl.DataFrame | None) -> pl.DataFrame | None:
    """One row per (sample, contig) with the contig's start offset, or None.

    The ``Coverage per contig`` block lists the contigs in reference order with
    their lengths, which is exactly what the concatenated axis was built from,
    so a running sum of the lengths recovers every contig's start offset.
    """
    if reports is None or reports.is_empty():
        return None
    if RAW_LINE_COL not in reports.columns or SOURCE_PATH_COL not in reports.columns:
        return None

    contigs = contig_coverage_block(reports, recipe=_RECIPE)
    if contigs.is_empty():
        return None
    # The block keeps the reference order, so the lengths before a contig are
    # its start on the concatenated axis.
    return contigs.select(
        "sample",
        "chromosome",
        (pl.col("length").cum_sum() - pl.col("length"))
        .over("sample")
        .cast(pl.Int64)
        .alias("contig_start"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, window), mapped onto a contig when one is known."""
    windows = (
        split_columns(
            sources["windows"], ["global_position", "coverage", "coverage_std"], recipe=_RECIPE
        )
        .with_columns(
            pl.col("global_position").cast(pl.Float64, strict=False).cast(pl.Int64),
            pl.col("coverage").cast(pl.Float64, strict=False),
            pl.col("coverage_std").cast(pl.Float64, strict=False),
        )
        .drop_nulls(["global_position", "coverage"])
    )
    if windows.is_empty():
        raise ValueError(f"{_RECIPE}: no window carried a position and a depth")

    contigs = _contig_map(sources.get("reports"))
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
