"""Overlapping genes per annotation, from nf-core/genomeqc's GENEOVERLAPS step.

The step (GenomicRanges over the validated GFF) writes one small table per
assembly, ``gene_overlaps/<assembly>.counts.tsv``::

    Statistic                                                Count
    Total number of genes                                    12593
    Number of genes with unresolved strand                   0
    Number of genes fully contained in same strand direction 838
    Number of genes fully contained in opposite strand direction 1349
    Total number of overlapping genes                        4998

transposed here into one row per assembly. Genes nested in another gene on
the same strand are the suspicious ones (a split or duplicated model); nested
on the opposite strand they are often real (a gene in an intron).

Input: every ``gene_overlaps/*.counts.tsv`` under the run, with its path in
``source_path``.

Output schema:
    genome : Utf8                    assembly, from the file name
    total_genes : Int64              genes in the annotation
    unresolved_strand_genes : Int64  genes without a strand
    contained_same_strand : Int64    genes fully inside another on the same strand
    contained_opposite_strand : Int64  genes fully inside another on the opposite strand
    overlapping_genes : Int64        genes overlapping any other
    overlapping_pct : Float64        overlapping genes, percent of all genes
    contained_same_strand_pct : Float64  same-strand nested genes, percent of all genes
    not_overlapping_genes : Int64    genes overlapping no other
    overlapping_not_nested : Int64   genes overlapping another without lying inside it

The last two split the annotation with the nested genes into four parts that add up
to ``total_genes``, the composition the Annotation tab stacks per assembly. A
nested gene overlaps the gene it sits in, so it is one of the overlapping genes.
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCE_PATH_COL = "source_path"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="counts",
        glob_pattern="**/gene_overlaps/*.counts.tsv",
        format="csv",
        read_kwargs={"separator": "\t", "infer_schema_length": 0},
        source_path=SOURCE_PATH_COL,
        input_schema={"Statistic": pl.Utf8, "Count": pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "total_genes": pl.Int64,
    "unresolved_strand_genes": pl.Int64,
    "contained_same_strand": pl.Int64,
    "contained_opposite_strand": pl.Int64,
    "overlapping_genes": pl.Int64,
    "overlapping_pct": pl.Float64,
    "contained_same_strand_pct": pl.Float64,
    "not_overlapping_genes": pl.Int64,
    "overlapping_not_nested": pl.Int64,
}

#: The step's row label -> output column.
STATISTICS: dict[str, str] = {
    "Total number of genes": "total_genes",
    "Number of genes with unresolved strand": "unresolved_strand_genes",
    "Number of genes fully contained in same strand direction": "contained_same_strand",
    "Number of genes fully contained in opposite strand direction": "contained_opposite_strand",
    "Total number of overlapping genes": "overlapping_genes",
}


def genome_of(source_path: str) -> str:
    return PurePosixPath(str(source_path).replace("\\", "/")).name.removesuffix(".counts.tsv")


def _share(num: str) -> pl.Expr:
    return (
        pl.when(pl.col("total_genes") > 0)
        .then((pl.col(num) * 100.0 / pl.col("total_genes")).round(2))
        .otherwise(None)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["counts"]
    long = raw.select(
        pl.col(SOURCE_PATH_COL).map_elements(genome_of, return_dtype=pl.Utf8).alias("genome"),
        pl.col("Statistic")
        .cast(pl.Utf8)
        .str.strip_chars()
        .replace_strict(STATISTICS, default=None)
        .alias("column"),
        pl.col("Count").cast(pl.Int64, strict=False).alias("count"),
    ).drop_nulls("column")
    if long.is_empty():
        raise ValueError("genomeqc gene_overlaps: no known statistic in the overlap tables")
    wide = long.pivot(on="column", index="genome", values="count", aggregate_function="first")
    for column in STATISTICS.values():
        if column not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Int64).alias(column))
    return (
        wide.with_columns(
            _share("overlapping_genes").alias("overlapping_pct"),
            _share("contained_same_strand").alias("contained_same_strand_pct"),
            (pl.col("total_genes") - pl.col("overlapping_genes"))
            .clip(lower_bound=0)
            .alias("not_overlapping_genes"),
            (
                pl.col("overlapping_genes")
                - pl.col("contained_same_strand")
                - pl.col("contained_opposite_strand")
            )
            .clip(lower_bound=0)
            .alias("overlapping_not_nested"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort("genome")
    )
