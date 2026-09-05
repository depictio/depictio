"""Do MACS2 and SEACR agree, sample by sample?

nf-core/cutandrun can run two very different peak callers over the same
fragments: MACS2, which fits a background model and reports a fold enrichment
and a q-value, and SEACR, which thresholds the fragment-coverage landscape
against the IgG control. Neither is a subset of the other, and the disagreement
is the most informative thing a CUT&RUN run produces: a broad mark can be
invisible to MACS2 and obvious to SEACR, and a caller that returns nothing at
all is a result, not a gap.

This recipe reduces both peak tables to one row per (sample, caller), and joins
them against each other so every row also carries how much of it the *other*
caller reproduced. A sample the sample sheet declares but a caller never called
gets a row with `n_peaks = 0` rather than disappearing, which is what keeps a
null result visible in the dashboard.

Overlap is counted, not measured in bases: a peak "is shared" when it overlaps
at least one peak of the other caller on the same sample and chromosome. That is
found with two as-of joins (the last other-caller peak starting at or before it,
carrying a running maximum end, and the first one starting at or after it), so
the cost stays O(n log n) instead of the quadratic interval cross join.

Sources are the two already-ingested peak collections plus the sample hub, read
through `dc_ref`: both peak tables are large and re-reading their files here
would parse them a second time.

Output schema:
    sample : Utf8            sample the peaks were called in
    target : Utf8            group the sample belongs to (the mark)
    caller : Utf8            "macs2" or "seacr"
    n_peaks : Int64          peaks this caller called for the sample
    total_bp : Int64         bases those peaks cover
    median_width : Float64   median peak width (bp)
    max_width : Int64        widest peak (bp)
    n_shared : Int64         peaks overlapping at least one peak of the other caller
    n_unique : Int64         n_peaks - n_shared
    frac_shared : Float64    n_shared / n_peaks, 0 when the caller called nothing
    log10_n_peaks : Float64  log10(n_peaks + 1), a colour axis that survives zeros
    other_caller : Utf8      the caller compared against
    n_peaks_other : Int64    peaks that other caller called for the same sample
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tags this recipe reads.
MACS2_DC_TAG = "macs2_peaks"
SEACR_DC_TAG = "seacr_peaks"
SAMPLES_DC_TAG = "samples"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="macs2", dc_ref=MACS2_DC_TAG, optional=True),
    RecipeSource(ref="seacr", dc_ref=SEACR_DC_TAG, optional=True),
    RecipeSource(ref="samples", dc_ref=SAMPLES_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "target": pl.Utf8,
    "caller": pl.Utf8,
    "n_peaks": pl.Int64,
    "total_bp": pl.Int64,
    "median_width": pl.Float64,
    "max_width": pl.Int64,
    "n_shared": pl.Int64,
    "n_unique": pl.Int64,
    "frac_shared": pl.Float64,
    "log10_n_peaks": pl.Float64,
    "other_caller": pl.Utf8,
    "n_peaks_other": pl.Int64,
}

CALLERS = ["macs2", "seacr"]
_OTHER = {"macs2": "seacr", "seacr": "macs2"}
# MACS2 is run with `--name <sample>.macs2`, so its peak names carry the caller.
_CALLER_SUFFIX = r"\.(?:macs2|macs3|seacr|epic2)$"
_INTERVAL_COLUMNS = ["sample", "chr", "start", "end"]

_EMPTY = pl.DataFrame(
    schema={"sample": pl.Utf8, "chr": pl.Utf8, "start": pl.Int64, "end": pl.Int64}
)


def _intervals(df: pl.DataFrame | None) -> pl.DataFrame:
    """Normalise a peak table to `sample, chr, start, end`, sorted for as-of joins."""
    if df is None or df.is_empty():
        return _EMPTY
    missing = [c for c in _INTERVAL_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"caller_agreement: peak table lacks columns {missing}")
    return (
        df.select(
            pl.col("sample").cast(pl.Utf8).str.replace(_CALLER_SUFFIX, ""),
            pl.col("chr").cast(pl.Utf8),
            pl.col("start").cast(pl.Int64),
            pl.col("end").cast(pl.Int64),
        )
        .drop_nulls(["sample", "chr", "start", "end"])
        .sort(["sample", "chr", "start"])
    )


def _shared_flags(left: pl.DataFrame, right: pl.DataFrame) -> pl.DataFrame:
    """Add `shared`: does each left interval overlap any right interval?

    Two as-of joins do it without a cross join. Backward: the last right
    interval starting at or before the left start, carrying the running maximum
    of the right ends so far, so any earlier right interval reaching into the
    left one counts. Forward: the first right interval starting at or after the
    left start, which overlaps when it starts before the left end.
    """
    if left.is_empty():
        return left.with_columns(pl.lit(False).alias("shared"))
    if right.is_empty():
        return left.with_columns(pl.lit(False).alias("shared"))

    right = right.with_columns(
        pl.col("end").cum_max().over(["sample", "chr"]).alias("_right_max_end"),
        pl.col("start").alias("_right_start"),
    )
    backward = left.join_asof(
        right.select(["sample", "chr", "start", "_right_max_end"]),
        on="start",
        by=["sample", "chr"],
        strategy="backward",
        # both frames are sorted by (sample, chr, start); polars cannot verify
        # that across `by` groups and only warns, so say so explicitly.
        check_sortedness=False,
    )
    forward = left.join_asof(
        right.select(["sample", "chr", "start", "_right_start"]),
        on="start",
        by=["sample", "chr"],
        strategy="forward",
        check_sortedness=False,
    )
    return left.with_columns(
        (
            (backward.get_column("_right_max_end") > pl.col("start")).fill_null(False)
            | (forward.get_column("_right_start") < pl.col("end")).fill_null(False)
        ).alias("shared")
    )


def _summarise(intervals: pl.DataFrame, caller: str) -> pl.DataFrame:
    """One row per sample: count, span and how much the other caller reproduced."""
    if intervals.is_empty():
        return pl.DataFrame(
            schema={
                "sample": pl.Utf8,
                "caller": pl.Utf8,
                "n_peaks": pl.Int64,
                "total_bp": pl.Int64,
                "median_width": pl.Float64,
                "max_width": pl.Int64,
                "n_shared": pl.Int64,
            }
        )
    width = (pl.col("end") - pl.col("start")).alias("width")
    return (
        intervals.with_columns(width)
        .group_by("sample")
        .agg(
            pl.len().cast(pl.Int64).alias("n_peaks"),
            pl.col("width").sum().cast(pl.Int64).alias("total_bp"),
            pl.col("width").median().cast(pl.Float64).alias("median_width"),
            pl.col("width").max().cast(pl.Int64).alias("max_width"),
            pl.col("shared").sum().cast(pl.Int64).alias("n_shared"),
        )
        .with_columns(pl.lit(caller).alias("caller"))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Compare the two callers per sample over the samples the sheet declares."""
    samples = sources["samples"]
    if "sample_id" not in samples.columns:
        raise ValueError("caller_agreement: the samples collection has no 'sample_id' column")

    by_caller = {
        "macs2": _intervals(sources.get("macs2")),
        "seacr": _intervals(sources.get("seacr")),
    }
    if all(frame.is_empty() for frame in by_caller.values()):
        raise ValueError("caller_agreement: neither peak collection has any peak")

    summaries = [_summarise(_shared_flags(by_caller[c], by_caller[_OTHER[c]]), c) for c in CALLERS]
    stats = pl.concat(summaries, how="diagonal_relaxed")

    # Peak calling only runs on the targets, so the IgG controls are not rows
    # here; a target a caller returned nothing for still is, with n_peaks 0.
    targets = samples
    if "is_control" in samples.columns:
        targets = samples.filter(~pl.col("is_control").cast(pl.Boolean).fill_null(False))
    target_col = "target" if "target" in targets.columns else None
    grid = targets.select(
        pl.col("sample_id").cast(pl.Utf8).alias("sample"),
        (pl.col(target_col).cast(pl.Utf8) if target_col else pl.lit(None, pl.Utf8)).alias("target"),
    ).unique()
    grid = grid.join(pl.DataFrame({"caller": CALLERS}), how="cross")

    df = grid.join(stats, on=["sample", "caller"], how="left").with_columns(
        pl.col("n_peaks").fill_null(0),
        pl.col("total_bp").fill_null(0),
        pl.col("median_width").fill_null(0.0),
        pl.col("max_width").fill_null(0),
        pl.col("n_shared").fill_null(0),
        pl.col("caller").replace_strict(_OTHER, return_dtype=pl.Utf8).alias("other_caller"),
    )
    counts = df.select(["sample", "caller", "n_peaks"]).rename({"n_peaks": "n_peaks_other"})
    df = df.join(
        counts, left_on=["sample", "other_caller"], right_on=["sample", "caller"], how="left"
    ).with_columns(pl.col("n_peaks_other").fill_null(0))

    df = df.with_columns(
        (pl.col("n_peaks") - pl.col("n_shared")).alias("n_unique"),
        pl.when(pl.col("n_peaks") > 0)
        .then(pl.col("n_shared") / pl.col("n_peaks"))
        .otherwise(0.0)
        .cast(pl.Float64)
        .alias("frac_shared"),
        (pl.col("n_peaks").cast(pl.Float64) + 1.0).log10().alias("log10_n_peaks"),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["target", "sample", "caller"])
