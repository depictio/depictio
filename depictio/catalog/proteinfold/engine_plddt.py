"""Per-residue confidence of each engine's top-ranked model, one curve per engine.

The same numbers as ``residues.py``, shaped for comparing engines on one target:
``series`` is the target and the engine (with the chain on a multi-chain
structure, so each chain draws its own curve in its own numbering): one curve is
always one structure, so the tile reads right before a target is picked instead
of zigzagging between targets at the same residue number. Curves longer than 200
residues are averaged over equal windows so a profile stays readable.

It is a collection of its own, with no ``engine`` column, so that picking one
structure elsewhere on a tab does not hide the other engines' curves: a
dashboard filter narrows every collection that carries its column, so an engine
picker on the residue table would otherwise narrow these curves to its engine.
The engine is in ``series``; the curves follow the target only.

Sources:
    structures  ``**/top_ranked_structures/*.pdb``, one text line per row
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.proteinfold import (
    RAW_LINE_READ_KWARGS,
    decimate,
    top_model_residues,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="structures",
        glob_pattern="**/top_ranked_structures/*.pdb",
        format="csv",
        read_kwargs=RAW_LINE_READ_KWARGS,
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "target": pl.Utf8,
    "series": pl.Utf8,
    "chain": pl.Utf8,
    "position": pl.Int64,
    "plddt": pl.Float64,
}

MAX_POINTS = 200


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Top-ranked PDBs -> one row per (target, engine curve, position)."""
    residues = top_model_residues(sources["structures"]).rename({"value": "plddt"})
    table = residues.select(list(EXPECTED_SCHEMA)).with_columns(
        (pl.col("target") + pl.lit(" ") + pl.col("series")).alias("series")
    )
    return (
        decimate(table, ["target", "series"], "position", "plddt", MAX_POINTS)
        .with_columns(pl.col("plddt").round(2))
        .sort(["target", "series", "position"])
    )
