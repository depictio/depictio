"""Canonical knee_qc DC for nf-core/scrnaseq.

Megatest source: STARsolo / Salmon Alevin ``barcodes.tsv`` + the raw counts matrix.
Compute per-barcode total UMI, n_genes_detected, %mito (genes matching ^MT-).

This recipe is for the PROPOSED `knee_qc` viz_kind. See
depictio/models/components/advanced_viz/PROPOSED_COMPONENTS.md.

Output (canonical knee_qc schema):

    sample_id    : Utf8
    barcode      : Utf8
    total_counts : Int64
    n_genes      : Int64
    pct_mito     : Float64   (optional)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "barcode": pl.Utf8,
    "total_counts": pl.Int64,
    "n_genes": pl.Int64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "pct_mito": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/scrnaseq megatest raw count matrices — see docstring."
    )
