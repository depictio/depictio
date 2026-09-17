"""CellBender's per-sample ambient-RNA removal metrics, pivoted to one row per sample.

`<sample>_metrics.csv` is a headerless two-column `metric,value` file (17
rows). The sample lives only in the file name (`<sample>_metrics.csv`), so the
raw data collection is a **scan** (`include_file_paths`) and the sample is
read off the basename rather than the directory, unlike the Cell Ranger
recipes in this catalog.

A template reusing this recipe declares::

    regex_config: {pattern: 'cellbender_removebackground/[^/]+_metrics\\.csv$'}
    dc_specific_properties:
      format: CSV
      polars_kwargs:
        has_header: false
        new_columns: [metric, value]
        include_file_paths: source_path
        infer_schema_length: 0

Output schema:
    sample : Utf8                              sample CellBender ran on
    total_raw_counts : Float64                  summed counts before removal
    total_output_counts : Float64                summed counts after removal
    total_counts_removed : Float64                counts CellBender called ambient
    fraction_counts_removed : Float64              total_counts_removed / total_raw_counts
    expected_cells : Float64                    `--expected-cells` (or Cell Ranger's estimate)
    found_cells : Float64                       barcodes CellBender kept as cells
    ratio_of_found_cells_to_expected_cells : Float64
    target_fpr : Float64                        target false-positive rate parameter
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "cellbender_metrics_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="metrics", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_raw_counts": pl.Float64,
    "total_output_counts": pl.Float64,
    "total_counts_removed": pl.Float64,
    "fraction_counts_removed": pl.Float64,
    "expected_cells": pl.Float64,
    "found_cells": pl.Float64,
    "ratio_of_found_cells_to_expected_cells": pl.Float64,
    "target_fpr": pl.Float64,
}

_SAMPLE_RE = r"([^/]+)_metrics\.csv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["metrics"]
    if "source_path" not in df.columns:
        raise ValueError(
            "cellbender_metrics: input has no 'source_path' column, the raw data "
            "collection must be scanned with polars_kwargs.include_file_paths"
        )
    required = {"metric", "value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"cellbender_metrics: input lacks columns {sorted(missing)}")

    df = df.with_columns(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        pl.col("value").cast(pl.Float64, strict=False),
    )
    if df.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            "cellbender_metrics: a row's source_path did not match '<sample>_metrics.csv'"
        )

    wanted = [c for c in EXPECTED_SCHEMA if c != "sample"]
    pivoted = df.pivot(on="metric", index="sample", values="value")
    missing_metrics = [c for c in wanted if c not in pivoted.columns]
    if missing_metrics:
        raise ValueError(f"cellbender_metrics: metrics file is missing keys {missing_metrics}")

    result = pivoted.select(["sample", *wanted])
    for col in wanted:
        result = result.with_columns(pl.col(col).cast(pl.Float64, strict=False))
    return result.select(list(EXPECTED_SCHEMA)).sort("sample")
