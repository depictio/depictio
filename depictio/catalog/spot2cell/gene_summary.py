"""Per sample, segmentation method and gene: how many transcripts the cells hold,
in how many cells, and at what level, from spot2cell's cell-by-gene tables.

Reads the ``spot2cell/cellxgene_<sample>_<method>.csv`` files (see
``spot2cell/cells.py`` for their shape). A gene one sample's spot table lacks
counts 0 in that sample, so every (sample, method) pair lists the run's whole
panel and a bar of one gene across samples never has a silent gap.

The ``mean_per_cell`` / ``frac_cells_expressing`` pair is the dot-plot shape
(size = fraction expressing, colour = mean level) with the sample as the group,
which reads as "which genes this tissue section expresses, and how broadly".

Output schema:
    sample : Utf8                    sample id of the samplesheet
    segmentation_method : Utf8       mesmer | cellpose | stardist | ilastik
    gene : Utf8                      gene of the panel
    total_counts : Int64             transcripts of the gene assigned to cells
    cells_expressing : Int64         cells with at least one transcript of it
    n_cells : Int64                  cells of the (sample, method) pair
    frac_cells_expressing : Float64  cells_expressing / n_cells (0 to 1)
    mean_per_cell : Float64          total_counts / n_cells
    mean_per_expressing_cell : Float64  total_counts / cells_expressing, 0 when none
    share_of_counts_pct : Float64    the gene's share of the pair's assigned transcripts
    rank : Int64                     1 = most transcripts within the pair
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="cellxgene",
        glob_pattern="**/cellxgene_*.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "segmentation_method": pl.Utf8,
    "gene": pl.Utf8,
    "total_counts": pl.Int64,
    "cells_expressing": pl.Int64,
    "n_cells": pl.Int64,
    "frac_cells_expressing": pl.Float64,
    "mean_per_cell": pl.Float64,
    "mean_per_expressing_cell": pl.Float64,
    "share_of_counts_pct": pl.Float64,
    "rank": pl.Int64,
}

NON_GENE = {
    "CellID",
    "source_path",
    "X_centroid",
    "Y_centroid",
    "Area",
    "MajorAxisLength",
    "MinorAxisLength",
    "Eccentricity",
    "Solidity",
    "Extent",
    "Orientation",
}
METHODS = ("mesmer", "cellpose", "stardist", "ilastik")
_NAME = re.compile(r"^cellxgene_(.+)_(" + "|".join(METHODS) + r")\.csv$")
GROUP = ["sample", "segmentation_method"]


def _sample_method(path: str) -> tuple[str, str]:
    name = path.rsplit("/", 1)[-1]
    match = _NAME.match(name)
    if match:
        return match.group(1), match.group(2)
    return name.removeprefix("cellxgene_").removesuffix(".csv"), "unknown"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Wide spot2cell tables -> one row per (sample, method, gene)."""
    raw = sources["cellxgene"]
    genes = sorted(c for c in raw.columns if c not in NON_GENE)
    if not genes:
        raise ValueError("spot2cell gene_summary: the cellxgene tables carry no gene column")
    keys = {p: _sample_method(p) for p in raw["source_path"].unique().to_list()}

    wide = raw.select(
        pl.col("source_path")
        .replace_strict({p: s for p, (s, _) in keys.items()}, return_dtype=pl.Utf8)
        .alias("sample"),
        pl.col("source_path")
        .replace_strict({p: m for p, (_, m) in keys.items()}, return_dtype=pl.Utf8)
        .alias("segmentation_method"),
        pl.col("CellID").cast(pl.Float64, strict=False).cast(pl.Int64).alias("cell_id"),
        *[
            pl.col(g).cast(pl.Float64, strict=False).fill_null(0).cast(pl.Int64).alias(g)
            for g in genes
        ],
    ).filter(pl.col("cell_id").is_not_null() & (pl.col("cell_id") != 0))

    per_gene = (
        wide.unpivot(index=[*GROUP, "cell_id"], on=genes, variable_name="gene", value_name="n")
        .group_by([*GROUP, "gene"])
        .agg(
            pl.col("n").sum().cast(pl.Int64).alias("total_counts"),
            (pl.col("n") > 0).sum().cast(pl.Int64).alias("cells_expressing"),
            pl.len().cast(pl.Int64).alias("n_cells"),
        )
    )
    pair_total = pl.col("total_counts").sum().over(GROUP)
    return (
        per_gene.with_columns(
            (pl.col("cells_expressing") / pl.col("n_cells"))
            .cast(pl.Float64)
            .alias("frac_cells_expressing"),
            (pl.col("total_counts") / pl.col("n_cells")).cast(pl.Float64).alias("mean_per_cell"),
            pl.when(pl.col("cells_expressing") > 0)
            .then(pl.col("total_counts") / pl.col("cells_expressing"))
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("mean_per_expressing_cell"),
            pl.when(pair_total > 0)
            .then(100.0 * pl.col("total_counts") / pair_total)
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("share_of_counts_pct"),
            pl.col("total_counts")
            .rank(method="ordinal", descending=True)
            .over(GROUP)
            .cast(pl.Int64)
            .alias("rank"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort([*GROUP, "rank"])
    )
