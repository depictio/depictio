"""Run-to-run Pearson correlation of the protein-group intensities.

A square matrix: one row and one column per run, the correlation of the two runs' log2
intensities over the protein groups both quantified. Runs of one condition should correlate
more than runs of different conditions; the matrix is drawn as a clustered heatmap whose
columns are the runs.

The group column named by the template's ``group_col`` parameter (the hub's ``condition``
by default) is joined from ``samples`` and annotates the rows.

Output schema (the group column right after ``run_id``; one Float64 column per run follows):
    run_id : Utf8
    <group column> : Utf8
    <run id> : Float64     correlation with that run
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

PROTEINS_DC_TAG = "quantms_proteins"
HUB_DC_TAG = "samples"
MIN_SHARED = 10

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="proteins",
        dc_ref=PROTEINS_DC_TAG,
        input_schema={"run_id": pl.Utf8, "protein_group": pl.Utf8, "log2_intensity": pl.Float64},
    ),
    RecipeSource(ref="hub", dc_ref=HUB_DC_TAG, optional=True, input_schema={"run_id": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {"run_id": pl.Utf8}
# One column per run, and the group column: named after the data, so they pass through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All runs"


def group_lookup(hub: pl.DataFrame | None, params: dict | None) -> tuple[str, pl.DataFrame]:
    """The group column's name and a ``run_id`` to group value table."""
    wanted = (params or {}).get("group_col") or "condition"
    if hub is not None and not hub.is_empty() and "run_id" in hub.columns:
        col = (
            wanted
            if wanted in hub.columns
            else ("condition" if "condition" in hub.columns else None)
        )
        if col is not None:
            table = hub.select(
                pl.col("run_id").cast(pl.Utf8), pl.col(col).cast(pl.Utf8).alias(col)
            ).unique(subset="run_id", keep="first")
            return col, table
    return NO_GROUP_COL, pl.DataFrame(schema={"run_id": pl.Utf8, NO_GROUP_COL: pl.Utf8})


def transform(sources: dict[str, pl.DataFrame | None], params: dict | None = None) -> pl.DataFrame:
    wide = sources["proteins"].pivot(on="run_id", index="protein_group", values="log2_intensity")
    runs = sorted(c for c in wide.columns if c != "protein_group")
    if len(runs) < 2:
        raise ValueError("quantms sample_correlation: needs at least two runs")
    values = wide.select(runs).to_numpy()
    matrix = np.full((len(runs), len(runs)), np.nan)
    for i in range(len(runs)):
        for j in range(len(runs)):
            both = ~np.isnan(values[:, i]) & ~np.isnan(values[:, j])
            if both.sum() >= MIN_SHARED:
                matrix[i, j] = np.corrcoef(values[both, i], values[both, j])[0, 1]
    out = pl.DataFrame(
        {"run_id": runs, **{run: np.round(matrix[:, k], 4).tolist() for k, run in enumerate(runs)}},
        schema={"run_id": pl.Utf8, **{run: pl.Float64 for run in runs}},
    )
    group_name, lookup = group_lookup(sources.get("hub"), params)
    out = out.join(lookup, on="run_id", how="left").with_columns(
        pl.col(group_name).fill_null("Unassigned" if group_name != NO_GROUP_COL else NO_GROUP_VALUE)
    )
    return out.select("run_id", group_name, *runs).sort("run_id")
