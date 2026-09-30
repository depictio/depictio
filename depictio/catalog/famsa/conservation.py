"""Per-residue conservation of every family, in its representative's numbering.

Reads the same ``famsa_alignment_raw`` text scan as ``famsa/alignment.py``
(one file line per row, the file in ``source_path``). For each family
alignment the first row is the representative; every one of its residues gets
one row, numbered 1..L along the ungapped representative, which is the
numbering a structure predicted from the representative sequence uses too.

``value`` is ``(1 - H / log2(20)) * occupancy``: the Shannon entropy of the
column's residues normalised to the 20 amino acids, discounted by the share of
members with a gap there, so 1 marks an invariant gap-free column and 0 a
column as diverse as random sequence (``depictio.recipes.lib.protein_families``).
``category`` bins it: conserved (0.7 and above), intermediate (0.4 to 0.7),
variable (below 0.4). The whole representative sequence rides on every row in
``sequence``, which is what a 3D tile in resolve mode folds.

Output schema (the contract's residue table plus the family keys):
    entity : Utf8              family id
    sample : Utf8              sample the family was built from
    position : Int64           residue number along the representative, 1-based
    residue : Utf8             representative residue (one letter)
    value : Float64            conservation score, 0-1
    category : Utf8            conserved / intermediate / variable
    consensus : Utf8           most frequent residue of the column
    consensus_share : Float64  share of the column's residues equal to the consensus
    occupancy : Float64        share of members with a residue in the column
    n_members : Int64          aligned members the column is computed over
    sequence : Utf8            ungapped representative sequence
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.msa import parse_fasta_alignment
from depictio.recipes.lib.protein_families import (
    column_conservation,
    conservation_class,
    family_id,
    sample_from_path,
    texts_by_file,
    ungapped,
)

RAW_DC_TAG = "famsa_alignment_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="alignments", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "position": pl.Int64,
    "residue": pl.Utf8,
    "value": pl.Float64,
    "category": pl.Utf8,
    "consensus": pl.Utf8,
    "consensus_share": pl.Float64,
    "occupancy": pl.Float64,
    "n_members": pl.Int64,
    "sequence": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per representative residue of every family alignment."""
    rows: list[dict] = []
    seen: set[str] = set()
    for path, text in texts_by_file(sources["alignments"]).items():
        records = parse_fasta_alignment(text)
        family = family_id(path)
        if not records or family in seen:
            continue
        seen.add(family)
        sample = sample_from_path(path)
        sequence = ungapped(records[0][1]).upper()
        for residue in column_conservation(records):
            rows.append(
                {
                    "entity": family,
                    "sample": sample,
                    **residue,
                    "category": conservation_class(residue["value"]),
                    "n_members": len(records),
                    "sequence": sequence,
                }
            )
    if not rows:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    return (
        pl.DataFrame(rows)
        .with_columns(pl.col(["value", "consensus_share", "occupancy"]).round(3))
        .select(list(EXPECTED_SCHEMA))
        .cast(EXPECTED_SCHEMA)  # type: ignore[arg-type]
    )
