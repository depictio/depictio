"""What each sample is made of: its cells per cluster and per cell type.

One row per (sample, annotation, label): the cells of the sample carrying that
label and their share of the sample. Two annotations are stacked in one frame so
a single faceted bar chart compares them: ``cluster`` (Leiden, or the
segmentation method's own clusters) and ``cell type`` (fluorescence
annotation). An annotation the run did not produce is left out; a run with
neither (e.g. Visium HD without ``--use_scanpy_preprocessing``) gets one
``cluster`` row per sample labelled ``unassigned``, which says exactly that.

The labels of an annotation are ranked by their cell count over the whole run,
the ``TOP_N`` most abundant kept and the rest pooled into ``Other``, and the
rows come out in that order so a bar chart stacks the largest group first.

Input: the ``sopa_cells`` data collection (the ``sopa/cells`` recipe output).

Output schema:
    sample : Utf8        store the cells belong to
    annotation : Utf8    "cluster" or "cell type"
    label : Utf8         cluster / cell type, "Other" or "unassigned"
    n_cells : Int64      cells of the sample with that label
    pct_cells : Float64  share of the sample's cells, in percent
    rank : Int64         label rank over the run (1 = most cells; Other last)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag of the normalised cell table (``sopa/cells``).
CELLS_DC_TAG = "sopa_cells"

SOURCES: list[RecipeSource] = [RecipeSource(ref="cells", dc_ref=CELLS_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "annotation": pl.Utf8,
    "label": pl.Utf8,
    "n_cells": pl.Int64,
    "pct_cells": pl.Float64,
    "rank": pl.Int64,
}

TOP_N = 12
ANNOTATIONS = {"cluster": "cluster", "cell_type": "cell type"}
OTHER = "Other"
UNASSIGNED = "unassigned"


def _one(cells: pl.DataFrame, column: str, name: str) -> pl.DataFrame:
    frame = cells.select(
        "sample", pl.col(column).cast(pl.Utf8).fill_null(UNASSIGNED).alias("label")
    )
    totals = (
        frame.group_by("label")
        .agg(pl.len().alias("t"))
        .sort(["t", "label"], descending=[True, False])
    )
    keep = totals.head(TOP_N)["label"].to_list()
    frame = frame.with_columns(
        pl.when(pl.col("label").is_in(keep))
        .then(pl.col("label"))
        .otherwise(pl.lit(OTHER))
        .alias("label")
    )
    rank = {label: i + 1 for i, label in enumerate(keep)}
    counts = frame.group_by("sample", "label").agg(pl.len().cast(pl.Int64).alias("n_cells"))
    return counts.with_columns(
        pl.lit(name).alias("annotation"),
        (100.0 * pl.col("n_cells") / pl.col("n_cells").sum().over("sample")).alias("pct_cells"),
        pl.col("label")
        .replace_strict(rank, default=len(keep) + 1, return_dtype=pl.Int64)
        .alias("rank"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    cells = sources["cells"]
    if cells is None or cells.is_empty():
        raise ValueError("sopa composition: the cell table is empty")
    parts = [
        _one(cells, column, name)
        for column, name in ANNOTATIONS.items()
        if column in cells.columns and cells[column].null_count() < cells.height
    ]
    if not parts:
        parts = [
            _one(
                cells.with_columns(pl.lit(None, dtype=pl.Utf8).alias("cluster")),
                "cluster",
                "cluster",
            )
        ]
    return pl.concat(parts).select(list(EXPECTED_SCHEMA)).sort("annotation", "rank", "sample")
