"""Canonical-schema embedding DC for ampliseq (PCoA on Bray-Curtis).

Source: ``taxonomy_heatmap.tsv`` — a wide matrix with row identifiers
(Phylum, Kingdom) and per-sample relative-abundance columns. We drop the
two identifier columns, transpose so samples become rows, then apply PCoA
via depictio.recipes.lib.dimreduction.run_pcoa.

Canonical schema (see advanced_viz/schemas.py):
    sample_id : Utf8
    dim_1 : Float64
    dim_2 : Float64
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.dimreduction import run_pcoa

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="taxonomy_heatmap",
        path="taxonomy_heatmap.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Drop ID columns, transpose to samples×features, then PCoA on Bray-Curtis."""
    df = sources["taxonomy_heatmap"]

    drop_cols = [c for c in ("Phylum", "Kingdom") if c in df.columns]
    if not drop_cols:
        raise ValueError(
            "ampliseq embedding_pcoa: expected `Phylum` and/or `Kingdom` row-identifier columns"
        )
    feature_matrix = df.drop(drop_cols)

    # Transpose: input rows are taxa, columns are samples. We want one row
    # per sample so PCoA sees samples × taxa.
    sample_ids = feature_matrix.columns
    arr = feature_matrix.to_numpy().astype(float).T  # shape (n_samples, n_taxa)

    samples_wide = pl.DataFrame(
        {"sample_id": sample_ids, **{f"taxon_{i}": arr[:, i].tolist() for i in range(arr.shape[1])}}
    )

    return run_pcoa(samples_wide, n_components=2)
