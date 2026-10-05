"""Confidence of every predicted model, one row per structure entity and model rank.

Each engine ranks the models it produced for a target and writes their
per-residue pLDDT to ``<engine>[/<mode>]/<target>/<target>_plddt.tsv`` (one
``rank_<k>`` column per model). AlphaFold2 and ColabFold add the predicted TM
score per model (``<target>_ptm.tsv``) and, for a multi-chain target, the
interface TM score and ipSAE (``_iptm.tsv``, ``_ipsae.tsv``; the files are
empty for a single chain). Engines number their models from 0 or from 1, so
``model_rank`` renumbers them from 1 (the top-ranked model, the one written to
``top_ranked_structures``).

Summaries per model: mean pLDDT, the share of residues at pLDDT 70 or more
(confidently placed) and under 50 (likely disordered or wrong), and the scores
when the engine wrote them (null otherwise).

Sources:
    plddt   ``**/*_plddt.tsv``, one text line per row
    scores  the ``proteinfold_scores_raw`` scan (optional: ESMFold and
            RoseTTAFold All-Atom write no TM scores)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.proteinfold import (
    RAW_LINE_READ_KWARGS,
    model_scores_long,
    plddt_long,
)

SCORES_DC_TAG = "proteinfold_scores_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="plddt",
        glob_pattern="**/*_plddt.tsv",
        format="csv",
        read_kwargs=RAW_LINE_READ_KWARGS,
        source_path="source_path",
    ),
    RecipeSource(ref="scores", dc_ref=SCORES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "model_id": pl.Utf8,
    "structure": pl.Utf8,
    "entity": pl.Utf8,
    "engine": pl.Utf8,
    "target": pl.Utf8,
    "model_rank": pl.Int64,
    "is_top": pl.Boolean,
    "n_residues": pl.Int64,
    "mean_plddt": pl.Float64,
    "confident_pct": pl.Float64,
    "very_low_pct": pl.Float64,
    "ptm": pl.Float64,
    "iptm": pl.Float64,
    "ipsae": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """pLDDT tables and score files -> one row per (entity, model rank)."""
    residues = plddt_long(sources["plddt"])
    summary = residues.group_by(
        ["entity", "engine", "target", "model_rank"], maintain_order=True
    ).agg(
        pl.len().cast(pl.Int64).alias("n_residues"),
        pl.col("plddt").mean().alias("mean_plddt"),
        ((pl.col("plddt") >= 70.0).mean() * 100.0).alias("confident_pct"),
        ((pl.col("plddt") < 50.0).mean() * 100.0).alias("very_low_pct"),
    )
    scores = model_scores_long(sources.get("scores"))
    wide = (
        scores.pivot(
            on="metric", index=["entity", "model_rank"], values="score", aggregate_function="first"
        )
        if not scores.is_empty()
        else pl.DataFrame(schema={"entity": pl.Utf8, "model_rank": pl.Int64})
    )
    for metric in ("ptm", "iptm", "ipsae"):
        if metric not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(metric))
    out = summary.join(wide, on=["entity", "model_rank"], how="left").with_columns(
        (pl.col("entity") + pl.lit("#") + pl.col("model_rank").cast(pl.Utf8)).alias("model_id"),
        (pl.col("model_rank") == 1).alias("is_top"),
        (pl.col("engine") + pl.lit(" / ") + pl.col("target")).alias("structure"),
    )
    return (
        out.select(list(EXPECTED_SCHEMA))
        .cast(EXPECTED_SCHEMA)
        .sort(["target", "engine", "model_rank"])
    )
