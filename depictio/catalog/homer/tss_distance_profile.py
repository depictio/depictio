"""Where each sample's peaks sit relative to the nearest TSS, pre-binned.

``homer/annotate_peaks.py`` gives one row per peak with a signed
``distance_to_tss``; this recipe turns that cloud into a curve by counting the
peaks of every sample in fixed-width bins across a window centred on the start
site. Drawn as a profile with a marker at 0, it is the standard promoter-
enrichment read: a sharp central spike means the peaks are promoter-bound, a
flat curve means they are distributed across the gene body and intergenic space.

Why the binning happens here rather than in a histogram figure
--------------------------------------------------------------
A histogram re-bins on every render and cannot carry a reference marker, a
shaded promoter window or log axes without a hand-written code-mode figure --
which is exactly what the chipseq and atacseq templates were carrying, once
each. Binning in the recipe hands the same picture to the ``profile`` kind,
which owns those three settings, and shrinks the frame from one row per peak
(hundreds of thousands) to one row per sample and bin.

The window is clipped at ``CLIP_BP`` because HOMER reports the distance to the
nearest TSS however far away it is, and the tail runs to whole megabases on
intergenic peaks: everything past the clip is counted in the outermost bin
rather than dropped, so the fractions still sum to 1 per sample.

Input: the ``homer_annotated_peaks`` data collection, read through ``dc_ref``
rather than the raw files so the two do not parse ``annotatePeaks.txt`` twice
and cannot disagree on what a sample is.

Output schema:
    sample : Utf8             sample the peaks were called in
    distance_to_tss : Int64   centre of the bin, signed bp from the TSS
    peak_count : Int64        peaks of that sample falling in the bin
    fraction : Float64        peak_count over the sample's peaks
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads: the tidy per-peak annotation table.
SOURCE_DC_TAG = "homer_annotated_peaks"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="peaks", dc_ref=SOURCE_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "distance_to_tss": pl.Int64,
    "peak_count": pl.Int64,
    "fraction": pl.Float64,
}

#: Half-width of the plotted window, in bp. Peaks further out are folded into
#: the outermost bin rather than dropped.
CLIP_BP = 10_000

#: Bin width, in bp. 250 over a +/-10 kb window is 80 bins, the resolution the
#: hand-written histograms this replaces were using.
BIN_BP = 250


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count each sample's peaks in fixed-width bins around the TSS."""
    peaks = sources["peaks"]
    if peaks.is_empty():
        raise ValueError("homer_tss_distance_profile: the annotated peaks are empty")
    missing = {"sample", "distance_to_tss"} - set(peaks.columns)
    if missing:
        raise ValueError(
            f"homer_tss_distance_profile: {SOURCE_DC_TAG} has no {sorted(missing)} column; "
            f"got {peaks.columns}"
        )

    distance = pl.col("distance_to_tss").cast(pl.Int64, strict=False)
    clipped = (
        peaks.select(pl.col("sample").cast(pl.Utf8), distance)
        .drop_nulls()
        .with_columns(pl.col("distance_to_tss").clip(-CLIP_BP, CLIP_BP))
    )
    if clipped.is_empty():
        raise ValueError("homer_tss_distance_profile: no peak carried a distance to a TSS")

    # Floor-divide onto the bin grid, then move to the bin centre so the curve
    # is drawn through the middle of each bin rather than its left edge.
    binned = (
        clipped.with_columns(
            ((pl.col("distance_to_tss") // BIN_BP) * BIN_BP + BIN_BP // 2).alias("distance_to_tss")
        )
        .group_by(["sample", "distance_to_tss"])
        .agg(pl.len().alias("peak_count"))
    )
    return (
        binned.with_columns(
            (pl.col("peak_count") / pl.col("peak_count").sum().over("sample")).alias("fraction")
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "distance_to_tss"])
    )
