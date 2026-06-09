"""Canonical pathway-enrichment DC for nf-core/differentialabundance.

Megatest source: ``tables/gsea/<contrast>/<source>.gsea_report.tsv`` for GSEA, or
``tables/gprofiler/<contrast>.tsv`` for gprofiler2.

Output (canonical schema):

    term         : Utf8         (pathway / GO term)
    nes          : Float64      (signed enrichment score)
    padj         : Float64
    gene_count   : Int64        (gene-set size)
    source       : Utf8         (optional — GO_BP / KEGG / Reactome / Hallmark)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "term": pl.Utf8,
    "nes": pl.Float64,
    "padj": pl.Float64,
    "gene_count": pl.Int64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "source": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/differentialabundance megatest GSEA / gprofiler tables — "
        "see module docstring."
    )
