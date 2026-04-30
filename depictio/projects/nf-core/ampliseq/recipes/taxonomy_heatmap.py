"""Pivot relative abundance table to wide-format heatmap matrix.

Produces a Phylum × sample matrix (relative abundances) with a Kingdom column,
suitable for use with the ComplexHeatmap visualisation.

When a metadata DC is present (--var METADATA_FILE=... provided), all additional
metadata columns (i.e. every column except the sample ID) are embedded as a
``_col_annotations_json`` constant column so the heatmap renderer can pick them
up as column annotations without hardcoding anything in the dashboard YAML.

See https://nf-co.re/ampliseq/docs/usage/#metadata — only ``ID`` is required;
all other columns are optional and are used as annotations dynamically.
"""

import json

import plotly.colors
import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="rel_abundance",
        dc_ref="taxonomy_rel_abundance",
    ),
    RecipeSource(
        ref="metadata",
        dc_ref="metadata",
        optional=True,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "Phylum": pl.Utf8,
    "Kingdom": pl.Utf8,
}
# Sample columns are dynamic — validated via OPTIONAL_SCHEMA = {}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# Column that holds the sample identifier in the metadata file
_METADATA_ID_COL = "ID"
_MAX_ANNOTATIONS = 5
# Columns to skip when selecting annotations (IDs, technical fields, coordinates)
_SKIP_ANNOTATION_COLS = {
    "name",
    "sampling_date",
    "latitude",
    "longitude",
    "depictio_run_id",
    "aggregation_time",
}

# Use Plotly's default qualitative color sequence for deterministic auto-coloring.
# Sorted unique values always get the same color assignment, matching Plotly charts.
_PLOTLY_QUALITATIVE = plotly.colors.qualitative.Plotly


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot long-format relative abundance to wide Phylum × sample matrix."""
    df = sources["rel_abundance"]

    # Aggregate to Phylum level (sum per sample + Phylum)
    df_agg = df.group_by(["sample", "Phylum", "Kingdom"]).agg(
        pl.col("rel_abundance").sum().alias("rel_abundance")
    )

    # Pivot: rows = Phylum, columns = samples
    pivoted = df_agg.pivot(
        values="rel_abundance",
        index=["Phylum", "Kingdom"],
        on="sample",
        aggregate_function="sum",
    ).fill_null(0.0)

    # Sort samples alphabetically so column order is deterministic
    sample_cols = sorted([c for c in pivoted.columns if c not in ["Phylum", "Kingdom"]])
    result = pivoted.select(["Phylum", "Kingdom"] + sample_cols).sort("Phylum")

    # Build col_annotations JSON from metadata when available
    metadata = sources.get("metadata")
    if metadata is not None:
        # Normalise sample column name (nf-core ampliseq uses "ID")
        if _METADATA_ID_COL in metadata.columns:
            metadata = metadata.rename({_METADATA_ID_COL: "sample"})

        # Select meaningful annotation columns, skipping IDs and coordinates
        annotation_cols = [
            c for c in metadata.columns if c != "sample" and c not in _SKIP_ANNOTATION_COLS
        ][:_MAX_ANNOTATIONS]

        if annotation_cols:
            # Build per-sample lookup restricted to samples present in the matrix
            meta_lookup = (
                metadata.select(["sample"] + annotation_cols)
                .unique(subset=["sample"])
                .filter(pl.col("sample").is_in(sample_cols))
            )
            # Reorder to match alphabetical sample column order
            sample_order = {s: i for i, s in enumerate(sample_cols)}
            meta_lookup = (
                meta_lookup.with_columns(
                    pl.col("sample").replace(sample_order).cast(pl.Int32).alias("_order")
                )
                .sort("_order")
                .drop("_order")
            )

            col_annotations: dict = {}
            for col in annotation_cols:
                raw_values = meta_lookup[col].to_list()
                # Convert non-serializable types and None to string
                values = [
                    str(v)
                    if v is not None and not isinstance(v, (str, int, float, bool))
                    else (v if v is not None else "")
                    for v in raw_values
                ]
                # Skip annotations that have any empty/null values
                # (ComplexHeatmap can't handle empty strings in color mapping)
                if any(v == "" or v is None for v in values):
                    continue

                # Auto-generate deterministic colors from Plotly's default palette.
                # Sorted unique values always map to the same color, matching
                # what Plotly charts produce when using the same color column.
                unique_vals = sorted(set(values))
                colors = {
                    v: _PLOTLY_QUALITATIVE[i % len(_PLOTLY_QUALITATIVE)]
                    for i, v in enumerate(unique_vals)
                }

                col_annotations[col] = {
                    "values": values,
                    "type": "categorical",
                    "colors": colors,
                }

            result = result.with_columns(
                pl.lit(json.dumps(col_annotations)).alias("_col_annotations_json")
            )

    return result
