"""Per 250 kb window: how far its nascent signal moves over the time course, and when.

The genome-wide counterpart of ``gene_dynamics``, independent of any gene
annotation: it reads the strand coverage itself (``bedtools_strand_bins``, both
strands summed, per million of each library's signal), so a change in an
unannotated region (an enhancer cluster, a long non-coding locus, an antisense
transcript) shows as well as one in a gene.

The windows compared are the transcribed half of the genome without its hotspots
(``depictio/recipes/lib/strand_coverage.py``: mean signal between the median
window's and the 99.5th percentile, which drops the ribosomal DNA arrays whose
share follows depletion rather than transcription). On ``log2(rpm + 1)``,
averaged over the libraries of each time point, each window gets the same calls
as a gene (``depictio/recipes/lib/time_course.py``): the peak change against the
baseline, its time point and phase, and a ``trend`` of ``Rising`` or
``Falling`` when the peak reaches a log2 fold change of 1 and two time points
change that much the same way, else ``Stable``.

Sources:
    bins     ``bedtools_strand_bins`` (catalog ``bedtools/strand_bins.py``)
    samples  ``samples`` (the sample hub)

Output schema:
    window_id, chromosome : Utf8, start, end, position : Int64
    mean_rpm, baseline_log2_signal, dynamic_range : Float64
    peak_log2fc, abs_peak_log2fc, last_log2fc : Float64
    peak_time_point : Utf8, peak_time_h : Float64, peak_phase : Utf8
    n_changed : Int64, trend : Utf8, rank : Int64
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib import strand_coverage as sc
from depictio.recipes.lib import time_course as tc

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="bins",
        dc_ref="bedtools_strand_bins",
        input_schema={
            "sample": pl.Utf8,
            "chromosome": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
            "position": pl.Int64,
            "signal_rpm": pl.Float64,
            "log2_signal": pl.Float64,
        },
    ),
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={
            "sample": pl.Utf8,
            "time_point": pl.Utf8,
            "time_h": pl.Float64,
            "time_order": pl.Int64,
            "time_axis": pl.Float64,
            "phase": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "window_id": pl.Utf8,
    "chromosome": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "position": pl.Int64,
    "mean_rpm": pl.Float64,
    "baseline_log2_signal": pl.Float64,
    "dynamic_range": pl.Float64,
    "peak_log2fc": pl.Float64,
    "abs_peak_log2fc": pl.Float64,
    "last_log2fc": pl.Float64,
    "peak_time_point": pl.Utf8,
    "peak_time_h": pl.Float64,
    "peak_phase": pl.Utf8,
    "n_changed": pl.Int64,
    "trend": pl.Utf8,
    "rank": pl.Int64,
}

#: Trend labels of a window, by the sign of its peak change.
TREND_LABELS = {tc.UP: "Rising", tc.DOWN: "Falling", tc.FLAT: "Stable"}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    bins = sources["bins"]
    windows = sc.comparable_windows(bins)
    long = bins.with_columns(sc.window_id_expr()).join(
        windows.select("window_id"), on="window_id", how="inner"
    )
    times = sources["samples"].select("sample", *tc.TIME_POINT_COLUMNS)
    points = tc.time_point_values(
        long.select("window_id", "sample", "log2_signal"),
        times,
        key="window_id",
        value_col="log2_signal",
    )
    calls = tc.classify_changes(points, key="window_id")
    return (
        calls.join(windows, on="window_id", how="left")
        .with_columns(
            pl.col("direction").replace_strict(TREND_LABELS, return_dtype=pl.Utf8).alias("trend"),
            pl.col("baseline").alias("baseline_log2_signal"),
            pl.col("abs_peak_log2fc")
            .rank(method="ordinal", descending=True)
            .cast(pl.Int64)
            .alias("rank"),
            sc.contig_order_expr("chromosome"),
        )
        .sort(["_contig_number", "chromosome", "start"], nulls_last=True)
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
    )
