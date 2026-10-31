"""Splice junctions per sample, by intron motif and annotation, from STAR's ``SJ.out.tab``.

``SJ.out.tab`` holds one row per collapsed junction (200 to 400 thousand per
human RNA-seq sample): the intron, its strand, the intron motif STAR read off
the genome, whether the annotation already knew the junction, and the uniquely
and multi-mapping reads crossing it. A table that long says nothing drawn row
by row, so the recipe sums it per sample into the eight cells a splicing QC is
read on: four motif classes (GT/AG, GC/AG, AT/AC, non-canonical; the two strand
readings of a motif folded together) by annotated or novel.

A clean library spends nearly all its reads on annotated GT/AG junctions. Many
novel non-canonical junctions with few reads each are alignment noise; a high
novel share on canonical motifs is either real novel splicing or an annotation
that does not fit the sample.

Input: every ``*.SJ.out.tab`` under the run (tab-separated, no header), with the
file path in ``source_path``. The column meanings live in
``depictio.recipes.lib.star_logs.SJ_COLUMNS``.

Output schema:
    sample : Utf8               STAR's file prefix, the samplesheet id
    motif_class : Utf8          GT/AG, GC/AG, AT/AC or non-canonical
    motif_order : Int64         1 to 4, the order above
    annotation : Utf8           annotated (in the sjdb) or novel
    junctions : Int64           junctions in the cell
    unique_reads : Int64        uniquely mapping reads crossing them
    multimapping_reads : Int64  multi-mapping reads crossing them
    junctions_pct : Float64     of the sample's junctions, percent
    unique_reads_pct : Float64  of the sample's unique junction reads, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.star_logs import (
    MOTIF_CLASSES,
    SJ_COLUMNS,
    SOURCE_PATH_COL,
    sample_from_path,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="junctions",
        glob_pattern="**/*.SJ.out.tab",
        format="csv",
        read_kwargs={
            "separator": "\t",
            "has_header": False,
            "new_columns": SJ_COLUMNS,
            "schema_overrides": {"chrom": pl.Utf8},
        },
        source_path=SOURCE_PATH_COL,
        input_schema={
            "motif": pl.Int64,
            "annotated": pl.Int64,
            "unique_reads": pl.Int64,
            "multimapping_reads": pl.Int64,
            SOURCE_PATH_COL: pl.Utf8,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "motif_class": pl.Utf8,
    "motif_order": pl.Int64,
    "annotation": pl.Utf8,
    "junctions": pl.Int64,
    "unique_reads": pl.Int64,
    "multimapping_reads": pl.Int64,
    "junctions_pct": pl.Float64,
    "unique_reads_pct": pl.Float64,
}

_MOTIF_ORDER = {"GT/AG": 1, "GC/AG": 2, "AT/AC": 3, "non-canonical": 4}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Sum every junction table into motif class by annotation, per sample."""
    sj = sources["junctions"]
    paths = sj.select(SOURCE_PATH_COL).unique()
    samples = paths.with_columns(
        pl.col(SOURCE_PATH_COL).map_elements(sample_from_path, return_dtype=pl.Utf8).alias("sample")
    )
    motif = (
        pl.col("motif")
        .cast(pl.Int64)
        .replace_strict(MOTIF_CLASSES, default="non-canonical", return_dtype=pl.Utf8)
    )
    cells = (
        sj.join(samples, on=SOURCE_PATH_COL, how="left")
        .with_columns(
            motif.alias("motif_class"),
            pl.when(pl.col("annotated").cast(pl.Int64) == 1)
            .then(pl.lit("annotated"))
            .otherwise(pl.lit("novel"))
            .alias("annotation"),
        )
        .group_by(["sample", "motif_class", "annotation"])
        .agg(
            pl.len().cast(pl.Int64).alias("junctions"),
            pl.col("unique_reads").cast(pl.Int64).sum().alias("unique_reads"),
            pl.col("multimapping_reads").cast(pl.Int64).sum().alias("multimapping_reads"),
        )
    )
    total = pl.col("junctions").sum().over("sample")
    total_reads = pl.col("unique_reads").sum().over("sample")
    return (
        cells.with_columns(
            pl.col("motif_class")
            .replace_strict(_MOTIF_ORDER, default=5, return_dtype=pl.Int64)
            .alias("motif_order"),
            (pl.col("junctions") * 100.0 / total).round(3).alias("junctions_pct"),
            pl.when(total_reads > 0)
            .then(pl.col("unique_reads") * 100.0 / total_reads)
            .otherwise(None)
            .round(3)
            .alias("unique_reads_pct"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "motif_order", "annotation"])
    )
