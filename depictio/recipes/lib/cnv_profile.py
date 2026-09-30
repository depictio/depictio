"""Shared building blocks for the canonical ``cnv_profile`` recipes.

Three somatic callers publish a copy-number profile in three different shapes
(CNVkit bins + segments, ASCAT allele-specific segments, Control-FREEC ratio
windows), and all three land on the same canonical row contract::

    sample : Utf8          the tumour sample the profile belongs to
    chrom : Utf8           chromosome, as the caller spells it
    start : Int64          start of the bin or segment, bp
    end : Int64            end of the bin or segment, bp
    log2 : Float64         log2 copy ratio against a diploid baseline
    baf : Float64          B-allele frequency, null when the caller has none
    copy_number : Int64    absolute copy number, null when not called
    segment : Utf8         row type: "bin" or "segment"
    label : Utf8           short hover label (gene, allelic state, CN call)
    depth : Float64        read depth behind the row, null when unavailable

The ``segment`` column is what lets one long data collection carry both the
evidence (bins) and the call (segments): the renderer draws a "bin" row as a
point and a "segment" row as a thick horizontal stroke.

Shared here rather than copied because the three recipes need exactly the same
decimation and the same log2 floor, and recipes may not import each other.
"""

from __future__ import annotations

import polars as pl

#: The canonical column order every cnv_profile recipe returns.
CNV_PROFILE_COLUMNS: list[str] = [
    "sample",
    "chrom",
    "start",
    "end",
    "log2",
    "baf",
    "copy_number",
    "segment",
    "label",
    "depth",
]

#: The canonical output schema, shared by all three recipes' EXPECTED_SCHEMA.
CNV_PROFILE_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "log2": pl.Float64,
    "baf": pl.Float64,
    "copy_number": pl.Int64,
    "segment": pl.Utf8,
    "label": pl.Utf8,
    "depth": pl.Float64,
}

#: Row-type values of the ``segment`` role.
BIN_ROW = "bin"
SEGMENT_ROW = "segment"

#: Floor applied to log2 of a zero ratio. A homozygous deletion has ratio 0,
#: whose log2 is minus infinity: unplottable, and it would blow the y axis out
#: on its own. CNVkit itself clamps (to -20); -3.0 is below the loss threshold
#: any caller uses while staying inside the renderer's default axis limit.
LOG2_FLOOR = -3.0

#: Bins kept by default. A whole-exome CNVkit run emits ~2e5 .cnr rows per
#: sample and a Control-FREEC ratio file ~1e6 windows; past this the extra rows
#: cost storage and transfer without changing a single drawn pixel, because the
#: renderer decimates again on the way into the figure.
DEFAULT_MAX_BINS = 50_000


def safe_log2(ratio: pl.Expr) -> pl.Expr:
    """log2 of a copy ratio, with the zero and negative cases handled.

    Control-FREEC writes ``-1`` for "not assessed" and ``0`` for a homozygous
    deletion; ASCAT can call total copy number 0. Negative ratios become null
    (nothing to plot), zero becomes :data:`LOG2_FLOOR`.
    """
    return (
        pl.when(ratio.is_null() | (ratio < 0))
        .then(None)
        .when(ratio == 0)
        .then(pl.lit(LOG2_FLOOR))
        .otherwise(ratio.log(2))
        .cast(pl.Float64)
    )


def finalise(df: pl.DataFrame) -> pl.DataFrame:
    """Cast to the canonical schema, add any missing optional column, order.

    Every recipe ends with this, so the three of them cannot drift on dtype or
    column order. Rows with no usable coordinate or no log2 are dropped: they
    can neither be placed on the genome axis nor drawn.
    """
    for name, dtype in CNV_PROFILE_SCHEMA.items():
        if name not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=dtype).alias(name))
    df = df.with_columns(
        [pl.col(name).cast(dtype, strict=False) for name, dtype in CNV_PROFILE_SCHEMA.items()]
    )
    return (
        df.filter(
            pl.col("chrom").is_not_null()
            & pl.col("start").is_not_null()
            & pl.col("log2").is_not_null()
        )
        .select(CNV_PROFILE_COLUMNS)
        .sort(["sample", "segment", "chrom", "start"])
    )


def decimate_bins(bins: pl.DataFrame, max_bins: int | None = None) -> pl.DataFrame:
    """Average consecutive bins down to at most ``max_bins`` rows per sample.

    Windows never cross a sample or a chromosome boundary, and the emitted row
    keeps the window's full span (start of the first bin, end of the last), so
    the decimated track still covers the same genome. ``log2``, ``baf``,
    ``copy_number`` and ``depth`` are means over the non-null values of the
    window; a window whose BAF is null throughout stays null rather than
    collapsing to zero.

    Only ever applied to bins. A called segment is the answer the reader is
    taking off the plot, so the segments are passed through untouched.

    ``max_bins`` defaults to :data:`DEFAULT_MAX_BINS`, read at call time so a
    caller (or a test) can move the cap by setting the module attribute.
    """
    cap = DEFAULT_MAX_BINS if max_bins is None else max_bins
    if bins.height == 0 or cap <= 0 or bins.height <= cap:
        return bins

    ordered = bins.sort(["sample", "chrom", "start"])
    # One window index per group of `factor` consecutive bins. The factor is
    # global rather than per chromosome so a small contig is not coarsened as
    # hard as a large one just because it has its own group.
    factor = max(1, -(-ordered.height // cap))
    windowed = ordered.with_columns(
        (pl.int_range(pl.len(), dtype=pl.Int64).over(["sample", "chrom"]) // factor).alias(
            "_window"
        )
    )
    return (
        windowed.group_by(["sample", "chrom", "_window"], maintain_order=True)
        .agg(
            pl.col("start").min().alias("start"),
            pl.col("end").max().alias("end"),
            pl.col("log2").mean().alias("log2"),
            pl.col("baf").mean().alias("baf"),
            pl.col("copy_number").mean().round(0).alias("copy_number"),
            pl.col("segment").first().alias("segment"),
            pl.col("label").first().alias("label"),
            pl.col("depth").mean().alias("depth"),
        )
        .drop("_window")
    )


def runs(df: pl.DataFrame, value_cols: list[str]) -> pl.DataFrame:
    """Tag maximal runs of consecutive rows sharing ``value_cols``.

    Adds a ``_run`` column that increments whenever the sample, the chromosome
    or any of ``value_cols`` changes from the previous row. This is how the
    Control-FREEC recipe recovers segments: the caller writes the segment-level
    value (``MedianRatio``) on every window it covers rather than publishing the
    segments separately, so a run of identical values *is* one segment.

    The frame must already be sorted by sample, chrom, start.
    """
    keys = ["sample", "chrom", *value_cols]
    changed = pl.lit(False)
    for key in keys:
        col = pl.col(key)
        changed = changed | (col != col.shift(1)) | (col.is_null() != col.shift(1).is_null())
    return df.with_columns(changed.fill_null(True).cum_sum().alias("_run"))
