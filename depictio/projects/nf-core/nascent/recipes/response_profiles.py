"""The typical trajectory of each response class: median change per time point, with its band.

Ten thousand curves, one per gene, read as a grey mass. What a reader wants is
the shape of each response: when the induced-early genes rise and whether they
come back down, whether the late-repressed ones drift or drop. So the genes of
each class (``gene_dynamics``) are summarised per time point as the median log2
fold change against the baseline, with the first and third quartile as a band.
``Stable`` is kept as the flat reference the other classes are read against.

Sources:
    trajectories  ``gene_trajectories``

Output schema:
    response, direction, time_point : Utf8
    time_h : Float64, time_order : Int64, time_axis : Float64, phase : Utf8
    median_log2fc, q1_log2fc, q3_log2fc : Float64
    n_genes : Int64        genes of the class behind the median
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib import time_course as tc

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="trajectories",
        dc_ref="gene_trajectories",
        input_schema={
            "gene_id": pl.Utf8,
            "time_point": pl.Utf8,
            "time_h": pl.Float64,
            "time_order": pl.Int64,
            "time_axis": pl.Float64,
            "phase": pl.Utf8,
            "log2fc": pl.Float64,
            "direction": pl.Utf8,
            "response": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "response": pl.Utf8,
    "direction": pl.Utf8,
    "time_point": pl.Utf8,
    "time_h": pl.Float64,
    "time_order": pl.Int64,
    "time_axis": pl.Float64,
    "phase": pl.Utf8,
    "median_log2fc": pl.Float64,
    "q1_log2fc": pl.Float64,
    "q3_log2fc": pl.Float64,
    "n_genes": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    trajectories = sources["trajectories"]
    directions = trajectories.select("response", "direction").unique(subset="response")
    return (
        tc.spread_by_class(trajectories, class_col="response")
        .rename({"n_features": "n_genes"})
        .join(directions, on="response", how="left")
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["response", "time_order"])
    )
