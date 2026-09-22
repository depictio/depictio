"""Control-FREEC ratio windows as a canonical ``cnv_profile`` table.

Control-FREEC works on fixed-size windows and writes one row per window to
``<sample>_ratio.txt``, tab separated with a header row (Control-FREEC
documentation, "Output files")::

    Chromosome  Start  Ratio  MedianRatio  CopyNumber

and, when a BAF was computed from a SNV file, four more columns on the same
rows::

    BAF  estimatedBAF  Genotype  UncertaintyOfGT

``Ratio`` is the window's normalised copy ratio and ``MedianRatio`` the median
ratio of the *segment* the window belongs to, written out on every window that
segment covers. Control-FREEC therefore publishes no segment file of its own:
a maximal run of windows sharing a ``MedianRatio`` and a ``CopyNumber`` **is**
one segment, and this recipe recovers them by run-length encoding those two
columns. Both the windows (``segment = "bin"``) and the recovered segments
(``segment = "segment"``) go into the same long table.

Control-FREEC writes ``-1`` for a value it could not assess, in both ``Ratio``
and ``BAF``; those become nulls rather than a ratio of minus one.

The file carries no sample column, so the raw data collection is a **scan**
(``include_file_paths``) and the sample is recovered from the
``variant_calling/controlfreec/<sample>/`` directory nf-core/sarek publishes
into.

A template reusing this recipe declares one raw scan data collection::

    # controlfreec_ratio_raw
    regex_config: {pattern: 'variant_calling/controlfreec/[^/]+/[^/]+_ratio\\.txt$'}
    dc_specific_properties:
      format: CSV
      polars_kwargs: {separator: "\\t", include_file_paths: source_path}

``optional: true`` on a germline-only run, which publishes no
``variant_calling/controlfreec/`` directory at all.

Output schema: the canonical cnv_profile contract, see
``depictio/recipes/lib/cnv_profile.py``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cnv_profile import (
    BIN_ROW,
    CNV_PROFILE_SCHEMA,
    SEGMENT_ROW,
    decimate_bins,
    finalise,
    runs,
    safe_log2,
)

RATIO_DC_TAG = "controlfreec_ratio_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="ratio", dc_ref=RATIO_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = CNV_PROFILE_SCHEMA
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: nf-core/sarek writes `variant_calling/controlfreec/<sample>/<sample>_ratio.txt`.
_SAMPLE_RE = r"controlfreec/([^/]+)/[^/]*$"

#: Control-FREEC's "not assessed" sentinel, in both Ratio and BAF.
_NOT_ASSESSED = -1.0

#: Window size used when a chromosome has a single window and the step cannot
#: be measured. Control-FREEC's own default for WGS.
_FALLBACK_WINDOW = 50_000


def _window_size(df: pl.DataFrame) -> int:
    """The window step, measured as the most common gap between starts.

    Control-FREEC does not write the window end, and the size is a run
    parameter rather than a constant, so it is read off the data instead of
    assumed.
    """
    gaps = (
        df.sort(["sample", "chrom", "start"])
        .with_columns(
            (pl.col("start") - pl.col("start").shift(1).over(["sample", "chrom"])).alias("_gap")
        )
        .filter(pl.col("_gap") > 0)
        .get_column("_gap")
    )
    if gaps.len() == 0:
        return _FALLBACK_WINDOW
    modal = gaps.mode()
    return int(modal.min()) if modal.len() else _FALLBACK_WINDOW


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Windows plus the segments their MedianRatio runs encode."""
    df = sources["ratio"]

    missing = [c for c in ("Chromosome", "Start", "Ratio") if c not in df.columns]
    if missing:
        raise ValueError(
            f"controlfreec_cnv_ratio: the _ratio.txt input lacks columns {missing}; "
            f"got {df.columns}"
        )
    if "sample" not in df.columns and "source_path" not in df.columns:
        raise ValueError(
            "controlfreec_cnv_ratio: the input has neither a 'sample' nor a "
            "'source_path' column, so the raw data collection must be scanned with "
            "polars_kwargs.include_file_paths"
        )

    sample = (
        pl.col("sample").cast(pl.Utf8)
        if "sample" in df.columns
        else pl.col("source_path").str.extract(_SAMPLE_RE, 1).cast(pl.Utf8)
    )

    def _assessed(name: str) -> pl.Expr:
        value = pl.col(name).cast(pl.Float64, strict=False)
        return pl.when(value == _NOT_ASSESSED).then(None).otherwise(value)

    has_baf = "BAF" in df.columns
    has_cn = "CopyNumber" in df.columns
    has_median = "MedianRatio" in df.columns

    base = df.select(
        sample.alias("sample"),
        pl.col("Chromosome").cast(pl.Utf8).alias("chrom"),
        pl.col("Start").cast(pl.Int64, strict=False).alias("start"),
        _assessed("Ratio").alias("_ratio"),
        (
            _assessed("MedianRatio").alias("_median_ratio")
            if has_median
            else pl.lit(None, dtype=pl.Float64).alias("_median_ratio")
        ),
        (
            pl.col("CopyNumber").cast(pl.Int64, strict=False).alias("_copy_number")
            if has_cn
            else pl.lit(None, dtype=pl.Int64).alias("_copy_number")
        ),
        (
            _assessed("BAF").alias("_baf")
            if has_baf
            else pl.lit(None, dtype=pl.Float64).alias("_baf")
        ),
    ).filter(pl.col("chrom").is_not_null() & pl.col("start").is_not_null())

    if base.height == 0:
        raise ValueError("controlfreec_cnv_ratio: no usable window rows in the _ratio.txt input")

    window = _window_size(base)
    base = base.sort(["sample", "chrom", "start"]).with_columns(
        (pl.col("start") + window - 1).alias("end")
    )

    bins = decimate_bins(
        base.select(
            "sample",
            "chrom",
            "start",
            "end",
            safe_log2(pl.col("_ratio")).alias("log2"),
            pl.col("_baf").alias("baf"),
            pl.col("_copy_number").alias("copy_number"),
            pl.lit(BIN_ROW).alias("segment"),
            pl.lit(None, dtype=pl.Utf8).alias("label"),
            pl.lit(None, dtype=pl.Float64).alias("depth"),
        )
    )

    # A run of windows sharing the segment-level MedianRatio and CopyNumber is
    # the segment Control-FREEC called. Never decimated: the call is what the
    # reader takes off the plot.
    segments = (
        runs(base, ["_median_ratio", "_copy_number"])
        .group_by(["_run"], maintain_order=True)
        .agg(
            pl.col("sample").first().alias("sample"),
            pl.col("chrom").first().alias("chrom"),
            pl.col("start").min().alias("start"),
            pl.col("end").max().alias("end"),
            pl.col("_median_ratio").first().alias("_median_ratio"),
            pl.col("_copy_number").first().alias("copy_number"),
            pl.col("_baf").median().alias("baf"),
        )
        .drop("_run")
        .with_columns(
            safe_log2(pl.col("_median_ratio")).alias("log2"),
            pl.lit(SEGMENT_ROW).alias("segment"),
            pl.when(pl.col("copy_number").is_null())
            .then(None)
            .otherwise(pl.concat_str([pl.lit("CN "), pl.col("copy_number").cast(pl.Utf8)]))
            .alias("label"),
            pl.lit(None, dtype=pl.Float64).alias("depth"),
        )
        .drop("_median_ratio")
    )

    return finalise(pl.concat([bins, segments], how="diagonal_relaxed"))
