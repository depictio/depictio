"""Each sample's route through the pipeline's stages, one row per step.

A sample goes through assembly, then optionally long-read and short-read
polishing, then any number of scaffolders, which are alternatives run on the
same polished assembly rather than steps run one after the other. Drawn as one
line per sample over the stage rank, two scaffolders of the same sample would
zig-zag at the last step, so this recipe spells out every route: the shared
assembly and polishing steps, followed by one scaffolder each (or by nothing
when the sample was not scaffolded). Each route is one series, named
`<sample> to <final stage>`.

Every step carries the metrics that change along the way (QV, N50, total length,
k-mer completeness, BUSCO complete) and their change from the sample's raw
assembly, so a profile of QV over the stage rank reads as "what each stage
added". All the other columns of the per-assembly table are passed through,
so the design filters of the dashboard apply to these rows as well.

Input: the ``assemblies`` data collection (`assemblies.py`), declared before
this one.

Output schema (plus the pass-through columns of `assemblies`):
    route : Utf8               `<sample> to <final stage>`, one series per route
    assembly_id : Utf8         the assessed assembly at this step
    sample : Utf8              samplesheet sample
    stage : Utf8               the stage of this step
    stage_rank : Int64         0 assembly, 1 long-read polish, 2 short-read polish, 3 scaffold
    final_stage : Utf8         the last stage of the route
    qv : Float64               Merqury QV at this step
    qv_gain : Float64          QV minus the QV of the raw assembly
    n50 : Int64                N50 at this step
    n50_fold : Float64         N50 over the N50 of the raw assembly
    total_length : Int64       assembled bases at this step
    kmer_completeness : Float64  Merqury k-mer completeness at this step
    busco_complete : Float64   BUSCO complete at this step
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

ASSEMBLIES_DC_TAG = "assemblies"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="assemblies", dc_ref=ASSEMBLIES_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "route": pl.Utf8,
    "assembly_id": pl.Utf8,
    "sample": pl.Utf8,
    "stage": pl.Utf8,
    "stage_rank": pl.Int64,
    "final_stage": pl.Utf8,
    "qv": pl.Float64,
    "qv_gain": pl.Float64,
    "n50": pl.Int64,
    "n50_fold": pl.Float64,
    "total_length": pl.Int64,
    "kmer_completeness": pl.Float64,
    "busco_complete": pl.Float64,
}

SCAFFOLD_RANK = 3


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Expand every sample into its assembly-to-final-stage routes."""
    table = sources["assemblies"]
    if table.is_empty():
        raise ValueError("genomeassembler stage_steps: the assemblies table is empty")
    required = {"assembly_id", "sample", "stage", "stage_rank", "qv", "n50"}
    if not required.issubset(table.columns):
        raise ValueError(
            f"genomeassembler stage_steps: need {sorted(required)}, got {table.columns}"
        )

    baseline = (
        table.filter(pl.col("stage_rank") == 0)
        .select(
            "sample",
            pl.col("qv").alias("_qv0"),
            pl.col("n50").cast(pl.Float64).alias("_n500"),
        )
        .unique(subset=["sample"], keep="first")
    )

    parts: list[pl.DataFrame] = []
    for (_sample,), rows in table.group_by(["sample"], maintain_order=True):
        rows = rows.sort("stage_rank")
        shared = rows.filter(pl.col("stage_rank") < SCAFFOLD_RANK)
        ends = rows.filter(pl.col("stage_rank") >= SCAFFOLD_RANK)
        routes = []
        if ends.is_empty():
            routes.append(shared)
        else:
            for index in range(ends.height):
                routes.append(pl.concat([shared, ends.slice(index, 1)], how="vertical"))
        for route in routes:
            if route.is_empty():
                continue
            final = route["stage"][-1]
            parts.append(
                route.with_columns(
                    (pl.col("sample") + pl.lit(" to ") + pl.lit(final)).alias("route"),
                    pl.lit(final).alias("final_stage"),
                )
            )
    if not parts:
        raise ValueError("genomeassembler stage_steps: no sample carried a stage")

    steps = pl.concat(parts, how="vertical").join(baseline, on="sample", how="left")
    steps = steps.with_columns(
        (pl.col("qv") - pl.col("_qv0")).alias("qv_gain"),
        (pl.col("n50").cast(pl.Float64) / pl.col("_n500")).alias("n50_fold"),
    ).drop(["_qv0", "_n500"])
    extra = [c for c in steps.columns if c not in EXPECTED_SCHEMA]
    return steps.select([*EXPECTED_SCHEMA, *extra]).sort(["route", "stage_rank"])
