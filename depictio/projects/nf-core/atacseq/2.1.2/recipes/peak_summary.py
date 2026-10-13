"""Per-sample MACS2 peak QC for atacseq 2.x: call count, FRiP score, peak spreads.

The catalog's ``macs2/peak_summary.py`` pivots the peak-QC summary and joins the
FRiP score onto it by sample name. atacseq 2.x spells that sample two ways:

* ``macs2_peak.mLb.clN.summary.txt`` names it after the merged, filtered
  library (``WT_REP1.mLb.clN``);
* ``WT_REP1.mLb.clN_peaks.FRiP_mqc.tsv`` holds the bare sample (``WT_REP1``).

A join on the raw name leaves every FRiP score null, so this version recipe
strips the merge-level suffix from both sides (``strip_stage_suffixes``, the
helper every catalog recipe uses for these names) before joining, and keys the
table on the bare sample like the ataqv and deepTools collections. Both globs
name the merged-library files only: the merged-replicate level writes the same
two files as ``.mRp.clN``, and reading both would put two levels of one
analysis in one table.

Output schema (the catalog recipe's, so the dashboards bind it alike):
    sample : Utf8                     sample the peaks were called in
    num_peaks : Int64                 peaks MACS2 called for the sample
    frip_score : Float64              fraction of mapped reads inside peaks
    width_median : Float64            median peak width (bp)
    width_mean : Float64              mean peak width (bp)
    width_max : Float64               widest peak (bp)
    fold_enrichment_median : Float64  median fold enrichment over the background
    fold_enrichment_mean : Float64    mean fold enrichment over the background
    neg_log10_qvalue_median : Float64 median -log10 q-value
    neg_log10_pvalue_median : Float64 median -log10 p-value
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        glob_pattern="**/merged_library/macs2/*/qc/macs2_peak.mLb.clN.summary.txt",
        format="TSV",
        input_schema={
            "sample": pl.Utf8,
            "measure": pl.Utf8,
            "num_peaks": pl.Utf8,
            "Median": pl.Utf8,
            "Mean": pl.Utf8,
            "Max.": pl.Utf8,
        },
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(
        ref="frip",
        glob_pattern="**/merged_library/macs2/*/qc/*.mLb.clN_peaks.FRiP_mqc.tsv",
        format="TSV",
        input_schema={"sample": pl.Utf8, "frip_score": pl.Utf8},
        read_kwargs={
            "has_header": False,
            "comment_prefix": "#",
            "new_columns": ["sample", "frip_score"],
            "infer_schema_length": 0,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "num_peaks": pl.Int64,
    "frip_score": pl.Float64,
    "width_median": pl.Float64,
    "width_mean": pl.Float64,
    "width_max": pl.Float64,
    "fold_enrichment_median": pl.Float64,
    "fold_enrichment_mean": pl.Float64,
    "neg_log10_qvalue_median": pl.Float64,
    "neg_log10_pvalue_median": pl.Float64,
}

# `measure` value in the summary -> prefix of the output columns.
_MEASURES = {
    "length": "width",
    "fold": "fold_enrichment",
    "-log10(qvalue)": "neg_log10_qvalue",
    "-log10(pvalue)": "neg_log10_pvalue",
}
# summary() quantile column -> statistic suffix.
_STATS = {"Median": "median", "Mean": "mean", "Max.": "max"}


def _bare_sample(column: str) -> pl.Expr:
    """The sample without its merge-level suffix (``WT_REP1.mLb.clN`` -> ``WT_REP1``)."""
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .str.strip_chars()
        .map_elements(strip_stage_suffixes, return_dtype=pl.Utf8)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot the peak summary per sample and join the FRiP score onto it."""
    summary = sources["summary"].with_columns(
        _bare_sample("sample").alias("sample"),
        pl.col("measure").cast(pl.Utf8),
        pl.col("num_peaks").cast(pl.Float64, strict=False).cast(pl.Int64),
        *[pl.col(stat).cast(pl.Float64, strict=False) for stat in _STATS],
    )

    wide = summary.group_by("sample").agg(pl.col("num_peaks").max())
    for measure, prefix in _MEASURES.items():
        block = summary.filter(pl.col("measure") == measure)
        if block.is_empty():
            continue
        wide = wide.join(
            block.select(
                "sample",
                *[pl.col(stat).alias(f"{prefix}_{suffix}") for stat, suffix in _STATS.items()],
            ).unique(subset="sample"),
            on="sample",
            how="left",
        )

    frip = sources["frip"].select(
        _bare_sample("sample").alias("sample"),
        pl.col("frip_score").cast(pl.Float64, strict=False),
    )
    wide = wide.join(frip.unique(subset="sample"), on="sample", how="left")

    for column, dtype in OUTPUT_SCHEMA.items():
        if column not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=dtype).alias(column))
    return wide.select(list(OUTPUT_SCHEMA)).sort("sample")
