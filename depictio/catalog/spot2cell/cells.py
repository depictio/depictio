"""One row per segmented cell from spot2cell's cell-by-gene tables: where the cell
is, its shape, how many transcripts it holds and which gene dominates it.

nf-core/molkart's spot2cell (``bin/spot2cell.py``) writes one wide CSV per sample
and segmentation method, ``spot2cell/cellxgene_<sample>_<method>.csv``: ``CellID``
(the label value of the filtered segmentation mask), one integer column per gene
of the spot table, then the cell's regionprops (``X_centroid``, ``Y_centroid``,
``Area``, axis lengths, eccentricity, solidity, extent, orientation). The gene
columns are the genes present in that sample's spot table, so two files of one
run need not carry the same set; the glob is concatenated diagonally and a gene
a file lacks counts 0.

``cell_id`` is kept as the label value, so it equals the pixel value of the
matching ``segmentation/filtered_masks/<sample>_<method>_filtered.tif``: the image
viewer colours the labels overlay through it. It is only unique within one
(sample, method) pair; ``cell_key`` joins the three for links, tables and
record cards.

``dominant_gene`` is the gene with the most transcripts in the cell (ties broken
alphabetically, ``none`` for a cell no spot was assigned to): a cluster-free
categorical colouring for the image, meaningful on any panel.

The sample and method come from the file name, since the table carries neither.
A DC can restrict the glob to one method through ``source_overrides`` (e.g.
``**/cellxgene_*_mesmer.csv``) to get the cells of that segmentation alone, the
shape the image viewer's points overlay needs.

Output schema:
    sample : Utf8                 sample id of the samplesheet
    segmentation_method : Utf8    mesmer | cellpose | stardist | ilastik
    cell_id : Int64               label value in the filtered mask
    cell_key : Utf8               sample:method:cell_id, unique across the run
    x_centroid, y_centroid : Float64   centroid, level-0 pixels (column, row)
    area : Float64                pixels
    major_axis_length, minor_axis_length, eccentricity, solidity, extent,
    orientation : Float64         skimage regionprops of the label
    total_counts : Int64          transcripts assigned to the cell
    n_genes : Int64               genes with at least one transcript
    dominant_gene : Utf8          most abundant gene, "none" when empty
    dominant_gene_frac : Float64  its share of the cell's transcripts (0 to 1)
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
    "x_centroid": pl.Float64,
    "y_centroid": pl.Float64,
    "area": pl.Float64,
    "major_axis_length": pl.Float64,
    "minor_axis_length": pl.Float64,
    "eccentricity": pl.Float64,
    "solidity": pl.Float64,
    "extent": pl.Float64,
    "orientation": pl.Float64,
    "total_counts": pl.Int64,
    "n_genes": pl.Int64,
    "dominant_gene": pl.Utf8,
    "dominant_gene_frac": pl.Float64,
}

#: spot2cell's regionprops columns -> output names; everything else but CellID is a gene
PROPS = {
    "X_centroid": "x_centroid",
    "Y_centroid": "y_centroid",
    "Area": "area",
    "MajorAxisLength": "major_axis_length",
    "MinorAxisLength": "minor_axis_length",
    "Eccentricity": "eccentricity",
    "Solidity": "solidity",
    "Extent": "extent",
    "Orientation": "orientation",
}
NON_GENE = {"CellID", "source_path", *PROPS}
METHODS = ("mesmer", "cellpose", "stardist", "ilastik")
_NAME = re.compile(r"^cellxgene_(.+)_(" + "|".join(METHODS) + r")\.csv$")


def _sample_method(path: str) -> tuple[str, str]:
    name = path.rsplit("/", 1)[-1]
    match = _NAME.match(name)
    if match:
        return match.group(1), match.group(2)
    stem = name.removeprefix("cellxgene_").removesuffix(".csv")
    return stem, "unknown"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Wide spot2cell tables -> one typed row per cell."""
    raw = sources["cellxgene"]
    genes = sorted(c for c in raw.columns if c not in NON_GENE)
    keys = {p: _sample_method(p) for p in raw["source_path"].unique().to_list()}
    counts = [pl.col(g).cast(pl.Float64, strict=False).fill_null(0).cast(pl.Int64) for g in genes]

    frame = raw.select(
        pl.col("source_path")
        .replace_strict({p: s for p, (s, _) in keys.items()}, return_dtype=pl.Utf8)
        .alias("sample"),
        pl.col("source_path")
        .replace_strict({p: m for p, (_, m) in keys.items()}, return_dtype=pl.Utf8)
        .alias("segmentation_method"),
        pl.col("CellID").cast(pl.Float64, strict=False).cast(pl.Int64).alias("cell_id"),
        *[
            (pl.col(src) if src in raw.columns else pl.lit(None))
            .cast(pl.Float64, strict=False)
            .alias(dst)
            for src, dst in PROPS.items()
        ],
        *[c.alias(g) for c, g in zip(counts, genes)],
    ).filter(pl.col("cell_id").is_not_null() & (pl.col("cell_id") != 0))

    if genes:
        stacked = pl.concat_list([pl.col(g) for g in genes])
        frame = frame.with_columns(
            pl.sum_horizontal(genes).cast(pl.Int64).alias("total_counts"),
            pl.sum_horizontal([(pl.col(g) > 0).cast(pl.Int64) for g in genes])
            .cast(pl.Int64)
            .alias("n_genes"),
            stacked.list.max().alias("_max"),
            stacked.list.arg_max().alias("_arg"),
        ).with_columns(
            pl.when(pl.col("total_counts") > 0)
            .then(
                pl.col("_arg").replace_strict(
                    dict(enumerate(genes)), return_dtype=pl.Utf8, default=None
                )
            )
            .otherwise(pl.lit("none"))
            .alias("dominant_gene"),
            pl.when(pl.col("total_counts") > 0)
            .then(pl.col("_max") / pl.col("total_counts"))
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("dominant_gene_frac"),
        )
    else:
        frame = frame.with_columns(
            pl.lit(0, dtype=pl.Int64).alias("total_counts"),
            pl.lit(0, dtype=pl.Int64).alias("n_genes"),
            pl.lit("none", dtype=pl.Utf8).alias("dominant_gene"),
            pl.lit(0.0, dtype=pl.Float64).alias("dominant_gene_frac"),
        )

    frame = frame.with_columns(
        pl.concat_str(
            [pl.col("sample"), pl.col("segmentation_method"), pl.col("cell_id").cast(pl.Utf8)],
            separator=":",
        ).alias("cell_key")
    )
    return frame.select(list(EXPECTED_SCHEMA)).sort(["sample", "segmentation_method", "cell_id"])
