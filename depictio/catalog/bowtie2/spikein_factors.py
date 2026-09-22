"""Spike-in normalisation factors, from the two Bowtie 2 log sets of a run.

A CUT&RUN or CUT&Tag experiment carries a fixed amount of carrier DNA from a
second organism through every library. The libraries are aligned twice, once
against the target genome and once against that spike-in genome, and the
spike-in depth is what says how much material each library really held: a
library with twice the spike-in depth of another was sequenced twice as deep
for the same amount of chromatin, and its coverage has to be divided by that
before two samples can be compared.

nf-core/cutandrun turns the spike-in depth into a single multiplier,

    scale_factor = normalisation_c / spikein_aligned_pairs

with ``normalisation_c`` defaulting to 10000, and applies it to the bedGraph
every downstream caller reads. It does not publish the factor as a table, so
this recipe recomputes it from the logs the pipeline does publish.

Both log sets are read through ONE scan data collection: the file names are
``<sample>.bowtie2.log`` for the target genome and ``<sample>.spikein.bowtie2.log``
for the spike-in, so a single regex on the file name picks up both and the
``.spikein.`` infix is what separates them. Only a scan carries the file path
into the frame, which is why the collection is declared with
``include_file_paths`` and the sample is read off the path. A template reusing
this output declares::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*\\.bowtie2\\.log$'}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          has_header: false
          new_columns: [line]
          include_file_paths: source_path
          infer_schema_length: 0

Bowtie 2 writes its summary to stderr as plain prose, not as a table, so the
numbers are pulled out with regular expressions. Paired-end runs report
``aligned concordantly exactly 1 time`` / ``>1 times`` over read PAIRS;
single-end runs report ``aligned exactly 1 time`` / ``>1 times`` over reads.
Both are handled, and ``total_pairs`` is the unit the log itself counts in.

Output schema:
    sample : Utf8               sample both alignments belong to
    total_pairs : Int64         read pairs (or reads, single-end) that entered both alignments
    target_aligned : Int64      pairs aligned concordantly to the target genome
    target_align_rate : Float64 Bowtie 2's own overall alignment rate against the target (percent)
    spikein_aligned : Int64     pairs aligned concordantly to the spike-in genome
    spikein_align_rate : Float64 same rate against the spike-in genome (percent)
    spikein_fraction : Float64  spikein_aligned / total_pairs, the carrier share of the library
    target_per_spikein : Float64 target_aligned / spikein_aligned, the enrichment ratio
    scale_factor : Float64      normalisation_c / spikein_aligned, the multiplier applied to the bedGraph
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads (see module docstring).
RAW_DC_TAG = "bowtie2_logs_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="logs", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_pairs": pl.Int64,
    "target_aligned": pl.Int64,
    "target_align_rate": pl.Float64,
    "spikein_aligned": pl.Int64,
    "spikein_align_rate": pl.Float64,
    "spikein_fraction": pl.Float64,
    "target_per_spikein": pl.Float64,
    "scale_factor": pl.Float64,
}

#: nf-core/cutandrun's `--normalisation_c` default: the constant the spike-in
#: depth is divided into. Changing it rescales every factor by the same amount,
#: so the ranking between samples is unaffected.
NORMALISATION_C = 10_000.0

# `<sample>.spikein.bowtie2.log` (spike-in genome) or `<sample>.bowtie2.log`
# (target genome). The infix is what tells the two sets apart.
_SPIKEIN_RE = r"^(?P<sample>.+?)\.spikein\.bowtie2\.log$"
_TARGET_RE = r"^(?P<sample>.+?)\.bowtie2\.log$"

# Bowtie 2 prints its summary as prose; these pull the counts back out.
_TOTAL_RE = r"(\d+)\s+reads;\s+of these"
_RATE_RE = r"([\d.]+)%\s+overall alignment rate"
_CONCORDANT_ONE_RE = r"(\d+)\s+\([\d.]+%\)\s+aligned concordantly exactly 1 time"
_CONCORDANT_MULTI_RE = r"(\d+)\s+\([\d.]+%\)\s+aligned concordantly >1 times"
_SINGLE_ONE_RE = r"(\d+)\s+\([\d.]+%\)\s+aligned exactly 1 time"
_SINGLE_MULTI_RE = r"(\d+)\s+\([\d.]+%\)\s+aligned >1 times"


def _int_from(report: pl.Expr, pattern: str) -> pl.Expr:
    """The first capture group of `pattern` in `report`, as an Int64 or null."""
    return report.str.extract(pattern, 1).cast(pl.Int64, strict=False)


def _aligned(report: pl.Expr) -> pl.Expr:
    """Uniquely-plus-multiply aligned pairs, paired-end first then single-end."""
    concordant = _int_from(report, _CONCORDANT_ONE_RE).fill_null(0) + _int_from(
        report, _CONCORDANT_MULTI_RE
    ).fill_null(0)
    single = _int_from(report, _SINGLE_ONE_RE).fill_null(0) + _int_from(
        report, _SINGLE_MULTI_RE
    ).fill_null(0)
    return pl.when(concordant > 0).then(concordant).otherwise(single).cast(pl.Int64)


def _reports(df: pl.DataFrame) -> pl.DataFrame:
    """Glue each log file's lines back into one text blob per file."""
    text = pl.col("line").cast(pl.Utf8).fill_null("")
    return (
        df.with_columns(
            pl.col("source_path").str.replace_all(r"^.*/", "").alias("file_name"),
            text.alias("line"),
        )
        .group_by("file_name")
        .agg(pl.col("line").str.join("\n").alias("report"))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pair the target and spike-in logs of each sample and derive the factor."""
    df = sources["logs"]
    if "source_path" not in df.columns:
        raise ValueError(
            "bowtie2_spikein_factors: input has no 'source_path' column. The raw "
            "data collection must be scanned with polars_kwargs.include_file_paths"
        )
    if "line" not in df.columns:
        raise ValueError(
            "bowtie2_spikein_factors: input has no 'line' column. The raw data "
            "collection must be read with new_columns: [line]"
        )

    reports = _reports(df)
    file_name = pl.col("file_name")
    reports = reports.with_columns(
        file_name.str.extract(_SPIKEIN_RE, 1).alias("spikein_sample"),
        file_name.str.extract(_TARGET_RE, 1).alias("target_sample"),
        _int_from(pl.col("report"), _TOTAL_RE).alias("total_pairs"),
        pl.col("report").str.extract(_RATE_RE, 1).cast(pl.Float64, strict=False).alias("rate"),
        _aligned(pl.col("report")).alias("aligned"),
    )

    spikein = reports.filter(pl.col("spikein_sample").is_not_null()).select(
        pl.col("spikein_sample").alias("sample"),
        pl.col("total_pairs"),
        pl.col("aligned").alias("spikein_aligned"),
        pl.col("rate").alias("spikein_align_rate"),
    )
    # `<sample>.bowtie2.log` also matches `<sample>.spikein.bowtie2.log` with
    # `sample` ending in `.spikein`, so the spike-in files are removed by name.
    target = (
        reports.filter(
            pl.col("target_sample").is_not_null() & pl.col("spikein_sample").is_null()
        ).select(
            pl.col("target_sample").alias("sample"),
            pl.col("total_pairs").alias("target_total_pairs"),
            pl.col("aligned").alias("target_aligned"),
            pl.col("rate").alias("target_align_rate"),
        )
    ).unique(subset="sample")
    spikein = spikein.unique(subset="sample")

    if target.is_empty():
        raise ValueError(
            "bowtie2_spikein_factors: no '<sample>.bowtie2.log' target-genome log was read"
        )
    if spikein.is_empty():
        raise ValueError(
            "bowtie2_spikein_factors: no '<sample>.spikein.bowtie2.log' spike-in log "
            "was read, so no scale factor can be derived"
        )

    merged = target.join(spikein, on="sample", how="inner")
    if merged.is_empty():
        raise ValueError(
            "bowtie2_spikein_factors: no sample has both a target and a spike-in log; "
            "the two sets must share the '<sample>' prefix"
        )

    total = pl.coalesce([pl.col("total_pairs"), pl.col("target_total_pairs")]).cast(pl.Int64)
    positive_spikein = pl.col("spikein_aligned") > 0
    merged = merged.with_columns(
        total.alias("total_pairs"),
        pl.when(total > 0)
        .then((pl.col("spikein_aligned") / total).round(6))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("spikein_fraction"),
        pl.when(positive_spikein)
        .then((pl.col("target_aligned") / pl.col("spikein_aligned")).round(2))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("target_per_spikein"),
        # A library with no spike-in read at all cannot be normalised: the
        # factor stays null instead of becoming an infinity that would then
        # silently dominate every mean on the dashboard.
        pl.when(positive_spikein)
        .then((pl.lit(NORMALISATION_C) / pl.col("spikein_aligned")).round(4))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("scale_factor"),
    )
    return merged.select(list(EXPECTED_SCHEMA)).sort("sample")
