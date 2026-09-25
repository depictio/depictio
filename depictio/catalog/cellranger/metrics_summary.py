"""Tidy Cell Ranger's per-sample `metrics_summary.csv` into typed columns.

Cell Ranger count writes one summary row per sample with number formatting
meant for a spreadsheet: thousands separators (`"8,767"`) and percent signs
(`"98.5%"`). There is no sample column either, Cell Ranger publishes one file
per sample under `cellranger/count/<sample>/outs/metrics_summary.csv`, so this
recipe reads the raw CSVs through a **scan** data collection (only a scan
carries the file path into the frame via `include_file_paths`) and recovers
the sample from that path.

A template reusing this recipe declares::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: 'cellranger/count/[^/]+/outs/metrics_summary\\.csv$'}
      dc_specific_properties:
        format: CSV
        polars_kwargs:
          include_file_paths: source_path
          infer_schema_length: 0

`infer_schema_length: 0` reads every column as text, since the thousands
separators and percent signs would otherwise make Polars guess mixed types.

Output schema (a subset of the 20 columns Cell Ranger writes; the rest are
already in the MultiQC `cellranger-count-stats-table`). Each `_pct` column
(0-100) has a `_frac` twin (0-1, `EXTEND`ed for `cellranger/library_metrics_long.py`
and any Tier-2 viz control that expects a fraction rather than a percentage):
    sample : Utf8                         sample the metrics belong to
    estimated_cells : Int64               "Estimated Number of Cells"
    mean_reads_per_cell : Int64           "Mean Reads per Cell"
    median_genes_per_cell : Int64         "Median Genes per Cell"
    number_of_reads : Int64               "Number of Reads"
    valid_barcodes_pct, valid_barcodes_frac : Float64          "Valid Barcodes"
    sequencing_saturation_pct, sequencing_saturation_frac : Float64   "Sequencing Saturation"
    q30_barcode_pct, q30_barcode_frac : Float64             "Q30 Bases in Barcode"
    q30_rna_read_pct, q30_rna_read_frac : Float64            "Q30 Bases in RNA Read"
    q30_umi_pct, q30_umi_frac : Float64                 "Q30 Bases in UMI"
    reads_mapped_confidently_transcriptome_pct, _frac : Float64  "Reads Mapped Confidently to Transcriptome"
    reads_mapped_antisense_pct, _frac : Float64  "Reads Mapped Antisense to Gene"
    fraction_reads_in_cells_pct, _frac : Float64 "Fraction Reads in Cells"
    total_genes_detected : Int64          "Total Genes Detected"
    median_umi_counts_per_cell : Int64    "Median UMI Counts per Cell"
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "cellranger_metrics_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="metrics", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "estimated_cells": pl.Int64,
    "mean_reads_per_cell": pl.Int64,
    "median_genes_per_cell": pl.Int64,
    "number_of_reads": pl.Int64,
    "valid_barcodes_pct": pl.Float64,
    "sequencing_saturation_pct": pl.Float64,
    "q30_barcode_pct": pl.Float64,
    "q30_rna_read_pct": pl.Float64,
    "q30_umi_pct": pl.Float64,
    "reads_mapped_confidently_transcriptome_pct": pl.Float64,
    "reads_mapped_antisense_pct": pl.Float64,
    "fraction_reads_in_cells_pct": pl.Float64,
    "total_genes_detected": pl.Int64,
    "median_umi_counts_per_cell": pl.Int64,
    "valid_barcodes_frac": pl.Float64,
    "sequencing_saturation_frac": pl.Float64,
    "q30_barcode_frac": pl.Float64,
    "q30_rna_read_frac": pl.Float64,
    "q30_umi_frac": pl.Float64,
    "reads_mapped_confidently_transcriptome_frac": pl.Float64,
    "reads_mapped_antisense_frac": pl.Float64,
    "fraction_reads_in_cells_frac": pl.Float64,
}

# raw Cell Ranger column name -> (ours, is_percent)
_INT_COLUMNS = {
    "Estimated Number of Cells": "estimated_cells",
    "Mean Reads per Cell": "mean_reads_per_cell",
    "Median Genes per Cell": "median_genes_per_cell",
    "Number of Reads": "number_of_reads",
    "Total Genes Detected": "total_genes_detected",
    "Median UMI Counts per Cell": "median_umi_counts_per_cell",
}
_PCT_COLUMNS = {
    "Valid Barcodes": "valid_barcodes_pct",
    "Sequencing Saturation": "sequencing_saturation_pct",
    "Q30 Bases in Barcode": "q30_barcode_pct",
    "Q30 Bases in RNA Read": "q30_rna_read_pct",
    "Q30 Bases in UMI": "q30_umi_pct",
    "Reads Mapped Confidently to Transcriptome": "reads_mapped_confidently_transcriptome_pct",
    "Reads Mapped Antisense to Gene": "reads_mapped_antisense_pct",
    "Fraction Reads in Cells": "fraction_reads_in_cells_pct",
}

_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/metrics_summary\.csv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["metrics"]
    if "source_path" not in df.columns:
        raise ValueError(
            "cellranger_metrics: input has no 'source_path' column, the raw data "
            "collection must be scanned with polars_kwargs.include_file_paths"
        )
    missing = [c for c in {**_INT_COLUMNS, **_PCT_COLUMNS} if c not in df.columns]
    if missing:
        raise ValueError(f"cellranger_metrics: input lacks columns {missing}")

    exprs = [
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
    ]
    for raw_name, out_name in _INT_COLUMNS.items():
        exprs.append(
            pl.col(raw_name).str.replace_all(",", "").cast(pl.Int64, strict=False).alias(out_name)
        )
    for raw_name, out_name in _PCT_COLUMNS.items():
        exprs.append(
            pl.col(raw_name).str.replace_all("%", "").cast(pl.Float64, strict=False).alias(out_name)
        )

    result = df.select(exprs)
    result = result.with_columns(
        [
            (pl.col(out_name) / 100).alias(f"{out_name.removesuffix('_pct')}_frac")
            for out_name in _PCT_COLUMNS.values()
        ]
    )
    unnamed = result.filter(pl.col("sample").is_null()).height
    if unnamed:
        raise ValueError(
            "cellranger_metrics: a row's source_path does not look like "
            "'cellranger/count/<sample>/outs/metrics_summary.csv'"
        )
    return result.select(list(EXPECTED_SCHEMA)).sort("sample")
