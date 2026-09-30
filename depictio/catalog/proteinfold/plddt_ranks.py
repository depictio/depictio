"""Per-residue pLDDT of each engine's models: the top-ranked curve and their spread.

Read from the same ``<target>_plddt.tsv`` tables as ``models.py``. One curve per
structure (engine and target): ``plddt`` is the top-ranked model, the one written
to ``top_ranked_structures``, and ``plddt_min`` / ``plddt_max`` the lowest and
highest model at that residue, so a band shows where the engine's models
disagree and the curves of several engines show where the engines do, without
drawing every model of every engine (AlphaFold2 multimer writes 25 per target).
``residue_index`` counts residues from 1 over the chains in order (the tables
do not carry chain ids); curves longer than 200 residues are averaged over
equal windows, per model, before the spread is taken.

Sources:
    plddt  ``**/*_plddt.tsv``, one text line per row
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.proteinfold import RAW_LINE_READ_KWARGS, decimate, plddt_long

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="plddt",
        glob_pattern="**/*_plddt.tsv",
        format="csv",
        read_kwargs=RAW_LINE_READ_KWARGS,
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "engine": pl.Utf8,
    "target": pl.Utf8,
    "n_models": pl.Int64,
    "residue_index": pl.Int64,
    "plddt": pl.Float64,
    "plddt_min": pl.Float64,
    "plddt_max": pl.Float64,
}

MAX_POINTS = 200


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """pLDDT tables -> one row per (entity, residue): top model, lowest, highest."""
    long = plddt_long(sources["plddt"])
    if long.is_empty():
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    # Every model of an entity has the same residues, so windowing each model
    # alike keeps their residue_index values aligned for the spread below.
    windowed = decimate(long, ["entity", "model_rank"], "residue_index", "plddt", MAX_POINTS)
    out = windowed.group_by(["entity", "engine", "target", "residue_index"]).agg(
        pl.col("model_rank").n_unique().cast(pl.Int64).alias("n_models"),
        pl.col("plddt").filter(pl.col("model_rank") == 1).first().alias("plddt"),
        pl.col("plddt").min().alias("plddt_min"),
        pl.col("plddt").max().alias("plddt_max"),
    )
    return (
        out.with_columns(pl.col("plddt", "plddt_min", "plddt_max").round(2))
        .select(list(EXPECTED_SCHEMA))
        .cast(EXPECTED_SCHEMA)
        .sort(["target", "engine", "residue_index"])
    )
