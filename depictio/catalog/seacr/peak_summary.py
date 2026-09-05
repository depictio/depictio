"""One row per sample: what SEACR called and how strong those calls are.

Reads the tidy peak table `seacr/peaks.py` produced (through ``dc_ref``) and
reduces it to a per-sample QC row. SEACR reports no FRiP score and no fold
enrichment, so the signal-to-noise proxies here are the summed fragment
coverage inside the calls and the coverage per base (``signal_density``): a
target that worked has far more of both than the IgG control processed the same
way.

Output schema:
    sample : Utf8                      sample the peaks were called in
    threshold_mode : Utf8              SEACR mode the calls came from
    num_peaks : Int64                  regions SEACR called
    total_bp : Int64                   bases covered by those regions
    width_median : Float64             median region width (bp)
    width_mean : Float64               mean region width (bp)
    width_max : Int64                  widest region (bp)
    total_signal_sum : Float64         summed fragment coverage over all regions
    total_signal_median : Float64      median per-region total signal
    max_signal_median : Float64        median per-region max signal
    signal_density_median : Float64    median coverage per base inside a region
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads: the output of `seacr/peaks.py`.
PEAKS_DC_TAG = "seacr_peaks"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="peaks", dc_ref=PEAKS_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "threshold_mode": pl.Utf8,
    "num_peaks": pl.Int64,
    "total_bp": pl.Int64,
    "width_median": pl.Float64,
    "width_mean": pl.Float64,
    "width_max": pl.Int64,
    "total_signal_sum": pl.Float64,
    "total_signal_median": pl.Float64,
    "max_signal_median": pl.Float64,
    "signal_density_median": pl.Float64,
}

_REQUIRED = ["sample", "width", "total_signal", "max_signal", "signal_density"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Group the peak table by sample and summarise width and signal."""
    df = sources["peaks"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"seacr_peak_summary: input lacks columns {missing}")

    mode = (
        pl.col("threshold_mode").first()
        if "threshold_mode" in df.columns
        else pl.lit(None, dtype=pl.Utf8)
    )
    summary = df.group_by("sample").agg(
        mode.alias("threshold_mode"),
        pl.len().cast(pl.Int64).alias("num_peaks"),
        pl.col("width").sum().cast(pl.Int64).alias("total_bp"),
        pl.col("width").median().cast(pl.Float64).alias("width_median"),
        pl.col("width").mean().cast(pl.Float64).alias("width_mean"),
        pl.col("width").max().cast(pl.Int64).alias("width_max"),
        pl.col("total_signal").sum().cast(pl.Float64).alias("total_signal_sum"),
        pl.col("total_signal").median().cast(pl.Float64).alias("total_signal_median"),
        pl.col("max_signal").median().cast(pl.Float64).alias("max_signal_median"),
        pl.col("signal_density").median().cast(pl.Float64).alias("signal_density_median"),
    )
    return summary.select(list(EXPECTED_SCHEMA)).sort("sample")
