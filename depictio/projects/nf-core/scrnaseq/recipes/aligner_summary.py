"""One row per `--aligner` route, the headline numbers a reader compares them on.

Each route reports its own idea of "cells called" and "mapping rate" through a
different tool (Cell Ranger's metrics_summary.csv, QCatch for simpleaf, kb
count's run_info.json for kallisto), so this recipe is the translation layer:
it picks the one number from each route's own catalog output that means the
same thing, rather than asking the dashboard to know three schemas. A route
the run did not use (most commonly simpleaf and kallisto, which are not the
pipeline's default `--aligner`) is simply absent from the output, every
non-Cell-Ranger source is `optional=True`, so a Cell Ranger-only run still
produces a valid one-row table instead of failing.

kallisto's `median_umi_per_cell` is null: getting it would mean reading the
count matrix itself, out of scope for this table (see
`kallisto/run_metrics.py`).

Sources, all read through `dc_ref` from already-ingested catalog outputs:
    cellranger_metrics : cellranger/metrics_summary.py output (required)
    cellranger_cellbender_barcodes_raw : raw scan, CellBender's Cell Ranger-route cell list
    qcatch_metrics_summary : qcatch/metrics_summary.py output (simpleaf's own cell call)
    simpleaf_cellbender_metrics : cellbender/metrics.py output, scanned over the simpleaf route
    simpleaf_mapping_metrics : simpleaf/mapping_metrics.py output
    kallisto_run_metrics : kallisto/run_metrics.py output
    kallisto_cellbender_metrics : cellbender/metrics.py output, scanned over the kallisto route

Output schema:
    aligner : Utf8                "cellranger" | "simpleaf" | "kallisto"
    cells_called : Int64           the route's own primary cell call
    cellbender_cells : Int64       CellBender's cell call for the same route, null if not run
    median_umi_per_cell : Float64  null when not computed for this route (kallisto)
    mapping_rate : Float64         reads mapped / reads processed, 0-1
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

CELLRANGER_METRICS_DC_TAG = "cellranger_metrics"
CELLRANGER_CELLBENDER_DC_TAG = "cellranger_cellbender_barcodes_raw"
QCATCH_METRICS_DC_TAG = "qcatch_metrics_summary"
SIMPLEAF_CELLBENDER_DC_TAG = "simpleaf_cellbender_metrics"
SIMPLEAF_MAPPING_DC_TAG = "simpleaf_mapping_metrics"
KALLISTO_RUN_DC_TAG = "kallisto_run_metrics"
KALLISTO_CELLBENDER_DC_TAG = "kallisto_cellbender_metrics"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="cellranger_metrics", dc_ref=CELLRANGER_METRICS_DC_TAG),
    RecipeSource(ref="cellranger_cellbender", dc_ref=CELLRANGER_CELLBENDER_DC_TAG, optional=True),
    RecipeSource(ref="qcatch_metrics", dc_ref=QCATCH_METRICS_DC_TAG, optional=True),
    RecipeSource(ref="simpleaf_cellbender", dc_ref=SIMPLEAF_CELLBENDER_DC_TAG, optional=True),
    RecipeSource(ref="simpleaf_mapping", dc_ref=SIMPLEAF_MAPPING_DC_TAG, optional=True),
    RecipeSource(ref="kallisto_run", dc_ref=KALLISTO_RUN_DC_TAG, optional=True),
    RecipeSource(ref="kallisto_cellbender", dc_ref=KALLISTO_CELLBENDER_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "aligner": pl.Utf8,
    "cells_called": pl.Int64,
    "cellbender_cells": pl.Int64,
    "median_umi_per_cell": pl.Float64,
    "mapping_rate": pl.Float64,
}

#: 10x GEM-well suffix Cell Ranger's CellBender barcodes carry, e.g. "-1"
_GEM_SUFFIX_RE = r"-\d+$"


def _barcode_count(df: pl.DataFrame | None) -> int | None:
    if df is None or df.height == 0 or "barcode" not in df.columns:
        return None
    n = (
        df.select(
            pl.col("barcode").cast(pl.Utf8).str.replace(_GEM_SUFFIX_RE, "").alias("barcode_core")
        )
        .drop_nulls()
        .unique()
        .height
    )
    return n or None


def _first_row(df: pl.DataFrame | None) -> dict | None:
    if df is None or df.height == 0:
        return None
    # Aggregate across samples (mean) so a multi-sample run still yields one row.
    numeric_cols = [c for c, dt in df.schema.items() if dt.is_numeric()]
    if not numeric_cols:
        return df.row(0, named=True)
    return df.select([pl.col(c).mean() for c in numeric_cols]).row(0, named=True)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    cellranger_metrics = _first_row(sources.get("cellranger_metrics"))
    if cellranger_metrics is None:
        raise ValueError("aligner_summary: 'cellranger_metrics' source produced no rows")

    rows: list[dict] = []

    reads_mapped_pct = cellranger_metrics.get("reads_mapped_confidently_transcriptome_pct")
    rows.append(
        {
            "aligner": "cellranger",
            "cells_called": cellranger_metrics.get("estimated_cells"),
            "cellbender_cells": _barcode_count(sources.get("cellranger_cellbender")),
            "median_umi_per_cell": cellranger_metrics.get("median_umi_counts_per_cell"),
            "mapping_rate": (reads_mapped_pct / 100.0) if reads_mapped_pct is not None else None,
        }
    )

    qcatch = _first_row(sources.get("qcatch_metrics"))
    simpleaf_cellbender = _first_row(sources.get("simpleaf_cellbender"))
    simpleaf_mapping = _first_row(sources.get("simpleaf_mapping"))
    if qcatch is not None or simpleaf_cellbender is not None or simpleaf_mapping is not None:
        rows.append(
            {
                "aligner": "simpleaf",
                "cells_called": (qcatch or {}).get("retained_cells"),
                "cellbender_cells": (simpleaf_cellbender or {}).get("found_cells"),
                "median_umi_per_cell": (qcatch or {}).get("median_umi_per_retained_cell"),
                "mapping_rate": (simpleaf_mapping or {}).get("mapping_rate"),
            }
        )

    kallisto_run = _first_row(sources.get("kallisto_run"))
    kallisto_cellbender = _first_row(sources.get("kallisto_cellbender"))
    if kallisto_run is not None or kallisto_cellbender is not None:
        rows.append(
            {
                "aligner": "kallisto",
                "cells_called": (kallisto_run or {}).get("cells_called"),
                "cellbender_cells": (kallisto_cellbender or {}).get("found_cells"),
                "median_umi_per_cell": None,
                "mapping_rate": (kallisto_run or {}).get("p_pseudoaligned"),
            }
        )

    df = pl.DataFrame(rows, infer_schema_length=None)
    for column, dtype in EXPECTED_SCHEMA.items():
        if column not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=dtype).alias(column))
    return df.select(
        [pl.col(column).cast(dtype, strict=False) for column, dtype in EXPECTED_SCHEMA.items()]
    ).sort("aligner")
