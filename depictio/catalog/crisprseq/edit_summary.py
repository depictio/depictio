"""Read accounting and edit outcome rates, one row per library.

Joins three CIGAR-parser tables per library:

* ``<sample>_reads-summary.csv``: raw reads, the merged and quality-filtered
  shares (percent), clustered reads and the aligned share (percent);
* ``<sample>_edits.csv``: reads per outcome class (wild type, template-based,
  deletion-insertion, in-frame and frameshift insertions and deletions);
* ``<sample>_QC-indels.csv``: reads dropped by the indel filters, and the
  passing indels split by whether they sit above the sequencing error rate and
  inside the library's main indel peak.

The rates are shares of the classified reads (the sum of the outcome classes):
``edited_pct`` is everything but wild type, ``frameshift_pct`` the out-of-frame
insertions and deletions, ``inframe_pct`` the in-frame ones.
``frameshift_of_indels_pct`` is the out-of-frame share of the indel reads alone,
the knockout-relevant number once editing happened at all (null without indels).
Rates are rounded to three significant figures.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import first_matching, num, rounded, sample_expr

_TEXT = {"infer_schema_length": 0, "null_values": ["NA", ""]}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reads",
        glob_pattern="**/*_reads-summary.csv",
        format="csv",
        read_kwargs=_TEXT,
        source_path="source_path",
    ),
    RecipeSource(
        ref="edits",
        glob_pattern="**/*_edits.csv",
        format="csv",
        read_kwargs=_TEXT,
        source_path="source_path",
    ),
    RecipeSource(
        ref="qc",
        glob_pattern="**/*_QC-indels.csv",
        format="csv",
        read_kwargs=_TEXT,
        source_path="source_path",
    ),
]

# Column order is the table's: the library and its editing rates first, the
# read accounting next, the raw class and filter counts last.
EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "classified_reads": pl.Int64,
    "edited_pct": pl.Float64,
    "indel_pct": pl.Float64,
    "frameshift_pct": pl.Float64,
    "inframe_pct": pl.Float64,
    "template_based_pct": pl.Float64,
    "frameshift_of_indels_pct": pl.Float64,
    "raw_reads": pl.Int64,
    "clustered_reads": pl.Int64,
    "aligned_pct": pl.Float64,
    "quality_filtered_pct": pl.Float64,
    "merged_pct": pl.Float64,
    "edited_reads": pl.Int64,
    "wt_reads": pl.Int64,
    "template_based_reads": pl.Int64,
    "delins_reads": pl.Int64,
    "ins_inframe_reads": pl.Int64,
    "ins_frameshift_reads": pl.Int64,
    "del_inframe_reads": pl.Int64,
    "del_frameshift_reads": pl.Int64,
    "wt_failing_filter": pl.Int64,
    "indels_failing_filter": pl.Int64,
    "indels_above_error_in_peak": pl.Int64,
    "indels_above_error_outside_peak": pl.Int64,
    "indels_below_error_in_peak": pl.Int64,
    "indels_below_error_outside_peak": pl.Int64,
}

# (output column, accepted source headers) per table.
_READS = {
    "raw_reads": ("Raw reads",),
    "merged_pct": ("Merged reads",),
    "quality_filtered_pct": ("Quality filtered reads",),
    "clustered_reads": ("Clustered reads",),
    "aligned_pct": ("Aligned reads",),
}
_EDITS = {
    "wt_reads": ("Wt",),
    "template_based_reads": ("Template-based",),
    "delins_reads": ("Delins",),
    "ins_inframe_reads": ("Ins_inframe",),
    "ins_frameshift_reads": ("Ins_outframe",),
    "del_inframe_reads": ("Dels_inframe",),
    "del_frameshift_reads": ("Dels_outframe",),
}
_QC = {
    "wt_failing_filter": ("Wt NOT passing filter",),
    "indels_failing_filter": ("Indels NOT passing filter",),
    "indels_above_error_in_peak": ("Above error & in pick",),
    "indels_above_error_outside_peak": ("Above error & NOT in pick",),
    "indels_below_error_in_peak": ("NOT above error & in pick",),
    "indels_below_error_outside_peak": ("NOT above error & NOT in pick",),
}


def _pick(df: pl.DataFrame, spec: dict[str, tuple[str, ...]]) -> pl.DataFrame:
    exprs = [sample_expr()]
    for out, names in spec.items():
        dtype = pl.Float64 if out.endswith("_pct") else pl.Int64
        src = first_matching(df.columns, *names)
        exprs.append((num(src, dtype) if src else pl.lit(None, dtype=dtype)).cast(dtype).alias(out))
    return df.select(exprs).unique(subset=["sample"], keep="first")


def _pct(num_expr: pl.Expr, den: str) -> pl.Expr:
    return (pl.when(pl.col(den) > 0).then(num_expr * 100.0 / pl.col(den)).otherwise(None)).cast(
        pl.Float64
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    edits = _pick(sources["edits"], _EDITS)
    reads = _pick(sources["reads"], _READS)
    qc = _pick(sources["qc"], _QC)
    counts = list(_EDITS)
    out = (
        edits.join(reads, on="sample", how="full", coalesce=True)
        .join(qc, on="sample", how="left")
        .with_columns([pl.col(c).fill_null(0) for c in counts])
        .with_columns(pl.sum_horizontal(counts).cast(pl.Int64).alias("classified_reads"))
        .with_columns((pl.col("classified_reads") - pl.col("wt_reads")).alias("edited_reads"))
    )
    frameshift = pl.col("ins_frameshift_reads") + pl.col("del_frameshift_reads")
    inframe = pl.col("ins_inframe_reads") + pl.col("del_inframe_reads")
    indels = frameshift + inframe + pl.col("delins_reads")
    out = out.with_columns(
        _pct(pl.col("edited_reads"), "classified_reads").alias("edited_pct"),
        _pct(indels, "classified_reads").alias("indel_pct"),
        _pct(frameshift, "classified_reads").alias("frameshift_pct"),
        _pct(inframe, "classified_reads").alias("inframe_pct"),
        _pct(pl.col("template_based_reads"), "classified_reads").alias("template_based_pct"),
        pl.when((frameshift + inframe) > 0)
        .then(frameshift * 100.0 / (frameshift + inframe))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("frameshift_of_indels_pct"),
    )
    rates = [c for c, t in EXPECTED_SCHEMA.items() if t == pl.Float64]
    return out.with_columns(rounded(*rates)).select(list(EXPECTED_SCHEMA)).sort("sample")
