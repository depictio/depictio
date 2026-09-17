"""Tidy QCatch's per-sample `<sample>_metrics_summary.csv` into typed columns.

QCatch (the QC report generator for alevin-fry / simpleaf quantifications)
writes one summary row per sample with the same spreadsheet-friendly number
formatting as Cell Ranger's `metrics_summary.csv`: thousands separators
(`"8,779"`) and percent signs (`"84.49%"`). The sample lives only in the file
name (`<sample>_metrics_summary.csv`), so the raw data collection is a
**scan** (`include_file_paths`) and the sample is recovered from the
basename, same idiom as `cellbender/metrics.py`.

A template reusing this recipe declares::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: 'qcatch/[^/]+_metrics_summary\\.csv$'}
      dc_specific_properties:
        format: CSV
        polars_kwargs:
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8                              sample QCatch reported on
    retained_cells : Int64                     "Number of retained cells"
    processed_cells : Int64                    "Number of all processed cells"
    mean_reads_per_retained_cell : Int64        "Mean reads per retained cell"
    median_umi_per_retained_cell : Int64        "Median UMI per retained cell"
    median_genes_per_retained_cell : Int64      "Median genes per retained cell"
    total_genes_detected : Int64                "Total genes detected for retained cells"
    mapping_rate_pct : Float64                  "Mapping rate"
    sequencing_saturation_pct : Float64         "Sequencing saturation"
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "qcatch_metrics_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="metrics", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "retained_cells": pl.Int64,
    "processed_cells": pl.Int64,
    "mean_reads_per_retained_cell": pl.Int64,
    "median_umi_per_retained_cell": pl.Int64,
    "median_genes_per_retained_cell": pl.Int64,
    "total_genes_detected": pl.Int64,
    "mapping_rate_pct": pl.Float64,
    "sequencing_saturation_pct": pl.Float64,
}

_INT_COLUMNS = {
    "Number of retained cells": "retained_cells",
    "Number of all processed cells": "processed_cells",
    "Mean reads per retained cell": "mean_reads_per_retained_cell",
    "Median UMI per retained cell": "median_umi_per_retained_cell",
    "Median genes per retained cell": "median_genes_per_retained_cell",
    "Total genes detected for retained cells": "total_genes_detected",
}
_PCT_COLUMNS = {
    "Mapping rate": "mapping_rate_pct",
    "Sequencing saturation": "sequencing_saturation_pct",
}

_SAMPLE_RE = r"qcatch/([^/]+)_metrics_summary\.csv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["metrics"]
    if "source_path" not in df.columns:
        raise ValueError(
            "qcatch_metrics_summary: input has no 'source_path' column, the raw data "
            "collection must be scanned with polars_kwargs.include_file_paths"
        )
    missing = [c for c in {**_INT_COLUMNS, **_PCT_COLUMNS} if c not in df.columns]
    if missing:
        raise ValueError(f"qcatch_metrics_summary: input lacks columns {missing}")

    exprs = [pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample")]
    for raw_name, out_name in _INT_COLUMNS.items():
        exprs.append(
            pl.col(raw_name).str.replace_all(",", "").cast(pl.Int64, strict=False).alias(out_name)
        )
    for raw_name, out_name in _PCT_COLUMNS.items():
        exprs.append(
            pl.col(raw_name).str.replace_all("%", "").cast(pl.Float64, strict=False).alias(out_name)
        )

    result = df.select(exprs)
    unnamed = result.filter(pl.col("sample").is_null()).height
    if unnamed:
        raise ValueError(
            "qcatch_metrics_summary: a row's source_path does not look like "
            "'qcatch/<sample>_metrics_summary.csv'"
        )
    return result.select(list(EXPECTED_SCHEMA)).sort("sample")
