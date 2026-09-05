"""Per-sample MACS2 peak QC: call count, FRiP score and peak-metric spreads.

The peak-QC step that follows MACS2 in the nf-core ChIP-family pipelines writes
three things next to the peak calls:

* ``<prefix>peak.summary.txt`` — one row per (sample, measure) with the six
  ``summary()`` quantiles of that measure over the sample's peaks plus the peak
  count. ``measure`` is one of ``length``, ``fold``, ``-log10(pvalue)`` and
  ``-log10(qvalue)``.
* ``<sample>_peaks.FRiP_mqc.tsv`` — the sample's FRiP score, one data line
  under a MultiQC custom-content header.
* ``<sample>_peaks.count_mqc.tsv`` — the same peak count, same shape.

This recipe pivots the long summary into one row per sample and joins the FRiP
score onto it, which is the per-sample shape cards and a bar chart read. The
count files are not read: the count is already a column of the summary.

MultiQC renders the FRiP score and the peak count as two bar plots from the
custom-content files; what it does not carry is the *distribution* of peak
width, fold enrichment and significance behind those two numbers, which is what
this output adds.

Output schema:
    sample : Utf8                     sample the peaks were called in
    num_peaks : Int64                 peaks MACS2 called for the sample
    frip_score : Float64              fraction of mapped reads inside peaks
    width_median : Float64            median peak width (bp)
    width_mean : Float64              mean peak width (bp)
    width_max : Float64               widest peak (bp)
    fold_enrichment_median : Float64  median fold enrichment over the control
    fold_enrichment_mean : Float64    mean fold enrichment over the control
    neg_log10_qvalue_median : Float64 median -log10 q-value
    neg_log10_pvalue_median : Float64 median -log10 p-value
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        glob_pattern="**/*peak.summary.txt",
        format="TSV",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(
        ref="frip",
        glob_pattern="**/*_peaks.FRiP_mqc.tsv",
        format="TSV",
        read_kwargs={
            "has_header": False,
            "comment_prefix": "#",
            "new_columns": ["sample", "frip_score"],
            "infer_schema_length": 0,
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
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
# summary() quantile column -> statistic suffix. `Min.`/`1st Qu.`/`3rd Qu.` are
# read but only the statistics the schema names are kept.
_STATS = {"Median": "median", "Mean": "mean", "Max.": "max"}

_REQUIRED = ["sample", "measure", "num_peaks", *_STATS]


def _pivot_measures(summary: pl.DataFrame) -> pl.DataFrame:
    """Long (sample, measure) rows -> one row per sample, one column per statistic."""
    df = summary.with_columns(
        pl.col("sample").cast(pl.Utf8),
        pl.col("measure").cast(pl.Utf8),
        pl.col("num_peaks").cast(pl.Float64, strict=False).cast(pl.Int64),
        *[pl.col(stat).cast(pl.Float64, strict=False) for stat in _STATS],
    )
    wide = df.group_by("sample").agg(pl.col("num_peaks").max())
    for measure, prefix in _MEASURES.items():
        block = df.filter(pl.col("measure") == measure)
        if block.is_empty():
            continue
        block = block.select(
            "sample",
            *[pl.col(stat).alias(f"{prefix}_{suffix}") for stat, suffix in _STATS.items()],
        )
        wide = wide.join(block, on="sample", how="left")
    return wide


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot the peak summary and join the FRiP score onto it."""
    summary = sources["summary"]
    missing = [c for c in _REQUIRED if c not in summary.columns]
    if missing:
        raise ValueError(f"macs2_peak_summary: peak summary lacks columns {missing}")

    wide = _pivot_measures(summary)

    frip = sources["frip"].select(
        pl.col("sample").cast(pl.Utf8).str.strip_chars(),
        pl.col("frip_score").cast(pl.Float64, strict=False),
    )
    wide = wide.join(frip.unique(subset="sample"), on="sample", how="left")

    for column, dtype in EXPECTED_SCHEMA.items():
        if column not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=dtype).alias(column))
    return wide.select(list(EXPECTED_SCHEMA)).sort("sample")
