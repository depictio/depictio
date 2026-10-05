"""The multiple sequence alignment each MSA-based engine folded from.

AlphaFold2, ColabFold and RoseTTAFold All-Atom write the alignment of every
target to ``<engine>[/<mode>]/<target>/<target>_<engine>_msa.tsv``: one
aligned sequence per line, every residue an integer code, the query first.
The code order is the HHblits alphabet for monomer runs but AlphaFold's
residue-type order for AlphaFold2 multimer, so each file is decoded with the
order under which its query reads as the sequence of the structure folded
from it. The rows carry no names, so the query is ``query`` and the hits
``hit_<rank>``. Decoded into the
MSA table the alignment tiles read, capped at 500 rows per alignment in file
order, with identity and coverage measured against the query.

``msa_id`` and ``entity`` are the id of the structure folded from the
alignment, so a column brush on the alignment lands on that structure's
residue table. The query of a complex is its chains concatenated, so its row
carries the structure's chain layout in ``chains`` (``A:1-120,B:1-98``, each
chain in the residue table's own numbering) and a brush lands on one chain.

Sources:
    msa         ``**/*_msa.tsv``, one text line per row
    structures  ``**/top_ranked_structures/*.pdb`` (the query sequence)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.msa import (
    CHAINS_COLUMN,
    MSA_SCHEMA,
    best_alphabet,
    chain_layout_from_residues,
    decode_hhblits_rows,
    msa_frame,
)
from depictio.recipes.lib.protein_structure import residues_from_pdb
from depictio.recipes.lib.proteinfold import (
    RAW_LINE_READ_KWARGS,
    locate_structure,
    locate_target_file,
    raw_blocks,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="msa",
        glob_pattern="**/*_msa.tsv",
        format="csv",
        read_kwargs=RAW_LINE_READ_KWARGS,
        source_path="source_path",
    ),
    RecipeSource(
        ref="structures",
        glob_pattern="**/top_ranked_structures/*.pdb",
        format="csv",
        read_kwargs=RAW_LINE_READ_KWARGS,
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    **MSA_SCHEMA,
    CHAINS_COLUMN: pl.Utf8,
    "entity": pl.Utf8,
    "engine": pl.Utf8,
    "target": pl.Utf8,
    "depth": pl.Int64,
}

CAP = 500


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Integer-coded alignments -> one row per (alignment, aligned sequence)."""
    residues_of = {}
    for path, lines in raw_blocks(sources["structures"]):
        entity = locate_structure(path).entity
        residues_of[entity] = residues_from_pdb("\n".join(lines) + "\n", entity)
    frames = []
    for path, lines in raw_blocks(sources["msa"]):
        loc = locate_target_file(path)
        residues = residues_of.get(loc.entity)
        query = "".join(residues["residue"].to_list()) if residues is not None else ""
        alphabet = best_alphabet(lines, query)
        sequences = decode_hhblits_rows(lines, alphabet)
        if not sequences:
            continue
        records = [("query" if i == 0 else f"hit_{i}", seq) for i, seq in enumerate(sequences)]
        layout = (
            chain_layout_from_residues(residues, len(sequences[0].replace("-", "")))
            if residues is not None
            else None
        )
        frames.append(
            msa_frame(records, loc.entity, cap=CAP).with_columns(
                pl.when(pl.col("rank") == 0)
                .then(pl.lit(layout, dtype=pl.Utf8))
                .otherwise(pl.lit(None, dtype=pl.Utf8))
                .alias(CHAINS_COLUMN),
                pl.lit(loc.entity).alias("entity"),
                pl.lit(loc.engine).alias("engine"),
                pl.lit(loc.target).alias("target"),
                pl.lit(len(sequences), dtype=pl.Int64).alias("depth"),
            )
        )
    if not frames:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    return pl.concat(frames, how="vertical").select(list(EXPECTED_SCHEMA))
