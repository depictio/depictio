"""Fragment pile-up around the strongest SEACR regions, one window per region.

SEACR calls regions from the fragment coverage itself, so the fragments are the
signal the calls stand on. The CUT&RUN-family pipelines publish them as one
headerless BED3 per sample, ``<sample>.frags.cut.bed`` (chrom, start, end of
every properly paired fragment), next to the ``*.frags.len.txt`` histogram.
This recipe reads them together with the tidy SEACR calls and returns the
deepTools ``computeMatrix reference-point`` shape without a bigWig: for each
sample, the ``TOP_N`` strongest regions, a ``2 * HALF_WINDOW`` window centred
on each region's summit, in ``BIN_BP`` bins, and in every bin the fragments
that overlap it, per million fragments of the sample.

Two readings of the same rows:

* per region and offset (``peak_id`` x ``offset_bp``) it is the metagene matrix
  a ``signal_matrix`` tile draws, regions down and offsets across, with the mean
  profile above it;
* per genomic bin (``chr`` x ``bin_start``) it is a fragment coverage track that
  a ``coverage_track`` tile clamps to the region a locus navigator selects.

The second reading needs every genomic bin once per sample, so the regions are
picked greedily by total signal and a region whose summit sits within one window
of a stronger kept region is skipped (non-maximum suppression). Windows never
overlap, a bin belongs to at most one region, and the matrix rows stay complete.
The regions outside the kept set are simply not drawn: this is a pile-up around
the strongest calls, not a genome-wide coverage track.

Sources:

``fragments``
    The ``seacr_frags_raw`` collection: every ``*.frags.cut.bed`` read through a
    **scan**, because only a scan carries the file path (and so the sample) into
    the frame. A template reusing this recipe declares::

        config:
          type: Table
          scan:
            mode: recursive
            scan_parameters:
              regex_config: {pattern: '.*\\.frags\\.cut\\.bed$'}
          dc_specific_properties:
            format: TSV
            polars_kwargs:
              separator: "\\t"
              has_header: false
              new_columns: [chr, start, end]
              include_file_paths: source_path

    A megatest library holds a million fragments or more; the raw collection
    keeps them as three narrow columns and this recipe keeps only the few
    percent inside the windows.
``peaks``
    The ``seacr_peaks`` collection (``seacr/peaks.py``), for the summit, the
    total signal and the ``peak_id`` the other SEACR tiles select on.

A run whose fragment BEDs were not published (or not mirrored) leaves the raw
collection empty and this recipe without input, which is why templates declare
both collections ``optional: true``.

Output schema:
    sample : Utf8          sample the fragments and the region belong to
    target : Utf8          group the sample belongs to (replicate suffix removed)
    peak_id : Utf8         the SEACR region the window is centred on
    peak_rank : Int64      1 for the sample's strongest kept region
    chr : Utf8             chromosome
    summit : Int64         the region's summit (seacr_peaks.summit)
    offset_bp : Int64      bin start minus the summit bin start, a multiple of BIN_BP
    bin_start : Int64      genomic start of the bin (0-based)
    bin_end : Int64        genomic end of the bin
    fragments : Int64      fragments overlapping the bin
    cpm : Float64          fragments per million fragments of the sample
"""

from __future__ import annotations

import bisect

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Raw fragment BEDs, scanned with the file path (see module docstring).
RAW_DC_TAG = "seacr_frags_raw"
#: Tidy SEACR calls the windows are centred on.
PEAKS_DC_TAG = "seacr_peaks"

#: Bin width, half window and regions kept per sample. 61 bins x 500 regions x
#: a handful of samples stays in the low hundreds of thousands of rows.
BIN_BP = 100
HALF_WINDOW = 3000
TOP_N = 500

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="fragments", dc_ref=RAW_DC_TAG),
    RecipeSource(ref="peaks", dc_ref=PEAKS_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "target": pl.Utf8,
    "peak_id": pl.Utf8,
    "peak_rank": pl.Int64,
    "chr": pl.Utf8,
    "summit": pl.Int64,
    "offset_bp": pl.Int64,
    "bin_start": pl.Int64,
    "bin_end": pl.Int64,
    "fragments": pl.Int64,
    "cpm": pl.Float64,
}

_NAME_RE = r"(?P<sample>.+?)\.frags\.cut\.bed$"
_REPLICATE_SUFFIX = r"_(?:R|rep|REP|Rep)?\d+$"


