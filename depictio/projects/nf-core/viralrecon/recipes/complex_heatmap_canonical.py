"""Canonical-schema ComplexHeatmap DC for viralrecon amplicon coverage.

Thin wrapper around the existing ``mosdepth_amplicon_heatmap`` wide DC
(samples × amplicon log10-coverage matrix). The matrix is already canonical-
shaped for the ComplexHeatmap renderer; we only stabilise the canonical name
so the dashboard tile binds to a predictable DC tag.

Index column: ``sample`` (set as ``index_column`` in the viz config).
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="heatmap", dc_ref="mosdepth_amplicon_heatmap"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pass-through wrapper; ensure ``sample`` is Utf8 for use as index."""
    df = sources["heatmap"]
    if "sample" in df.columns:
        df = df.with_columns(pl.col("sample").cast(pl.Utf8))
    return df
