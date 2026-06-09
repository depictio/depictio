"""Canonical VST matrix DC for nf-core/differentialabundance.

Megatest source: ``tables/processed_abundance/all.normalised_counts.tsv`` or the
``vst.tsv`` produced by DESeq2 — wide gene × sample matrix.

Output (ComplexHeatmap-ready):

    feature_id : Utf8          (row index_column)
    gene_symbol: Utf8           (optional row annotation)
    <sample_1> ... <sample_N>   : Float64 numeric columns

ComplexHeatmap uses a string index column + a numeric matrix; column subsetting and
clustering are handled by the renderer.
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_symbol": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/differentialabundance megatest VST matrix — see module docstring."
    )
