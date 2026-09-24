"""X and Y mean depth per library, and the sex the ratio is consistent with.

MultiQC's mosdepth module writes one small table per run,
``mosdepth-xy-coverage-plot.txt``, with the mean depth on chromosome X and
on chromosome Y for every library it saw. Because it is one file for the
whole run and it carries a header and its own sample column, it is read by
glob rather than through a raw scan DC -- there is nothing to recover from
the path.

Its ``Sample`` column is the BAM stem, ``<sample>.<stage>``, so the same
library appears once per alignment stage. The stage is split off so the
library joins its sample, and one pass per sample is kept (see
``keep_one_stage``): the stages measure the same alignments.

The X/Y depth ratio is the classic aneuploidy-free check that the sex of the
sequenced material matches the sex recorded in the sample sheet: a karyotype
with two X and no Y has almost no Y signal (the ratio runs into the tens or
hundreds, bounded only by mismapping into the pseudoautosomal and
X-transposed regions), while one X and one Y sits near 1. The 10x cut-off
used here sits in the empty band between those two populations, far from
either. It is a heuristic on two summary numbers, not a genotype call: a sex
chromosome aneuploidy, a contaminated or mixed library, or a very low-depth
run can all land on the wrong side of it, and the raw X and Y depths are
kept so a reader can see how far from the cut-off a library actually is.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="xy", glob_pattern="**/mosdepth-xy-coverage-plot.txt", format="tsv")
]

#: X/Y mean-depth ratio at or above which the library reads as XX. See the
#: module docstring: a heuristic mid-band cut-off, not a genotype call.
XX_RATIO_CUTOFF = 10.0

#: MultiQC's own headers; the contig labels are MultiQC's, not the reference's.
_REQUIRED_COLUMNS = ("Sample", "Chromosome X", "Chromosome Y")

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
    "stage": pl.Utf8,  # md (duplicate-marked) or recal (BQSR-recalibrated)
    "x_coverage": pl.Float64,
    "y_coverage": pl.Float64,
    "xy_ratio": pl.Float64,  # null when Y depth is 0, so no ratio exists
    "inferred_sex": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library and alignment stage."""
    df = sources["xy"]
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"mosdepth_xy_sex_check: mosdepth-xy-coverage-plot.txt lacks column(s) {missing}, "
            f"got {df.columns}; MultiQC writes the file only when it recognised an X and a Y "
            "contig, so a run whose reference names them differently cannot be checked here"
        )

    # `<sample>.<stage>`: split on the LAST dot, so a sample id with dots in
    # it keeps them.
    stem = pl.col("Sample").cast(pl.Utf8)
    x_cov = pl.col("Chromosome X").cast(pl.Float64, strict=False)
    y_cov = pl.col("Chromosome Y").cast(pl.Float64, strict=False)
    ratio = (pl.when((y_cov.is_not_null()) & (y_cov > 0)).then(x_cov / y_cov).otherwise(None)).cast(
        pl.Float64
    )

    return keep_one_stage(
        df.with_columns(
            stem.str.extract(r"^(.*)\.[^.]+$", 1).fill_null(stem).alias("sample"),
            stem.str.extract(r"\.([^.]+)$", 1).fill_null("all").alias("stage"),
            x_cov.alias("x_coverage"),
            y_cov.alias("y_coverage"),
            ratio.alias("xy_ratio"),
        )
        .with_columns(
            pl.when(pl.col("xy_ratio").is_null())
            .then(pl.lit("XX"))  # no Y signal at all reads as XX
            .when(pl.col("xy_ratio") >= XX_RATIO_CUTOFF)
            .then(pl.lit("XX"))
            .otherwise(pl.lit("XY"))
            .alias("inferred_sex")
        )
        .select(list(EXPECTED_SCHEMA))
    ).sort(["sample", "stage"])
