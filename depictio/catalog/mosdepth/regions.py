"""Per-target mosdepth depth, binned into a genome-wide coverage track.

mosdepth writes one headerless BED4 per sample and per alignment stage,
``<sample>.<stage>.regions.bed.gz``, with one row per interval of the
``--by`` target file: ``chrom  start  end  mean_depth``. On a whole-exome or
targeted run that is one row per capture target, which for sarek's megatest
is 212 611 rows per file. Four files of that size are three orders of
magnitude more points than a coverage tile can draw, and the targets are not
evenly spaced, so plotting them raw both melts the browser and reads as
noise rather than as coverage.

So the recipe bins: every target is folded into the fixed genomic window it
starts in and the window's depth is the target-length-weighted mean of the
targets inside it, which is the depth an aggregate of the same bases would
have had. The window count, not the target count, then sets the tile size.

Sample and stage are read off the file name rather than the directory,
because the directory a pipeline publishes these under is its own choice
(sarek writes ``reports/mosdepth/<sample>/``, other pipelines write a flat
``mosdepth/``) while the file name is mosdepth's own and carries both ids.
A file named mosdepth's default way, ``<prefix>.regions.bed.gz`` (methylseq,
nanoseq, raredisease, circdna), carries no stage token: its whole stem is the
sample and the stage is recorded as ``all``.

Only primary contigs are kept. A GRCh38 run lists hundreds of ALT, decoy and
HLA contigs whose windows would otherwise dominate the categorical
chromosome axis with names no reader is looking for.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "mosdepth_regions_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="regions", dc_ref=RAW_DC_TAG)]

#: Width of one genomic window, in base pairs. A coverage tile stays readable
#: and stays within the renderer's point budget at roughly 15 000 rows; this
#: run's 212 611 targets per sample and stage, over four sample/stage pairs,
#: are 850 000. At 1 Mb the same run bins down to about 12 000 windows, and
#: the number scales with genome size rather than with panel density, so a
#: WGS run (whose ``--by`` is a window file already) lands in the same range.
BIN_SIZE = 1_000_000

#: Primary contigs, with and without the UCSC ``chr`` prefix, so a run on an
#: Ensembl-style reference keeps the same 24 contigs an analyst expects.
PRIMARY_CONTIG_RE = r"^(?:chr)?(?:\d{1,2}|X|Y|M|MT)$"

#: ``<sample>.<stage>.regions.bed[.gz]``: the stage is the last dot-separated
#: token before the fixed suffix, so a sample id containing dots survives.
_NAME_RE = r"^(.+)\.([^.]+)\.regions\.bed(?:\.gz)?$"
#: mosdepth's default ``<prefix>.regions.bed[.gz]``: the whole stem is the
#: sample and there is no stage token.
_PLAIN_NAME_RE = r"^(.+)\.regions\.bed(?:\.gz)?$"
#: Stage recorded for a file whose name carries none.
NO_STAGE = "all"

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chromosome": pl.Utf8,
    "position": pl.Int64,  # window start
    "end": pl.Int64,  # window start + BIN_SIZE
    "value": pl.Float64,  # target-length-weighted mean depth in the window
    "sample": pl.Utf8,
    "stage": pl.Utf8,  # md / recal on sarek; "all" when the file name has no stage
    "sample_stage": pl.Utf8,  # one track lane per sample and stage
    "n_targets": pl.Int64,  # targets folded into the window
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample, stage, contig and 1 Mb window."""
    df = sources["regions"]

    basename = pl.col("source_path").str.split("/").list.last()
    typed = df.with_columns(
        pl.col("chrom").alias("chromosome"),
        pl.col("start").cast(pl.Int64, strict=False).alias("start_bp"),
        pl.col("end").cast(pl.Int64, strict=False).alias("end_bp"),
        pl.col("coverage").cast(pl.Float64, strict=False).alias("depth"),
        pl.coalesce(
            basename.str.extract(_NAME_RE, 1), basename.str.extract(_PLAIN_NAME_RE, 1)
        ).alias("sample"),
        basename.str.extract(_NAME_RE, 2).fill_null(NO_STAGE).alias("stage"),
    ).filter(
        pl.col("chromosome").str.contains(PRIMARY_CONTIG_RE),
        pl.col("start_bp").is_not_null(),
        pl.col("end_bp").is_not_null(),
    )

    binned = (
        typed.with_columns(
            ((pl.col("start_bp") // BIN_SIZE) * BIN_SIZE).alias("position"),
            (pl.col("end_bp") - pl.col("start_bp")).alias("target_bp"),
        )
        .group_by(["sample", "stage", "chromosome", "position"])
        .agg(
            (pl.col("target_bp") * pl.col("depth")).sum().alias("weighted_bp"),
            pl.col("target_bp").sum().alias("covered_bp"),
            pl.len().cast(pl.Int64).alias("n_targets"),
        )
    )

    return (
        binned.with_columns(
            (pl.col("position") + BIN_SIZE).alias("end"),
            # A window whose targets are all zero-length carries no depth at
            # all; reporting 0.0 there would read as a real drop-out.
            pl.when(pl.col("covered_bp") > 0)
            .then(pl.col("weighted_bp") / pl.col("covered_bp"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("value"),
            (pl.col("sample") + pl.lit(" (") + pl.col("stage") + pl.lit(")")).alias("sample_stage"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "stage", "chromosome", "position"])
    )
