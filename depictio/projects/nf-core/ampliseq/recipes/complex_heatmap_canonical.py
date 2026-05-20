"""Canonical-schema ComplexHeatmap DC for ampliseq.

Thin wrapper around the existing ``taxonomy_heatmap`` wide DC (Phylum × sample
matrix with Kingdom + ``_col_annotations_json`` annotations). The output keeps
the same column layout — the matrix structure is already canonical for the
ComplexHeatmap renderer; we only stabilise the canonical name so the dashboard
tile binds to a predictable DC tag.

Schema for ``complex_heatmap`` is permissive on the index column (any String
column the user binds via ``index_column``). Here we expose ``Phylum`` as the
primary index, ``Kingdom`` as a row annotation, and the per-sample numeric
columns as the matrix.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="heatmap", dc_ref="taxonomy_heatmap"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "Phylum": pl.Utf8,
    "Kingdom": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pass-through wrapper; ensures index + annotation columns are Utf8."""
    df = sources["heatmap"]
    if "_col_annotations_json" in df.columns:
        df = df.drop("_col_annotations_json")
    casts = []
    if "Phylum" in df.columns:
        casts.append(pl.col("Phylum").cast(pl.Utf8))
    if "Kingdom" in df.columns:
        casts.append(pl.col("Kingdom").cast(pl.Utf8))
    if casts:
        df = df.with_columns(casts)
    return df
