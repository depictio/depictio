"""How much of a sample's fragment coverage falls inside its own peaks.

FRiP, the fraction of reads in peaks, is the signal-to-noise number of a
chromatin-profiling experiment: a library where most of the material sits
inside the called regions worked, one where it is spread over the genome did
not. nf-core/cutandrun does not publish a FRiP table, and SEACR reports no read
count at all, so this recipe builds the equivalent out of the two things the
run does publish, both measured in base pairs of fragment coverage:

  * the denominator, from the per-sample fragment-length histogram:
    ``sum(fragment_length * count)`` is every base every fragment covered;
  * the numerator, from the SEACR peak table: ``total_signal`` is the summed
    fragment coverage over a region, so summing it over a sample's regions is
    the coverage that landed inside peaks.

One correction is needed before the ratio means anything. cutandrun scales the
bedGraph SEACR reads by the spike-in factor (``normalisation_c /
spikein_aligned_pairs``), so ``total_signal`` is in scaled units while the
fragment histogram is in raw ones. Dividing the numerator by that same factor
puts both back in base pairs. On the 3.1 megatest the raw ratios span 2.3 to
48 across four samples whose scale factors span 2.9 to 55.9, and de-scaling
collapses them to 0.67 to 0.86: the correction is what makes the number a
fraction at all.

When no spike-in factor is available (``--skip_spikein_norm``, or a run whose
Bowtie 2 spike-in logs were not collected) the factor falls back to 1.0, which
is correct for an unscaled bedGraph and is recorded in the ``scale_factor``
column so a reader can tell the two cases apart.

The table is LONG: two rows per sample, ``In peaks`` and ``Outside peaks``, so
a donut or a stacked bar reads it as a composition directly. The sample-level
``frip`` is repeated on both rows of a sample, which leaves every quantile of
it unchanged and lets a single card gauge it.

Output schema:
    sample : Utf8           sample the coverage belongs to
    target : Utf8           group the sample belongs to (the mark)
    signal_class : Utf8     "In peaks" or "Outside peaks"
    coverage_bp : Float64   base pairs of fragment coverage in that class
    fraction : Float64      coverage_bp / fragment_bp
    frip : Float64          the sample's fraction inside peaks, on both of its rows
    n_peaks : Int64         regions the caller called for the sample
    peak_span_bp : Int64    base pairs those regions span
    fragment_bp : Float64   base pairs all of the sample's fragments covered
    scale_factor : Float64  spike-in factor divided out of the peak signal (1.0 when none)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tags this recipe reads.
PEAKS_DC_TAG = "seacr_peaks"
FRAGMENTS_DC_TAG = "seacr_fragment_lengths"
FACTORS_DC_TAG = "bowtie2_spikein_factors"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="peaks", dc_ref=PEAKS_DC_TAG),
    RecipeSource(ref="fragments", dc_ref=FRAGMENTS_DC_TAG),
    RecipeSource(ref="factors", dc_ref=FACTORS_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "target": pl.Utf8,
    "signal_class": pl.Utf8,
    "coverage_bp": pl.Float64,
    "fraction": pl.Float64,
    "frip": pl.Float64,
    "n_peaks": pl.Int64,
    "peak_span_bp": pl.Int64,
    "fragment_bp": pl.Float64,
    "scale_factor": pl.Float64,
}

IN_PEAKS = "In peaks"
OUTSIDE_PEAKS = "Outside peaks"


def _fragment_budget(fragments: pl.DataFrame) -> pl.DataFrame:
    """Base pairs of fragment coverage per sample, from the length histogram."""
    missing = [c for c in ("sample", "fragment_length", "count") if c not in fragments.columns]
    if missing:
        raise ValueError(f"cutandrun_frip: the fragment collection lacks columns {missing}")
    target = (
        pl.col("target").cast(pl.Utf8).first()
        if "target" in fragments.columns
        else pl.lit(None, pl.Utf8).first()
    )
    return fragments.group_by("sample").agg(
        target.alias("target"),
        (pl.col("fragment_length").cast(pl.Float64) * pl.col("count").cast(pl.Float64))
        .sum()
        .alias("fragment_bp"),
    )


def _peak_budget(peaks: pl.DataFrame) -> pl.DataFrame:
    """Summed region signal, region count and region span per sample."""
    missing = [c for c in ("sample", "total_signal", "start", "end") if c not in peaks.columns]
    if missing:
        raise ValueError(f"cutandrun_frip: the peak collection lacks columns {missing}")
    return peaks.group_by("sample").agg(
        pl.col("total_signal").cast(pl.Float64).sum().alias("scaled_peak_signal"),
        pl.len().cast(pl.Int64).alias("n_peaks"),
        (pl.col("end").cast(pl.Int64) - pl.col("start").cast(pl.Int64))
        .sum()
        .cast(pl.Int64)
        .alias("peak_span_bp"),
    )


def _factors(factors: pl.DataFrame | None) -> pl.DataFrame:
    """`sample, scale_factor`, or an empty frame when no spike-in run is bound."""
    empty = pl.DataFrame(schema={"sample": pl.Utf8, "scale_factor": pl.Float64})
    if factors is None or factors.is_empty():
        return empty
    if "sample" not in factors.columns or "scale_factor" not in factors.columns:
        return empty
    return (
        factors.select(
            pl.col("sample").cast(pl.Utf8),
            pl.col("scale_factor").cast(pl.Float64),
        )
        .drop_nulls()
        .unique(subset="sample")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split each sample's fragment coverage into the part inside its peaks."""
    fragments = sources["fragments"]
    peaks = sources["peaks"]
    if fragments.is_empty():
        raise ValueError("cutandrun_frip: the fragment-length collection is empty")
    if peaks.is_empty():
        raise ValueError("cutandrun_frip: the peak collection is empty")

    budget = _fragment_budget(fragments).join(_peak_budget(peaks), on="sample", how="inner")
    if budget.is_empty():
        raise ValueError(
            "cutandrun_frip: no sample has both a fragment histogram and called peaks; "
            "the two collections must share the sample naming"
        )

    budget = budget.join(_factors(sources.get("factors")), on="sample", how="left").with_columns(
        # 1.0 is the honest identity for a bedGraph that was never scaled.
        pl.col("scale_factor").fill_null(1.0).alias("scale_factor")
    )
    budget = budget.with_columns(
        (pl.col("scaled_peak_signal") / pl.col("scale_factor")).alias("peak_bp")
    )
    # A peak set can only hold coverage the library actually produced. Clipping
    # keeps an imperfect factor from printing a fraction above 1 instead of
    # saying the split is degenerate.
    budget = budget.with_columns(
        pl.min_horizontal(pl.col("peak_bp"), pl.col("fragment_bp")).alias("peak_bp")
    ).with_columns(
        pl.when(pl.col("fragment_bp") > 0)
        .then((pl.col("peak_bp") / pl.col("fragment_bp")).round(4))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("frip")
    )

    inside = budget.with_columns(
        pl.lit(IN_PEAKS).alias("signal_class"),
        pl.col("peak_bp").round(1).alias("coverage_bp"),
        pl.col("frip").alias("fraction"),
    )
    outside = budget.with_columns(
        pl.lit(OUTSIDE_PEAKS).alias("signal_class"),
        (pl.col("fragment_bp") - pl.col("peak_bp")).round(1).alias("coverage_bp"),
        (1.0 - pl.col("frip")).round(4).alias("fraction"),
    )
    long = pl.concat([inside, outside], how="vertical").with_columns(pl.col("fragment_bp").round(1))
    return long.select(list(EXPECTED_SCHEMA)).sort(["sample", "signal_class"])
