"""The filtering waterfall: how many barcodes survive each step, per sample.

Every number here already exists somewhere on the dashboard, and that is the
problem this output solves: raw barcodes are on the knee curve's axis, called
cells are a Cell Ranger metric, CellBender's cells are in its own metrics file
and QC-passing cells are a share on a gauge. Nobody can read a retention chain
off four tiles in three sections. One row per sample with the four stages as
four columns is what the `attrition` card layout takes.

The stages are in pipeline order and the order is the content:

    barcodes_observed -> cells_called -> cellbender_cells -> cells_qc_pass

`cellbender_cells` counts the called cells CellBender ALSO kept (the cell hub's
`cellbender_cell`), not CellBender's own total, so the four numbers are nested
subsets and the chart is a real funnel rather than four unrelated counts. It is
0 for a run launched with `--skip_cellbender`, which the dashboard text says to
read as "not run".

A template reusing this recipe declares two sources, both already shared by
`dc_ref`::

    SOURCES = [
        RecipeSource(ref="cell_qc", dc_ref="cellranger_cell_qc"),
        RecipeSource(ref="raw_barcodes", dc_ref="cellranger_raw_barcodes_raw"),
    ]

Output schema:
    sample : Utf8
    barcodes_observed : Int64   barcodes in raw_feature_bc_matrix (background droplets included)
    cells_called : Int64         barcodes Cell Ranger kept in the filtered matrix
    cellbender_cells : Int64     of those, the ones CellBender also called cells
    cells_qc_pass : Int64        of those called, the ones no MAD rule flagged
    pct_called : Float64         cells_called / barcodes_observed, as a percent
    pct_qc_pass : Float64        cells_qc_pass / cells_called, as a percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cellranger_samples import with_sample_column

CELL_QC_DC_TAG = "cellranger_cell_qc"
RAW_BARCODES_DC_TAG = "cellranger_raw_barcodes_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="cell_qc", dc_ref=CELL_QC_DC_TAG),
    RecipeSource(ref="raw_barcodes", dc_ref=RAW_BARCODES_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "barcodes_observed": pl.Int64,
    "cells_called": pl.Int64,
    "cellbender_cells": pl.Int64,
    "cells_qc_pass": pl.Int64,
    "pct_called": pl.Float64,
    "pct_qc_pass": pl.Float64,
}

_RAW_BARCODES_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/raw_feature_bc_matrix/"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    cell_qc = sources["cell_qc"]
    raw_barcodes = sources["raw_barcodes"]

    required = {"sample", "barcode", "qc_status", "cellbender_cell"}
    if missing := required - set(cell_qc.columns):
        raise ValueError(f"cellranger_cell_funnel: cell_qc lacks columns {sorted(missing)}")

    observed = (
        with_sample_column(
            raw_barcodes, _RAW_BARCODES_SAMPLE_RE, RAW_BARCODES_DC_TAG, "cellranger_cell_funnel"
        )
        .group_by("sample")
        .agg(pl.len().cast(pl.Int64).alias("barcodes_observed"))
    )
    if observed.height == 0:
        raise ValueError("cellranger_cell_funnel: no raw barcode list matched the expected layout")

    called = cell_qc.group_by("sample").agg(
        pl.len().cast(pl.Int64).alias("cells_called"),
        pl.col("cellbender_cell").cast(pl.Int64).sum().alias("cellbender_cells"),
        (pl.col("qc_status") == "pass").cast(pl.Int64).sum().alias("cells_qc_pass"),
    )

    result = called.join(observed, on="sample", how="left").with_columns(
        pl.col("barcodes_observed").cast(pl.Int64),
    )
    result = result.with_columns(
        (pl.col("cells_called") / pl.col("barcodes_observed") * 100).alias("pct_called"),
        (pl.col("cells_qc_pass") / pl.col("cells_called") * 100).alias("pct_qc_pass"),
    )
    return result.select(list(EXPECTED_SCHEMA)).sort("sample")
