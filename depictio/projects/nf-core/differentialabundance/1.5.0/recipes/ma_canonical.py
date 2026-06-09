"""Canonical MA-plot DC for nf-core/differentialabundance.

Megatest source: ``tables/differential/<contrast>.tsv`` — columns include ``gene_id``,
``baseMean``, ``log2FoldChange``, ``padj``, ``gene_symbol``.

Output (canonical schema, see schemas.py):

    feature_id          : Utf8
    avg_log_intensity   : Float64   (log10(baseMean + 1))
    log2_fold_change    : Float64
    significance        : Float64   (padj)
    label               : Utf8      (optional — gene_symbol)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "avg_log_intensity": pl.Float64,
    "log2_fold_change": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "significance": pl.Float64,
    "label": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/differentialabundance megatest "
        "(tables/differential/*.tsv) — see module docstring."
    )
