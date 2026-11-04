"""Long, threshold-annotated form of the 4 metrics 10x's QC guidance gives an
expected value for, one row per (sample, metric).

A template reusing this recipe declares one source, the already-extended
metrics_summary DC (`cellranger/metrics_summary.py`, with the `_frac`
columns)::

    transform: {recipe: "cellranger/library_metrics_long.py"}
    # SOURCES = [RecipeSource(ref="metrics", dc_ref="cellranger_metrics")]

Thresholds (10x guidance, all on the 0-1 fraction). Source: 10x Genomics technical
note CG000329 Rev A, "Cell Ranger Web Summary Files for Single Cell Gene Expression
Assay", Table 1 (https://assets.ctfassets.net/an68im79xiti/163qWiQBTVi2YLbskJphQX/e90bb82151b1cdab6d7e9b6c845e6130/CG000329_TechnicalNote_InterpretingCellRangerWebSummaryFiles_RevA.pdf):
    fraction_reads_in_cells          warn below 0.7   (expected ">70%")
    valid_barcodes                   fail below 0.75  (expected ">75%")
    q30_rna                          warn below 0.65  (platform dependent, "ideally >65%")
    confidently_mapped_transcriptome warn below 0.3   (expected ">30%")

Sequencing saturation is not here: the note gives it no number ("Dependent upon
sequencing depth and sample complexity"), so it is read as a value only
(`metrics_summary`'s `sequencing_saturation_*`). The warn / fail split is this module's
own; the note gives one expected value per metric.

Output schema:
    sample : Utf8
    metric : Utf8       one of the 4 metric names above
    value : Float64       the metric's value, as a 0-1 fraction
    unit : Utf8            always "fraction"
    threshold : Float64    the pass/warn (or pass/fail) cutoff for this metric
    status : Utf8           "pass" | "warn" | "fail"
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

METRICS_DC_TAG = "cellranger_metrics"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="metrics",
        dc_ref=METRICS_DC_TAG,
        input_schema={
            "sample": pl.Utf8,
            "fraction_reads_in_cells_frac": pl.Float64,
            "valid_barcodes_frac": pl.Float64,
            "q30_rna_read_frac": pl.Float64,
            "reads_mapped_confidently_transcriptome_frac": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "metric": pl.Utf8,
    "value": pl.Float64,
    "unit": pl.Utf8,
    "threshold": pl.Float64,
    "status": pl.Utf8,
}

# metric -> (source fraction column, threshold, band below the threshold)
_METRICS: dict[str, tuple[str, float, str]] = {
    "fraction_reads_in_cells": ("fraction_reads_in_cells_frac", 0.7, "warn"),
    "valid_barcodes": ("valid_barcodes_frac", 0.75, "fail"),
    "q30_rna": ("q30_rna_read_frac", 0.65, "warn"),
    "confidently_mapped_transcriptome": (
        "reads_mapped_confidently_transcriptome_frac",
        0.3,
        "warn",
    ),
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    metrics = sources["metrics"]
    required = {"sample"} | {col for col, _, _ in _METRICS.values()}
    if missing := required - set(metrics.columns):
        raise ValueError(f"cellranger_library_metrics_long: input lacks columns {sorted(missing)}")

    frames = []
    for metric_name, (col, threshold, band) in _METRICS.items():
        frames.append(
            metrics.select(
                "sample",
                pl.lit(metric_name).alias("metric"),
                pl.col(col).cast(pl.Float64).alias("value"),
                pl.lit("fraction").alias("unit"),
                pl.lit(threshold).cast(pl.Float64).alias("threshold"),
                pl.when(pl.col(col) >= threshold)
                .then(pl.lit("pass"))
                .otherwise(pl.lit(band))
                .alias("status"),
            )
        )
    result = pl.concat(frames, how="vertical_relaxed")
    return result.select(list(OUTPUT_SCHEMA)).sort(["sample", "metric"])
