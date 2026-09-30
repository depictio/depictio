"""Per-residue confidence of every top-ranked structure, one row per residue.

proteinfold writes the top-ranked model of each target and engine to
``<engine>[/<mode>]/top_ranked_structures/<target>.pdb`` with the model's
pLDDT in the B-factor column. The residue table is read straight from those
files, so its ``chain`` and ``position`` are the structure's own numbering (the
one the 3D viewer picks residues by) and its ``entity`` is the id the
structures collection gives the same file. RoseTTAFold All-Atom stores pLDDT
as a 0-1 fraction; it is put on the 0-100 scale of the other engines.
``category`` is the AlphaFold confidence band, labelled Very high, Confident,
Low and Very low as the pLDDT legend of the protein tiles labels it.

Sources:
    structures  ``**/top_ranked_structures/*.pdb``, one text line per row
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.proteinfold import RAW_LINE_READ_KWARGS, top_model_residues

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
    "entity": pl.Utf8,
    "engine": pl.Utf8,
    "target": pl.Utf8,
    "chain": pl.Utf8,
    "position": pl.Int64,
    "residue": pl.Utf8,
    "value": pl.Float64,
    "category": pl.Utf8,
    "confidently_placed": pl.Float64,
}


#: AlphaFold's confidence band labels, spelled as the protein tiles' pLDDT
#: legend spells them, so the band card, the table and the legends agree.
BAND_LABELS = {
    "very high": "Very high",
    "confident": "Confident",
    "low": "Low",
    "very low": "Very low",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Top-ranked PDBs -> one row per structure and residue."""
    residues = top_model_residues(sources["structures"])
    return residues.with_columns(
        pl.col("category").replace(BAND_LABELS),
        # 100 for a residue at pLDDT 70 or more, else 0: its average over any
        # scope is the share of confidently placed residues, in percent.
        pl.when(pl.col("value") >= 70.0).then(100.0).otherwise(0.0).alias("confidently_placed"),
    ).select(list(EXPECTED_SCHEMA))
