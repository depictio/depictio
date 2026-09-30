"""spot2cell's cell-by-gene tables melted to one row per (cell, gene) with at
least one transcript, so a gene picker filters cells and a box shows a gene's
per-cell spread.

Reads the same ``spot2cell/cellxgene_<sample>_<method>.csv`` files as
``spot2cell/cells.py`` (see there for the file shape). Zero counts are dropped:
a Molecular Cartography panel is ~100 genes and most cells hold a handful, so
the long table stays a small multiple of the cell count instead of cells x
panel. A gene absent from a cell therefore has no row, which is what a "cells
expressing" filter wants; a distribution of counts per cell reads "among the
cells that express it".

A DC restricts the glob to one method through ``source_overrides`` when the
long table should follow a single segmentation.

Output schema:
    sample : Utf8               sample id of the samplesheet
    segmentation_method : Utf8  mesmer | cellpose | stardist | ilastik
    cell_id : Int64             label value in the filtered mask
    cell_key : Utf8             sample:method:cell_id
    gene : Utf8                 gene of the panel
    count : Int64               transcripts of that gene assigned to the cell
    frac_of_cell : Float64      count over the cell's total (0 to 1)
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
    "cell_id": pl.Int64,
    "cell_key": pl.Utf8,
    "gene": pl.Utf8,
    "count": pl.Int64,
    "frac_of_cell": pl.Float64,
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


def _sample_method(path: str) -> tuple[str, str]:
    name = path.rsplit("/", 1)[-1]
    match = _NAME.match(name)
    if match:
        return match.group(1), match.group(2)
    return name.removeprefix("cellxgene_").removesuffix(".csv"), "unknown"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Wide spot2cell tables -> non-zero (cell, gene) counts."""
    raw = sources["cellxgene"]
    genes = sorted(c for c in raw.columns if c not in NON_GENE)
    if not genes:
        raise ValueError("spot2cell cell_genes_long: the cellxgene tables carry no gene column")
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
    wide = wide.with_columns(pl.sum_horizontal(genes).alias("_total"))

    long = (
        wide.unpivot(
            index=["sample", "segmentation_method", "cell_id", "_total"],
            on=genes,
            variable_name="gene",
            value_name="count",
        )
        .filter(pl.col("count") > 0)
        .with_columns(
            pl.concat_str(
                [pl.col("sample"), pl.col("segmentation_method"), pl.col("cell_id").cast(pl.Utf8)],
                separator=":",
            ).alias("cell_key"),
            (pl.col("count") / pl.col("_total")).cast(pl.Float64).alias("frac_of_cell"),
            pl.col("count").cast(pl.Int64),
        )
    )
    return long.select(list(EXPECTED_SCHEMA)).sort(
        ["sample", "segmentation_method", "cell_id", "gene"]
    )
