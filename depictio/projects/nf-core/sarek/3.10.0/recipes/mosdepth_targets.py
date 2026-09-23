"""Per-target mosdepth depth, unbinned, for the Cohort QC locus section.

`mosdepth/regions.py` folds the capture targets into 1 Mb windows so a whole
exome fits on one genome-wide track. That is the right grain for the navigator
and the wrong one under it: a locus of a few hundred kilobases falls inside a
single window and would draw as one flat bar. This recipe keeps one row per
capture target instead, so a track that follows the navigator's region shows
the exons it covers and the depth on each.

The collection is large (one row per target, sample and mosdepth pass: about
850 000 rows on the sarek megatest) but it is only ever read narrowed to a
region, through the region link from `mosdepth_regions`, so a tile draws a few
hundred rows at a time.

Sample and stage come off the file name exactly as in `mosdepth/regions.py`
(``<sample>.<stage>.regions.bed.gz``, stage ``all`` when the name carries
none), and only the primary contigs are kept. Coordinates are named `chrom` /
`pos` like `vcf_variants` and `mosdepth_windows`, so every tile of the locus
section reads the region's filters on its own column names.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "mosdepth_regions_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="regions", dc_ref=RAW_DC_TAG)]

PRIMARY_CONTIG_RE = r"^(?:chr)?(?:\d{1,2}|X|Y|M|MT)$"
_NAME_RE = r"^(.+)\.([^.]+)\.regions\.bed(?:\.gz)?$"
_PLAIN_NAME_RE = r"^(.+)\.regions\.bed(?:\.gz)?$"
NO_STAGE = "all"

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chrom": pl.Utf8,
    "pos": pl.Int64,  # target start, 0-based
    "end": pl.Int64,  # target end
    "depth": pl.Float64,  # mean depth over the target
    "sample": pl.Utf8,
    "stage": pl.Utf8,  # md / recal on sarek
    "sample_stage": pl.Utf8,  # one track lane per sample and stage
    "target_bp": pl.Int64,  # target length
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per capture target, sample and mosdepth pass."""
    df = sources["regions"]
    basename = pl.col("source_path").str.split("/").list.last()
    return (
        df.with_columns(
            pl.col("chrom").cast(pl.Utf8).alias("chrom"),
            pl.col("start").cast(pl.Int64, strict=False).alias("pos"),
            pl.col("end").cast(pl.Int64, strict=False).alias("end"),
            pl.col("coverage").cast(pl.Float64, strict=False).alias("depth"),
            pl.coalesce(
                basename.str.extract(_NAME_RE, 1), basename.str.extract(_PLAIN_NAME_RE, 1)
            ).alias("sample"),
            basename.str.extract(_NAME_RE, 2).fill_null(NO_STAGE).alias("stage"),
        )
        .filter(
            pl.col("chrom").str.contains(PRIMARY_CONTIG_RE),
            pl.col("pos").is_not_null(),
            pl.col("end").is_not_null(),
        )
        .with_columns(
            (pl.col("end") - pl.col("pos")).alias("target_bp"),
            (pl.col("sample") + pl.lit(" (") + pl.col("stage") + pl.lit(")")).alias("sample_stage"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "stage", "chrom", "pos"])
    )
