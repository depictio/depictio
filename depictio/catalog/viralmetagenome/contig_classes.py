"""Taxonomic call of every de novo contig before clustering.

Before it clusters the contigs, viralmetagenome classifies each one with
Kraken2 and Kaiju and merges the two calls into one per contig
(``--precluster_classifiers``, ``--arguments_extract_precluster``):
``assembly/polishing/intermediate/precluster/merged_classifications/[<prefix>-]<sample>.resolved.txt``,
three tab-separated columns without a header: ``C`` or ``U`` (classified or
not), the sequence id and the taxon id (``0`` when unclassified). The file also
lists the reference-pool sequences the run clusters with
(``--cluster_with_reference_pool``); they are kept here and drop out when the
contigs collection joins on its own contig ids.

Output schema:
    sample : Utf8          sample id, read off the file name
    contig : Utf8          sequence id as the assembler (or the pool) named it
    classification : Utf8  Classified or Unclassified
    taxid : Utf8           NCBI taxon id of the merged call, null when unclassified
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import strip_global_prefix

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="resolved",
        glob_pattern="assembly/polishing/intermediate/precluster/merged_classifications/*.resolved.txt",
        format="tsv",
        read_kwargs={"has_header": False, "infer_schema_length": 0, "quote_char": None},
        source_path="source_path",
        input_schema={"column_1": pl.Utf8, "column_2": pl.Utf8, "source_path": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "contig": pl.Utf8,
    "classification": pl.Utf8,
    "taxid": pl.Utf8,
}


def _sample(path: str) -> str:
    name = PurePosixPath(path).name.removesuffix(".resolved.txt")
    return strip_global_prefix(name)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["resolved"]
    taxid = pl.col("column_3").cast(pl.Utf8) if "column_3" in df.columns else pl.lit(None)
    out = df.select(
        pl.col("source_path").map_elements(_sample, return_dtype=pl.Utf8).alias("sample"),
        pl.col("column_2").str.strip_chars().alias("contig"),
        pl.when(pl.col("column_1").str.strip_chars() == "C")
        .then(pl.lit("Classified"))
        .otherwise(pl.lit("Unclassified"))
        .alias("classification"),
        pl.when(taxid.str.strip_chars().is_in(["0", ""]))
        .then(None)
        .otherwise(taxid)
        .alias("taxid"),
    )
    return (
        out.filter(pl.col("contig").is_not_null())
        .unique(subset=["sample", "contig"], keep="first")
        .sort(["sample", "contig"])
    )