def _kept_regions(peaks: pl.DataFrame) -> pl.DataFrame:
    """The TOP_N strongest summits of one sample whose windows do not overlap."""
    min_gap = 2 * HALF_WINDOW + BIN_BP
    kept: list[dict] = []
    taken: dict[str, list[int]] = {}
    for row in peaks.sort("total_signal", descending=True, nulls_last=True).iter_rows(named=True):
        summits = taken.setdefault(row["chr"], [])
        i = bisect.bisect_left(summits, row["summit"])
        near_left = i > 0 and row["summit"] - summits[i - 1] < min_gap
        near_right = i < len(summits) and summits[i] - row["summit"] < min_gap
        if near_left or near_right:
            continue
        summits.insert(i, row["summit"])
        kept.append({**row, "peak_rank": len(kept) + 1})
        if len(kept) == TOP_N:
            break
    return pl.DataFrame(
        kept,
        schema={
            "peak_id": pl.Utf8,
            "chr": pl.Utf8,
            "summit": pl.Int64,
            "total_signal": pl.Float64,
            "peak_rank": pl.Int64,
        },
    )


def _sample_profile(sample: str, frags: pl.DataFrame, peaks: pl.DataFrame) -> pl.DataFrame:
    total = frags.height
    regions = _kept_regions(peaks.select("peak_id", "chr", "summit", "total_signal"))
    if total == 0 or regions.is_empty():
        return pl.DataFrame(schema=EXPECTED_SCHEMA)

    n_side = HALF_WINDOW // BIN_BP
    windows = (
        regions.with_columns(
            (pl.col("summit") // BIN_BP).alias("centre_bin"),
            pl.int_ranges(-n_side, n_side + 1).alias("step"),
        )
        .explode("step")
        .with_columns(
            (pl.col("centre_bin") + pl.col("step")).alias("bin"),
            (pl.col("step") * BIN_BP).cast(pl.Int64).alias("offset_bp"),
        )
        # A summit within a window of the contig start has no bins before 0.
        .filter(pl.col("bin") >= 0)
    )

    # Every bin a fragment touches, then a count per bin, but only for the
    # contigs a window sits on so the explode stays proportional to the calls.
    counts = (
        frags.filter(pl.col("chr").is_in(regions["chr"].unique().implode()))
        .select(
            "chr",
            pl.int_ranges(pl.col("start") // BIN_BP, (pl.col("end") - 1) // BIN_BP + 1).alias(
                "bin"
            ),
        )
        .explode("bin")
        .group_by("chr", "bin")
        .agg(pl.len().cast(pl.Int64).alias("fragments"))
    )

    return (
        windows.join(counts, on=["chr", "bin"], how="left")
        .with_columns(
            pl.lit(sample).alias("sample"),
            pl.col("fragments").fill_null(0),
            (pl.col("bin") * BIN_BP).cast(pl.Int64).alias("bin_start"),
            ((pl.col("bin") + 1) * BIN_BP).cast(pl.Int64).alias("bin_end"),
        )
        .with_columns(
            (pl.col("fragments").cast(pl.Float64) * 1e6 / total).alias("cpm"),
            pl.col("sample").str.replace(_REPLICATE_SUFFIX, "").alias("target"),
        )
        .select(list(EXPECTED_SCHEMA))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pile the fragments up around each sample's strongest non-overlapping regions."""
    frags = sources["fragments"]
    peaks = sources["peaks"]
    if "source_path" not in frags.columns:
        raise ValueError(
            "seacr_frags_profile: the fragment source has no 'source_path' column; "
            "read it with include_file_paths"
        )
    missing = {"sample", "peak_id", "chr", "summit", "total_signal"} - set(peaks.columns)
    if missing:
        raise ValueError(f"seacr_frags_profile: seacr_peaks lacks columns {sorted(missing)}")

    frags = (
        frags.with_columns(
            pl.col("source_path")
            .str.replace_all(r"^.*/", "")
            .str.extract(_NAME_RE, 1)
            .alias("sample"),
            pl.col("chr").cast(pl.Utf8),
            pl.col("start").cast(pl.Int64, strict=False),
            pl.col("end").cast(pl.Int64, strict=False),
        )
        .drop_nulls(["sample", "start", "end"])
        .filter(pl.col("end") > pl.col("start"))
    )

    frames = [
        _sample_profile(
            sample,
            frags.filter(pl.col("sample") == sample),
            peaks.filter(pl.col("sample") == sample),
        )
        for sample in sorted(set(frags["sample"].unique()) & set(peaks["sample"].unique()))
    ]
    frames = [f for f in frames if not f.is_empty()]
    if not frames:
        raise ValueError("seacr_frags_profile: no sample has both a fragment BED and SEACR regions")
    return pl.concat(frames).sort(["sample", "peak_rank", "offset_bp"])
