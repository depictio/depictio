"""Protein-group intensities in two runs of the same condition, for every pair of runs.

One row per protein group quantified in both runs of a pair, with its log2 intensity in
each. The pairs are the runs of one condition taken two by two, in the hub's run order
within the condition (the ``replicate`` rank). A tight cloud along the diagonal is a
reproducible pair; a condition with a single run has no pair.

The group column named by the template's ``group_col`` parameter (the hub's ``condition``
by default) is joined from ``samples``.

Output schema (the group column right after ``genes``):
    protein_group : Utf8
    protein_name : Utf8
    genes : Utf8
    pair : Utf8            "Run 1 vs run 2" within the condition
    run_x : Utf8           run on the x axis
    run_y : Utf8           run on the y axis
    log2_x : Float64
    log2_y : Float64
"""

from __future__ import annotations

from itertools import combinations

import polars as pl

from depictio.models.models.transforms import RecipeSource

PROTEINS_DC_TAG = "quantms_proteins"
HUB_DC_TAG = "samples"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="proteins",
        dc_ref=PROTEINS_DC_TAG,
        input_schema={
            "run_id": pl.Utf8,
            "protein_group": pl.Utf8,
            "protein_name": pl.Utf8,
            "genes": pl.Utf8,
            "log2_intensity": pl.Float64,
        },
    ),
    RecipeSource(ref="hub", dc_ref=HUB_DC_TAG, optional=True, input_schema={"run_id": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "protein_group": pl.Utf8,
    "protein_name": pl.Utf8,
    "genes": pl.Utf8,
    "pair": pl.Utf8,
    "run_x": pl.Utf8,
    "run_y": pl.Utf8,
    "log2_x": pl.Float64,
    "log2_y": pl.Float64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All runs"


def transform(sources: dict[str, pl.DataFrame | None], params: dict | None = None) -> pl.DataFrame:
    proteins = sources["proteins"]
    hub = sources.get("hub")
    wanted = (params or {}).get("group_col") or "condition"
    group = next((c for c in (wanted, "condition", NO_GROUP_COL) if c in proteins.columns), None)
    if group is None:
        proteins = proteins.with_columns(pl.lit(NO_GROUP_VALUE).alias(NO_GROUP_COL))
        group = NO_GROUP_COL

    # Position of each run inside its group: the hub's `replicate` when it has one.
    order: dict[str, int] = {}
    if hub is not None and not hub.is_empty() and {"run_id", "replicate"} <= set(hub.columns):
        order = {
            r["run_id"]: r["replicate"]
            for r in hub.select("run_id", "replicate").iter_rows(named=True)
        }

    runs_of = proteins.select(group, "run_id").unique().sort([group, "run_id"])
    frames: list[pl.DataFrame] = []
    for (value,), runs in runs_of.group_by([group], maintain_order=True):
        members = sorted(runs["run_id"].to_list(), key=lambda r: (order.get(r, 0), r))
        wide = proteins.filter(pl.col(group) == value).pivot(
            on="run_id", index=["protein_group", "protein_name", "genes"], values="log2_intensity"
        )
        for rank_x, rank_y in combinations(range(len(members)), 2):
            run_x, run_y = members[rank_x], members[rank_y]
            pair = wide.select(
                "protein_group",
                "protein_name",
                "genes",
                pl.lit(value).alias(group),
                pl.lit(f"Run {rank_x + 1} vs run {rank_y + 1}").alias("pair"),
                pl.lit(run_x).alias("run_x"),
                pl.lit(run_y).alias("run_y"),
                pl.col(run_x).alias("log2_x"),
                pl.col(run_y).alias("log2_y"),
            ).drop_nulls(subset=["log2_x", "log2_y"])
            frames.append(pair)
    if not frames:
        raise ValueError("quantms replicate_pairs: no condition has two runs")
    out = pl.concat(frames)
    return out.select(
        "protein_group", "protein_name", "genes", group, *list(OUTPUT_SCHEMA)[3:]
    ).sort([group, "pair", "protein_group"])
