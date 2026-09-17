"""Wide companion to `cellranger_marker_expression`, for the `complex_heatmap`
render: one row per marker gene, one column per cluster, `mean_expression`
values.

A template reusing this recipe declares one source, the already-transformed
marker_expression DC::

    transform: {recipe: "cellranger/marker_matrix.py"}
    # SOURCES = [RecipeSource(ref="markers", dc_ref="cellranger_marker_expression")]

Output schema: `gene` (Utf8, row id) plus one Float64 column per cluster
label seen in the source table (column names are data-dependent, hence no
static EXPECTED_SCHEMA beyond `gene`; `catalog validate` checks the frame
shape, not a fixed column list, for pivoted outputs).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

MARKER_EXPRESSION_DC_TAG = "cellranger_marker_expression"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="markers", dc_ref=MARKER_EXPRESSION_DC_TAG),
]

#: only `gene` is guaranteed; the per-cluster value columns are data-dependent.
EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    markers = sources["markers"]
    required = {"cluster_label", "gene", "mean_expression"}
    if missing := required - set(markers.columns):
        raise ValueError(f"cellranger_marker_matrix: input lacks columns {sorted(missing)}")

    wide = markers.pivot(on="cluster_label", index="gene", values="mean_expression")
    return wide.sort("gene")
