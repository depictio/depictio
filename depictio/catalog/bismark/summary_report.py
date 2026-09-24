"""Bismark's own run-level summary table, one row per library.

``bismark2summary`` walks the alignment, deduplication and methylation-extraction
reports of a whole run and writes ``bismark_summary_report.txt``: a single
tab-separated table, one row per BAM, holding the counts each of those reports
states separately. It is the only file in a methylseq run that puts the read
funnel and the cytosine counts side by side, which is exactly what a run-level
glance strip needs, and until now nothing read it.

The raw columns are counts. What a reader asks of them is ratios, so the recipe
derives them here rather than leaving every dashboard to recompute them:

* ``pct_aligned`` / ``pct_duplicate``: the two yields the funnel turns on.
* ``pct_cpg_methylation`` and its CHG / CHH siblings: methylation level per
  cytosine context, the same quantity the splitting report gives, recomputed
  from this file so a dashboard can show the funnel and the contexts off one
  collection.
* ``conversion_efficiency_pct`` = ``100 - pct_chh_methylation``. Mammalian CHH
  methylation is biologically near zero, so an apparent CHH call is an
  unconverted cytosine: its complement is the bisulfite conversion rate every
  bisulfite protocol reports. Below ~98 % the CpG calls inherit the same
  false-positive rate and the run is not usable as a methylome.
* ``cpgs_called``: methylated plus unmethylated CpG calls, the last step of the
  reads-to-methylome funnel an ``attrition`` card draws.

The design is joined in from the sample hub when the template declares one,
under the repo-wide ``samples`` tag, so a figure over this collection can colour
by the factor the run compares rather than by the sample id, which colours seven
bars in seven colours and says nothing. The join is optional: without a hub the
columns are null and every count is still there.

Column names in the file are Bismark's, including the lower-cased ``chgs``
(a typo in Bismark's own writer), so the header is matched case-insensitively.

Output schema:
    sample : Utf8                       library the row belongs to
    total_reads : Int64                 read pairs (or reads) Bismark analysed
    aligned_reads : Int64               reads with a unique best alignment
    unaligned_reads : Int64             reads with no alignment
    ambiguous_reads : Int64             reads that mapped to more than one place
    duplicate_reads : Int64             alignments removed as PCR duplicates
    unique_reads : Int64                alignments kept for extraction
    total_cs : Int64                    cytosines seen in any context
    methylated_cpg : Int64              methylated CpG calls
    unmethylated_cpg : Int64            unmethylated CpG calls
    methylated_chg : Int64              methylated CHG calls
    unmethylated_chg : Int64            unmethylated CHG calls
    methylated_chh : Int64              methylated CHH calls
    unmethylated_chh : Int64            unmethylated CHH calls
    cpgs_called : Int64                 methylated_cpg + unmethylated_cpg
    pct_aligned : Float64               aligned_reads / total_reads * 100
    pct_duplicate : Float64             duplicate_reads / aligned_reads * 100
    pct_cpg_methylation : Float64       methylated / called CpGs * 100
    pct_chg_methylation : Float64       methylated / called CHGs * 100
    pct_chh_methylation : Float64       methylated / called CHHs * 100
    conversion_efficiency_pct : Float64 100 - pct_chh_methylation
    <design columns> : Utf8             every factor of the sample hub (the run's
                                        METADATA_FILE), when it declares any
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bismark_names import hub_factor_columns
from depictio.recipes.lib.sample_hub import annotate_from_hub

SAMPLES_DC_TAG = "samples"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        glob_pattern="**/bismark_summary_report.txt",
        format="TSV",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(ref="samples", dc_ref=SAMPLES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_reads": pl.Int64,
    "aligned_reads": pl.Int64,
    "unaligned_reads": pl.Int64,
    "ambiguous_reads": pl.Int64,
    "duplicate_reads": pl.Int64,
    "unique_reads": pl.Int64,
    "total_cs": pl.Int64,
    "methylated_cpg": pl.Int64,
    "unmethylated_cpg": pl.Int64,
    "methylated_chg": pl.Int64,
    "unmethylated_chg": pl.Int64,
    "methylated_chh": pl.Int64,
    "unmethylated_chh": pl.Int64,
    "cpgs_called": pl.Int64,
    "pct_aligned": pl.Float64,
    "pct_duplicate": pl.Float64,
    "pct_cpg_methylation": pl.Float64,
    "pct_chg_methylation": pl.Float64,
    "pct_chh_methylation": pl.Float64,
    "conversion_efficiency_pct": pl.Float64,
}
# Design columns are run-dependent (the sample hub's factors); validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# The BAM name in the `File` column records the trimming and alignment stages;
# the sample is what is left of it. `bismark_[a-z0-9]+` rather than
# `bismark_bt2` so the hisat2 route's `_bismark_hisat2_` names strip too. The
# pattern is handed to polars (the Rust `regex` crate), so the case-insensitive
# flag is inline rather than a Python `re` flag.
_SUFFIX_PATTERN = r"(?i)(_\d+)?(_val_\d+)?_bismark_[a-z0-9]+_(pe|se)\.bam$"

# Bismark's header, lower-cased and stripped, mapped to the output column. The
# lower-cased "chgs" is Bismark's own spelling, not a transcription slip.
_HEADER_MAP: dict[str, str] = {
    "file": "file",
    "total reads": "total_reads",
    "aligned reads": "aligned_reads",
    "unaligned reads": "unaligned_reads",
    "ambiguously aligned reads": "ambiguous_reads",
    "duplicate reads (removed)": "duplicate_reads",
    "unique reads (remaining)": "unique_reads",
    "total cs": "total_cs",
    "methylated cpgs": "methylated_cpg",
    "unmethylated cpgs": "unmethylated_cpg",
    "methylated chgs": "methylated_chg",
    "unmethylated chgs": "unmethylated_chg",
    "methylated chhs": "methylated_chh",
    "unmethylated chhs": "unmethylated_chh",
}


def _pct(numerator: pl.Expr, denominator: pl.Expr) -> pl.Expr:
    """``numerator / denominator * 100``, null rather than an error on a zero."""
    safe = pl.when(denominator > 0).then(denominator).otherwise(None)
    return (numerator / safe * 100.0).cast(pl.Float64)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename Bismark's header, cast the counts and derive the ratios."""
    raw = sources["summary"]
    if raw.is_empty():
        raise ValueError("bismark_summary_report: bismark_summary_report.txt holds no row")
    samples = sources.get("samples")
    factors = hub_factor_columns(samples)

    renames = {
        c: _HEADER_MAP[c.strip().lower()] for c in raw.columns if c.strip().lower() in _HEADER_MAP
    }
    missing = set(_HEADER_MAP.values()) - set(renames.values())
    if missing:
        raise ValueError(
            f"bismark_summary_report: columns {sorted(missing)} are absent from the summary "
            f"table, got {raw.columns}"
        )

    frame = raw.rename(renames).with_columns(
        pl.col("file").cast(pl.Utf8).str.replace(_SUFFIX_PATTERN, "").alias("sample"),
        *[
            pl.col(name).cast(pl.Float64, strict=False).cast(pl.Int64).alias(name)
            for name in _HEADER_MAP.values()
            if name != "file"
        ],
    )

    return (
        frame.with_columns(
            (pl.col("methylated_cpg") + pl.col("unmethylated_cpg")).alias("cpgs_called"),
            _pct(pl.col("aligned_reads"), pl.col("total_reads")).alias("pct_aligned"),
            _pct(pl.col("duplicate_reads"), pl.col("aligned_reads")).alias("pct_duplicate"),
            _pct(
                pl.col("methylated_cpg"), pl.col("methylated_cpg") + pl.col("unmethylated_cpg")
            ).alias("pct_cpg_methylation"),
            _pct(
                pl.col("methylated_chg"), pl.col("methylated_chg") + pl.col("unmethylated_chg")
            ).alias("pct_chg_methylation"),
            _pct(
                pl.col("methylated_chh"), pl.col("methylated_chh") + pl.col("unmethylated_chh")
            ).alias("pct_chh_methylation"),
        )
        .with_columns(
            (100.0 - pl.col("pct_chh_methylation"))
            .cast(pl.Float64)
            .alias("conversion_efficiency_pct")
        )
        .pipe(annotate_from_hub, samples, factors, left_on="sample")
        .select(*EXPECTED_SCHEMA, *factors)
        .sort("sample")
    )
