"""Summit-centred aggregate of the MACS2 peak calls, one curve per sample.

A metagene around the summits would need the coverage tracks
(``computeMatrix reference-point`` over the bigWigs), and those are neither
published as a table by the pipeline nor mirrored with the peak calls. What the
narrowPeak files DO carry is every peak's interval and its summit, so this
recipe aggregates the peak calls themselves around the summits, on a fixed bin
grid centred on 0 (the summit):

``peak_footprint``
    Fraction of the sample's peaks whose called interval covers that offset
    from their own summit: 1 at the summit, then falling as the narrower peaks
    end. It is the average shape of a call, and where it crosses 0.5 is the
    median half-width on that side. A sharp transcription-factor sample falls
    within a few hundred bp; a broad histone mark stays high for kilobases.

``neighbour_summit_density``
    Summits called in the OTHER samples of the run, per anchor summit and per
    kb, in that bin. A central spike means the other libraries place their
    summits on this sample's summits (replicates agree, or two factors share
    sites); a flat curve at the genome-wide background means they do not. It is
    counted over every other sample of the run, so a run mixing antibodies
    shows the shared sites diluted by the unrelated ones: filter the collection
    by sample to read one comparison.

Neither column is a read-coverage signal, and the tile text must not call it
one. The bins are pre-computed here (one row per sample and bin, 81 per sample)
so the ``profile`` kind draws them with its marker at 0 and its derivative
mode, instead of a histogram re-binning hundreds of thousands of peaks.

Input: the ``macs2_peaks`` data collection, read through ``dc_ref`` so the
narrowPeak files are parsed once and the two tables agree on what a sample is.
``--broad`` calls (``*_peaks.broadPeak``) carry no summit and are not read.

Output schema:
    sample : Utf8                       sample the anchor summits were called in
    offset_bp : Int64                   bin centre, signed bp from the summit
    n_summits : Int64                   anchor summits of that sample
    peak_footprint : Float64            share of the sample's peaks covering the offset
    neighbour_summit_density : Float64  other samples' summits per anchor per kb
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads: the tidy per-peak narrowPeak table.
SOURCE_DC_TAG = "macs2_peaks"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="peaks", dc_ref=SOURCE_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "offset_bp": pl.Int64,
    "n_summits": pl.Int64,
    "peak_footprint": pl.Float64,
    "neighbour_summit_density": pl.Float64,
}

#: Half-width of the window around the summit, in bp.
HALF_WINDOW_BP = 2_000

#: Bin width, in bp. 50 over +/-2 kb is 81 bins centred on the summit.
BIN_BP = 50

_REQUIRED = ("sample", "chr", "start", "end", "summit")


def _bin_centres() -> np.ndarray:
    return np.arange(-HALF_WINDOW_BP, HALF_WINDOW_BP + 1, BIN_BP, dtype=np.int64)


def _footprint(left: np.ndarray, right: np.ndarray, centres: np.ndarray) -> np.ndarray:
    """Share of intervals [left, right) (summit-relative) that cover each centre."""
    left = np.sort(left)
    right = np.sort(right)
    started = np.searchsorted(left, centres, side="right")
    ended = np.searchsorted(right, centres, side="right")
    return (started - ended) / max(len(left), 1)


def _neighbour_counts(
    anchors: np.ndarray, own: np.ndarray, every: np.ndarray, edges: np.ndarray
) -> np.ndarray:
    """Summits of the other samples falling in each bin, summed over the anchors.

    ``own`` and ``every`` are sorted summit positions on one chromosome, of the
    anchor's sample and of the whole run. Counting ``every`` minus ``own`` below
    each edge drops the anchor's own sample, the anchor included.
    """
    shifted = (anchors[:, None] + edges[None, :]).ravel()
    below = np.searchsorted(every, shifted, side="left") - np.searchsorted(
        own, shifted, side="left"
    )
    cumulative = below.reshape(len(anchors), len(edges)).sum(axis=0)
    return np.diff(cumulative)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Aggregate every sample's peak calls on a summit-centred bin grid."""
    peaks = sources["peaks"]
    missing = [c for c in _REQUIRED if c not in peaks.columns]
    if missing:
        raise ValueError(
            f"macs2_summit_profile: {SOURCE_DC_TAG} has no {missing} column; got {peaks.columns}"
        )
    peaks = (
        peaks.select(
            pl.col("sample").cast(pl.Utf8),
            pl.col("chr").cast(pl.Utf8),
            pl.col("start").cast(pl.Int64, strict=False),
            pl.col("end").cast(pl.Int64, strict=False),
            pl.col("summit").cast(pl.Int64, strict=False),
        )
        .drop_nulls()
        # `summit` is 1-based and `start` 0-based: the summit base sits at
        # summit - 1 in the half-open [start, end) the interval describes.
        .with_columns((pl.col("summit") - 1).alias("summit0"))
    )
    if peaks.is_empty():
        raise ValueError("macs2_summit_profile: the peak table is empty")

    centres = _bin_centres()
    edges = np.append(centres - BIN_BP // 2, centres[-1] + BIN_BP - BIN_BP // 2)
    per_kb = BIN_BP / 1000.0

    every_by_chr = {
        chrom: np.sort(frame["summit0"].to_numpy()) for (chrom,), frame in peaks.group_by(["chr"])
    }

    rows: list[pl.DataFrame] = []
    for (sample,), own_peaks in peaks.group_by(["sample"]):
        n = own_peaks.height
        footprint = _footprint(
            (own_peaks["start"] - own_peaks["summit0"]).to_numpy(),
            (own_peaks["end"] - own_peaks["summit0"]).to_numpy(),
            centres,
        )
        neighbours = np.zeros(len(centres), dtype=np.int64)
        for (chrom,), chrom_peaks in own_peaks.group_by(["chr"]):
            own = np.sort(chrom_peaks["summit0"].to_numpy())
            neighbours += _neighbour_counts(own, own, every_by_chr[chrom], edges)
        rows.append(
            pl.DataFrame(
                {
                    "sample": [sample] * len(centres),
                    "offset_bp": centres,
                    "n_summits": [n] * len(centres),
                    "peak_footprint": footprint.astype(np.float64),
                    "neighbour_summit_density": neighbours / n / per_kb,
                },
                schema=EXPECTED_SCHEMA,
            )
        )
    return pl.concat(rows).select(list(EXPECTED_SCHEMA)).sort(["sample", "offset_bp"])
