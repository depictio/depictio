"""Genes x samples: the mean transcripts per cell of the panel's most abundant
genes, one column per sample, for a clustered heatmap of the tissue sections.

Reads the ``spot2cell/cellxgene_<sample>_<method>.csv`` files (see
``spot2cell/cells.py``). The value is log1p of the mean count per cell, so a
section with more cells does not outweigh one with fewer, and a handful of very
abundant genes does not flatten the rest of the scale. The ``TOP_N`` genes with
the most transcripts over the whole run are kept.

One column per sample: when the input mixes segmentation methods, each column
is ``<sample> (<method>)`` instead, so point the DC at a single method with
``source_overrides`` for a per-sample heatmap.

Output: ``gene`` + one Float64 column per sample, named at ingest (outside the
declared schema), rows in decreasing order of transcripts over the run.
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
    "gene": pl.Utf8,
}
# One log1p(mean count per cell) column per sample: named only at ingest.

#: genes kept, ranked by transcripts over the run
TOP_N = 40

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


def _column(path: str, several_methods: bool) -> str:
    name = path.rsplit("/", 1)[-1]
    match = _NAME.match(name)
    if not match:
        return name.removeprefix("cellxgene_").removesuffix(".csv")
    return f"{match.group(1)} ({match.group(2)})" if several_methods else match.group(1)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Wide spot2cell tables -> the TOP_N genes x samples, log1p mean per cell."""
    raw = sources["cellxgene"]
    genes = sorted(c for c in raw.columns if c not in NON_GENE)
    if not genes:
        raise ValueError("spot2cell gene_heatmap: the cellxgene tables carry no gene column")
    paths = raw["source_path"].unique().to_list()
    methods = {(_NAME.match(p.rsplit("/", 1)[-1]) or [None, None, None])[2] for p in paths}
    columns = {p: _column(p, len(methods) > 1) for p in paths}

    wide = raw.select(
        pl.col("source_path").replace_strict(columns, return_dtype=pl.Utf8).alias("column"),
        pl.col("CellID").cast(pl.Float64, strict=False).cast(pl.Int64).alias("cell_id"),
        *[
            pl.col(g).cast(pl.Float64, strict=False).fill_null(0).cast(pl.Int64).alias(g)
            for g in genes
        ],
    ).filter(pl.col("cell_id").is_not_null() & (pl.col("cell_id") != 0))

    long = (
        wide.unpivot(index=["column", "cell_id"], on=genes, variable_name="gene", value_name="n")
        .group_by(["column", "gene"])
        .agg(pl.col("n").sum().alias("total"), pl.col("n").mean().alias("mean"))
    )
    top = (
        long.group_by("gene")
        .agg(pl.col("total").sum().cast(pl.Int64).alias("total_counts"))
        .sort(["total_counts", "gene"], descending=[True, False])
        .head(TOP_N)
    )
    matrix = (
        long.join(top.select("gene"), on="gene", how="semi")
        .with_columns(pl.col("mean").log1p())
        .pivot(on="column", index="gene", values="mean")
    )
    sample_cols = sorted(c for c in matrix.columns if c != "gene")
    # `top` is already ranked; a left join keeps its order.
    return top.join(matrix, on="gene", how="left", maintain_order="left").select(
        pl.col("gene").cast(pl.Utf8),
        *[pl.col(c).fill_null(0.0).cast(pl.Float64) for c in sample_cols],
    )
