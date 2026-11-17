"""Per gene and time point: nascent transcription and its change from the baseline.

The long form of ``gene_dynamics``: one row per expressed gene per time point,
the mean ``log2(cpm + 1)`` of the libraries of that time point and its log2 fold
change against the baseline, carrying the gene's response class so a table or
a filter on the class reaches every time point of the gene. The same gene
selection (the genes ``gene_dynamics`` holds) and the same averaging (both go
through ``depictio/recipes/lib/time_course.py``), so the two never disagree on a
gene.

Sources:
    counts    ``subread_gene_counts`` (catalog ``subread/gene_counts.py``)
    samples   ``samples`` (the sample hub)
    dynamics  ``gene_dynamics``, for the response class of each gene

Output schema:
    gene_id, time_point : Utf8
    time_h : Float64, time_order : Int64, time_axis : Float64, phase : Utf8
    log2_cpm, log2fc : Float64
    direction, response : Utf8
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib import time_course as tc

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="counts",
        dc_ref="subread_gene_counts",
        input_schema={
            "gene_id": pl.Utf8,
            "sample": pl.Utf8,
            "log2_cpm": pl.Float64,
        },
    ),
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={
            "sample": pl.Utf8,
            "time_point": pl.Utf8,
            "time_h": pl.Float64,
            "time_order": pl.Int64,
            "time_axis": pl.Float64,
            "phase": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="dynamics",
        dc_ref="gene_dynamics",
        input_schema={"gene_id": pl.Utf8, "direction": pl.Utf8, "response": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "time_point": pl.Utf8,
    "time_h": pl.Float64,
    "time_order": pl.Int64,
    "time_axis": pl.Float64,
    "phase": pl.Utf8,
    "log2_cpm": pl.Float64,
    "log2fc": pl.Float64,
    "direction": pl.Utf8,
    "response": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    # `gene_dynamics` holds exactly the expressed genes, so its ids are the selection.
    dynamics = sources["dynamics"].select("gene_id", "direction", "response")
    times = sources["samples"].select("sample", *tc.TIME_POINT_COLUMNS)
    points = tc.time_point_values(
        sources["counts"]
        .join(dynamics.select("gene_id"), on="gene_id")
        .select("gene_id", "sample", "log2_cpm"),
        times,
        key="gene_id",
        value_col="log2_cpm",
    )
    return (
        points.join(dynamics, on="gene_id", how="inner")
        .rename({"value": "log2_cpm"})
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["gene_id", "time_order"])
    )
