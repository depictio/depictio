"""Per-contig coverage summary written by mosdepth.

``<sample>.<stage>.mosdepth.summary.txt`` is mosdepth's own headline table:
one row per contig with its length, the number of bases of sequence that
landed on it, and the mean, min and max depth. When mosdepth runs with
``--by`` it writes each contig twice: once over the whole contig, and once
more under ``<contig>_region`` over the target intervals only. Those are two
genuinely different numbers -- on an exome the genome-wide mean is a
fraction of the on-target mean -- so the suffix becomes a ``scope`` column
rather than being dropped or silently mixed into the contig axis.

Sample and stage come from the file name, not from the directory, for the
same reason as ``mosdepth/regions.py``: the publishing layout is the
pipeline's choice while the file name is mosdepth's. And as there, a file
named mosdepth's default way, ``<prefix>.mosdepth.summary.txt``, has no stage
token: the whole stem is the sample and the stage is recorded as ``all``.

The duplicate-marked (``md``) summaries of a GRCh38 run list every ALT,
decoy and HLA contig, 4 345 rows against the recalibrated file's 51. Keeping
only the primary contigs and the ``total`` roll-up makes the two stages
comparable on one axis and keeps a per-contig bar chart legible.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "mosdepth_summary_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="summary", dc_ref=RAW_DC_TAG)]

#: Primary contigs (with or without the UCSC ``chr`` prefix) plus mosdepth's
#: whole-run roll-up row.
PRIMARY_CONTIG_RE = r"^(?:(?:chr)?(?:\d{1,2}|X|Y|M|MT)|total)$"

#: ``<sample>.<stage>.mosdepth.summary.txt``; the stage is the last
#: dot-separated token before the fixed suffix.
_NAME_RE = r"^(.+)\.([^.]+)\.mosdepth\.summary\.txt$"
#: mosdepth's default ``<prefix>.mosdepth.summary.txt``: no stage token.
_PLAIN_NAME_RE = r"^(.+)\.mosdepth\.summary\.txt$"
#: Stage recorded for a file whose name carries none.
NO_STAGE = "all"

#: Suffix mosdepth appends to the contig name of a ``--by`` (on-target) row.
_REGION_SUFFIX = "_region"

#: When mosdepth ran more than once on a sample (sarek measures the
#: duplicate-marked and then the recalibrated CRAM), one pass is kept: the
#: first of these stages the sample has, else its alphabetically first one.
#: Recalibration rewrites base qualities, not alignments, so the passes carry
#: the same depth; keeping both doubled every sum and every track lane.
STAGE_PREFERENCE = ("recal", "md", "sorted")


def keep_one_stage(df: pl.DataFrame) -> pl.DataFrame:
    """Rows of one mosdepth pass per sample (see ``STAGE_PREFERENCE``)."""
    rank = pl.col("stage").replace_strict(
        {s: i for i, s in enumerate(STAGE_PREFERENCE)},
        default=len(STAGE_PREFERENCE),
        return_dtype=pl.Int64,
    )
    kept = (
        df.select("sample", "stage")
        .unique()
        .with_columns(rank.alias("_rank"))
        .sort(["sample", "_rank", "stage"])
        .unique(subset="sample", keep="first", maintain_order=True)
        .select("sample", "stage")
    )
    return df.join(kept, on=["sample", "stage"], how="semi")


EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "stage": pl.Utf8,  # md / recal on sarek; "all" when the file name has no stage
    "scope": pl.Utf8,  # genome (whole contig) or region (--by targets only)
    "chrom": pl.Utf8,
    "length": pl.Int64,
    "bases": pl.Int64,
    "mean_depth": pl.Float64,
    "min_depth": pl.Int64,
    "max_depth": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample, stage, scope and contig."""
    df = sources["summary"]

    basename = pl.col("source_path").str.split("/").list.last()
    is_region = pl.col("chrom").str.ends_with(_REGION_SUFFIX)

    return keep_one_stage(
        df.with_columns(
            pl.coalesce(
                basename.str.extract(_NAME_RE, 1), basename.str.extract(_PLAIN_NAME_RE, 1)
            ).alias("sample"),
            basename.str.extract(_NAME_RE, 2).fill_null(NO_STAGE).alias("stage"),
            pl.when(is_region).then(pl.lit("region")).otherwise(pl.lit("genome")).alias("scope"),
            pl.when(is_region)
            .then(pl.col("chrom").str.strip_suffix(_REGION_SUFFIX))
            .otherwise(pl.col("chrom"))
            .alias("contig"),
            pl.col("length").cast(pl.Int64, strict=False),
            pl.col("bases").cast(pl.Int64, strict=False),
            pl.col("mean").cast(pl.Float64, strict=False).alias("mean_depth"),
            pl.col("min").cast(pl.Int64, strict=False).alias("min_depth"),
            pl.col("max").cast(pl.Int64, strict=False).alias("max_depth"),
        )
        .filter(pl.col("contig").str.contains(PRIMARY_CONTIG_RE))
        .drop("chrom")
        .rename({"contig": "chrom"})
        .select(list(EXPECTED_SCHEMA))
    ).sort(["sample", "stage", "scope", "chrom"])
