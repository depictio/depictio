"""One row per protein group and condition: abundance and its spread over the condition's runs.

Groups the long protein table by the template's group column (the hub's ``condition``
by default) and reduces each protein group's runs inside it to a mean log2 intensity and
a coefficient of variation. The coefficient is the reproducibility measure of the
Reproducibility tab and the per-condition mean feeds the differential-abundance tab
(``quantms_comparisons`` reads it for the MA view and the record card).

Output schema (the group column is named by the template's ``group_col``):
    protein_group : Utf8
    protein_name : Utf8
    genes : Utf8
    <group column> : Utf8
    runs : Int64                  runs of the condition that quantified the group
    mean_log2_intensity : Float64
    sd_log2_intensity : Float64   null for a single run
    cv_pct : Float64              coefficient of variation of the intensity, percent; null for one run
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

PROTEINS_DC_TAG = "quantms_proteins"

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
            "intensity": pl.Float64,
            "log2_intensity": pl.Float64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "protein_group": pl.Utf8,
    "protein_name": pl.Utf8,
    "genes": pl.Utf8,
    "runs": pl.Int64,
    "mean_log2_intensity": pl.Float64,
    "sd_log2_intensity": pl.Float64,
    "cv_pct": pl.Float64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

NO_GROUP_COL = "__no_group__"


def transform(sources: dict[str, pl.DataFrame | None], params: dict | None = None) -> pl.DataFrame:
    proteins = sources["proteins"]
    wanted = (params or {}).get("group_col") or "condition"
    group = next((c for c in (wanted, "condition", NO_GROUP_COL) if c in proteins.columns), None)
    if group is None:
        proteins = proteins.with_columns(pl.lit("All runs").alias(NO_GROUP_COL))
        group = NO_GROUP_COL
    out = proteins.group_by(["protein_group", group]).agg(
        pl.col("protein_name").first(),
        pl.col("genes").first(),
        pl.col("run_id").n_unique().cast(pl.Int64).alias("runs"),
        pl.col("log2_intensity").mean().round(4).alias("mean_log2_intensity"),
        pl.col("log2_intensity").std().round(4).alias("sd_log2_intensity"),
        pl.when(pl.col("intensity").len() > 1)
        .then(pl.col("intensity").std() / pl.col("intensity").mean() * 100.0)
        .otherwise(None)
        .round(2)
        .alias("cv_pct"),
    )
    ordered = ["protein_group", "protein_name", "genes", group, *list(OUTPUT_SCHEMA)[3:]]
    return out.select(ordered).sort(["protein_group", group])
