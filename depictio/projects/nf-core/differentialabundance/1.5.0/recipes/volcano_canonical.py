"""Canonical volcano DC for nf-core/differentialabundance.

Megatest source: ``s3://nf-core-awsmegatests/differentialabundance/results-<sha>/tables/differential/``
  → one TSV per contrast, columns include ``gene_id``, ``log2FoldChange``, ``padj``,
    ``gene_symbol`` (DESeq2 / limma output).

Output: long table concatenated across contrasts, with the canonical volcano schema
(see depictio/models/components/advanced_viz/schemas.py):

    feature_id    : Utf8
    effect_size   : Float64
    significance  : Float64
    label         : Utf8     (optional — gene_symbol)
    category      : Utf8     (optional — contrast id)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "effect_size": pl.Float64,
    "significance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "label": pl.Utf8,
    "category": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Concatenate per-contrast DE TSVs and rename to the canonical schema.

    Stub — wire against the actual megatest output once downloaded locally.
    """
    raise NotImplementedError(
        "Wire against nf-core/differentialabundance megatest "
        "(tables/differential/*.tsv) — see module docstring."
    )
