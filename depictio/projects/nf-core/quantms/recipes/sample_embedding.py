"""Principal components of the runs, from the protein-group intensities.

Takes the protein groups quantified in every run, centres each group on its mean across
the runs and takes the singular value decomposition: the runs' coordinates on the first
two components, with the share of the variance each explains. Runs of one condition
should sit together and the conditions apart; a run away from its replicates is the one
to check in the acquisition and identification tabs.

The sign of a component is arbitrary, so each is flipped to make its largest coordinate
positive and a rebuild draws the same plot.

The group column named by the template's ``group_col`` parameter (the hub's ``condition``
by default) is joined from ``samples``.

Output schema (the group column right after ``run_id``):
    run_id : Utf8
    dim_1 : Float64        first component, run coordinate
    dim_2 : Float64        second component; 0 when the experiment has two runs
    explained_1 : Float64  percent of the variance on the first component
    explained_2 : Float64  percent of the variance on the second component
    proteins_used : Int64  protein groups quantified in every run
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

PROTEINS_DC_TAG = "quantms_proteins"
HUB_DC_TAG = "samples"
MIN_PROTEINS = 10

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
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "explained_1": pl.Float64,
    "explained_2": pl.Float64,
    "proteins_used": pl.Int64,
}
# The group column is named by the template's group_col and passes through.
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
    proteins = sources["proteins"]
    wide = proteins.pivot(on="run_id", index="protein_group", values="log2_intensity")
    runs = sorted(c for c in wide.columns if c != "protein_group")
    if len(runs) < 2:
        raise ValueError("quantms sample_embedding: needs at least two runs")
    complete = wide.drop_nulls(subset=runs)
    if complete.height < MIN_PROTEINS:
        raise ValueError(
            f"quantms sample_embedding: only {complete.height} protein groups are quantified "
            f"in every run, need {MIN_PROTEINS}"
        )
    x = complete.select(runs).to_numpy().T  # runs x proteins
    x = x - x.mean(axis=0, keepdims=True)
    u, s, _vt = np.linalg.svd(x, full_matrices=False)
    coords = u * s
    total = float((s**2).sum())
    explained = (s**2 / total * 100.0) if total > 0 else np.zeros_like(s)
    for k in range(coords.shape[1]):
        if coords[:, k].size and coords[np.argmax(np.abs(coords[:, k])), k] < 0:
            coords[:, k] = -coords[:, k]
    dim_1 = coords[:, 0]
    dim_2 = coords[:, 1] if coords.shape[1] > 1 else np.zeros(len(runs))
    out = pl.DataFrame(
        {
            "run_id": runs,
            "dim_1": np.round(dim_1, 4).tolist(),
            "dim_2": np.round(dim_2, 4).tolist(),
            "explained_1": [round(float(explained[0]), 2)] * len(runs),
            "explained_2": [round(float(explained[1]) if len(explained) > 1 else 0.0, 2)]
            * len(runs),
            "proteins_used": [complete.height] * len(runs),
        },
        schema={
            "run_id": pl.Utf8,
            "dim_1": pl.Float64,
            "dim_2": pl.Float64,
            "explained_1": pl.Float64,
            "explained_2": pl.Float64,
            "proteins_used": pl.Int64,
        },
    )
    group_name, lookup = group_lookup(sources.get("hub"), params)
    out = out.join(lookup, on="run_id", how="left").with_columns(
        pl.col(group_name).fill_null("Unassigned" if group_name != NO_GROUP_COL else NO_GROUP_VALUE)
    )
    return out.select("run_id", group_name, *list(OUTPUT_SCHEMA)[1:]).sort("run_id")
