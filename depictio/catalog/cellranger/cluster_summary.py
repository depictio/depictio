"""One row per graph-based cluster, summarising `cellranger_cell_qc`.

Pure aggregation of the cell hub (`cellranger/cell_qc.py`'s output, joined
via `dc_ref`, no raw file re-read): cluster size, QC medians and the share of
cells CellBender also called.

A template reusing this recipe declares one source, the already-transformed
cell_qc DC::

    transform: {recipe: "cellranger/cluster_summary.py"}
    # SOURCES = [RecipeSource(ref="cells", dc_ref="cellranger_cell_qc")]

Output schema:
    sample : Utf8
    graphclust : Utf8            "C1".."Cn"
    cluster_label : Utf8          "C<n> top1/top2" marker genes
    n_cells : Int64                cells in this cluster
    pct_cells : Float64            % of the sample's cells in this cluster
    median_n_umi : Float64
    median_n_genes : Float64
    median_pct_mito : Float64
    pct_flagged : Float64          % of this cluster's cells with qc_status == "flagged"
    pct_cellbender_cell : Float64  % of this cluster's cells CellBender also called a cell
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

CELL_QC_DC_TAG = "cellranger_cell_qc"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="cells", dc_ref=CELL_QC_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "graphclust": pl.Utf8,
    "cluster_label": pl.Utf8,
    "n_cells": pl.Int64,
    "pct_cells": pl.Float64,
    "median_n_umi": pl.Float64,
    "median_n_genes": pl.Float64,
    "median_pct_mito": pl.Float64,
    "pct_flagged": pl.Float64,
    "pct_cellbender_cell": pl.Float64,
}

_REQUIRED = {
    "sample",
    "graphclust",
    "cluster_label",
    "n_umi",
    "n_genes",
    "pct_mito",
    "qc_status",
    "cellbender_cell",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    cells = sources["cells"]
    missing = _REQUIRED - set(cells.columns)
    if missing:
        raise ValueError(f"cellranger_cluster_summary: input lacks columns {sorted(missing)}")

    totals = cells.group_by("sample").agg(pl.len().cast(pl.Int64).alias("_sample_total"))

    result = (
        cells.group_by(["sample", "graphclust", "cluster_label"])
        .agg(
            pl.len().cast(pl.Int64).alias("n_cells"),
            pl.col("n_umi").median().alias("median_n_umi"),
            pl.col("n_genes").median().alias("median_n_genes"),
            pl.col("pct_mito").median().alias("median_pct_mito"),
            (pl.col("qc_status") == "flagged")
            .cast(pl.Float64)
            .mean()
            .mul(100)
            .alias("pct_flagged"),
            pl.col("cellbender_cell").cast(pl.Float64).mean().mul(100).alias("pct_cellbender_cell"),
        )
        .join(totals, on="sample", how="left")
        .with_columns((pl.col("n_cells") / pl.col("_sample_total") * 100).alias("pct_cells"))
        .drop("_sample_total")
    )
    return result.select(list(EXPECTED_SCHEMA)).sort(["sample", "graphclust"])
