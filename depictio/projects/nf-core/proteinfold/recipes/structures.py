"""Structure table for nf-core/proteinfold: one row per top-ranked structure.

The Structure tab plots one point per structure the 3D tile can open, and a
click on a point must name a structure that exists. The rows therefore come
from the top-ranked PDBs themselves (the files the structures collection
uploads), keyed by the same ``entity`` id, with the confidence read from the
B-factor column the way the residue table reads it: mean pLDDT, the share of
residues placed confidently (70 or more) and the share likely disordered
(under 50). The model tables add how many models the engine produced for the
target and, when the engine wrote them, the top model's pTM and ipTM.

Sources:
    structures  ``**/top_ranked_structures/*.pdb``, one text line per row
    plddt       ``**/*_plddt.tsv``, one text line per row (model count)
    scores      the ``proteinfold_scores_raw`` scan (optional: ESMFold and
                RoseTTAFold All-Atom write no TM scores)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.proteinfold import (
    RAW_LINE_READ_KWARGS,
    model_scores_long,
    plddt_long,
    top_model_residues,
)

SCORES_DC_TAG = "proteinfold_scores_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="structures",
        glob_pattern="**/top_ranked_structures/*.pdb",
        format="csv",
        read_kwargs=RAW_LINE_READ_KWARGS,
        source_path="source_path",
    ),
    RecipeSource(
        ref="plddt",
        glob_pattern="**/*_plddt.tsv",
        format="csv",
        read_kwargs=RAW_LINE_READ_KWARGS,
        source_path="source_path",
        optional=True,
    ),
    RecipeSource(ref="scores", dc_ref=SCORES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "structure": pl.Utf8,
    "engine": pl.Utf8,
    "target": pl.Utf8,
    "n_chains": pl.Int64,
    "n_residues": pl.Int64,
    "mean_plddt": pl.Float64,
    "confident_pct": pl.Float64,
    "very_low_pct": pl.Float64,
    "n_models": pl.Int64,
    "ptm": pl.Float64,
    "iptm": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Top-ranked PDBs, model tables and scores -> one row per structure."""
    residues = top_model_residues(sources["structures"])
    out = residues.group_by(["entity", "engine", "target"], maintain_order=True).agg(
        pl.col("chain").n_unique().cast(pl.Int64).alias("n_chains"),
        pl.len().cast(pl.Int64).alias("n_residues"),
        pl.col("value").mean().round(2).alias("mean_plddt"),
        ((pl.col("value") >= 70.0).mean() * 100.0).round(2).alias("confident_pct"),
        ((pl.col("value") < 50.0).mean() * 100.0).round(2).alias("very_low_pct"),
    )

    plddt = sources.get("plddt")
    if plddt is not None and not plddt.is_empty():
        models = (
            plddt_long(plddt)
            .group_by("entity")
            .agg(pl.col("model_rank").n_unique().cast(pl.Int64).alias("n_models"))
        )
    else:
        models = pl.DataFrame(schema={"entity": pl.Utf8, "n_models": pl.Int64})

    scores = model_scores_long(sources.get("scores")).filter(pl.col("model_rank") == 1)
    top = (
        scores.pivot(on="metric", index="entity", values="score", aggregate_function="first")
        if not scores.is_empty()
        else pl.DataFrame(schema={"entity": pl.Utf8})
    )
    for metric in ("ptm", "iptm"):
        if metric not in top.columns:
            top = top.with_columns(pl.lit(None, dtype=pl.Float64).alias(metric))

    return (
        out.join(models, on="entity", how="left")
        .join(top.select("entity", "ptm", "iptm"), on="entity", how="left")
        .with_columns((pl.col("engine") + pl.lit(" / ") + pl.col("target")).alias("structure"))
        .select(list(EXPECTED_SCHEMA))
        .cast(EXPECTED_SCHEMA)
        .sort(["target", "engine"])
    )
