"""Canonical-schema embedding DC for ampliseq (PCoA on Bray-Curtis).

Consumes the existing ``taxonomy_heatmap`` DC — a wide matrix with row
identifiers (Phylum, Kingdom) and per-sample relative-abundance columns —
drops the identifier columns, transposes so samples become rows, then
applies PCoA via depictio.recipes.lib.dimreduction.run_pcoa.

Canonical schema (see advanced_viz/schemas.py):
    sample_id : Utf8
    dim_1 : Float64
    dim_2 : Float64

Optional roles (when metadata source is available):
    <group_col> : Utf8 — the first metadata annotation column (the dashboard's
        ``GROUP_COL``, e.g. ``habitat`` / ``treatment1``), used as ``color_col``
        so the PCoA tile gets a legend coloured by that grouping. The column
        keeps its original name so the parameterised dashboard's
        ``color_col: '{GROUP_COL}'`` resolves against it.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.dimreduction import run_pcoa

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="taxonomy_heatmap", dc_ref="taxonomy_heatmap"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
}

# The grouping column name is run-dependent (the dashboard's GROUP_COL), so the
# optional colour column is validated dynamically rather than against a fixed name.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_METADATA_ID_COL = "ID"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Drop ID columns, transpose to samples×features, then PCoA on Bray-Curtis."""
    df = sources["taxonomy_heatmap"]

    drop_cols = [c for c in ("Phylum", "Kingdom", "_col_annotations_json") if c in df.columns]
    if "Phylum" not in df.columns and "Kingdom" not in df.columns:
        raise ValueError(
            "ampliseq embedding_pcoa: expected `Phylum` and/or `Kingdom` row-identifier columns"
        )
    feature_matrix = df.drop(drop_cols)

    # Transpose: input rows are taxa, columns are samples. We want one row
    # per sample so PCoA sees samples × taxa.
    sample_ids = feature_matrix.columns
    arr = feature_matrix.to_numpy().astype(float).T  # shape (n_samples, n_taxa)

    samples_wide = pl.DataFrame(
        {
            "sample_id": sample_ids,
            **{f"taxon_{i}": arr[:, i].tolist() for i in range(arr.shape[1])},
        }
    )

    coords = run_pcoa(samples_wide, n_components=2)

    metadata = sources.get("metadata")
    if metadata is not None:
        cols = metadata.columns
        sample_id_col = next((c for c in (_METADATA_ID_COL, "sample") if c in cols), None)
        if sample_id_col is None and cols:
            sample_id_col = cols[0]
        # GROUP_COL = first annotation column (first non-ID column), matching the
        # CLI's _auto_detect_metadata_columns convention. Keep its real name so the
        # dashboard's `color_col: '{GROUP_COL}'` resolves against it.
        group_col = next((c for c in cols if c != sample_id_col), None)
        if sample_id_col is not None and group_col is not None:
            meta_slim = (
                metadata.select(sample_id_col, group_col)
                .unique(subset=[sample_id_col])
                .rename({sample_id_col: "sample_id"})
                .with_columns(pl.col(group_col).cast(pl.Utf8))
            )
            coords = coords.join(meta_slim, on="sample_id", how="left")

    return coords
