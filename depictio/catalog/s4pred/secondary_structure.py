"""One row per residue of an S4PRED ss2 file (PSIPRED VFORMAT).

Consumes the raw ``s4pred_ss2_raw`` scan (one line per row in ``raw_line``,
the ``#`` comment dropped by the scan, the blank line read as null, plus
``source_path``). Each data line is ``position residue state P(C) P(H) P(E)``;
the file is parsed by ``depictio.recipes.lib.secondary_structure.parse_ss2``, so
the columns are the ones the ``secondary_structure`` kind reads.

The pipeline names every ss2 file after the sequence id, so ``entity`` is the
file name without ``.ss2``; the sample is the directory above ``ss2/``
(nf-core writes ``s4pred/<sample>/ss2/<sequence id>.ss2``), else the entity.
Ids that FASTA headers make unsafe (``GI|225038609|EFDID|719595|FULL``) are
spelled as every other table of the protein spells them
(``depictio.recipes.lib.protein_annotation.protein_entity``, the rule of an
``indexed_file`` sample id), so the entity joins the sequence, domain and
structure tables.

Residue table columns: ``category`` is the predicted state spelled out
(Helix, Strand, Coil) and ``value`` the probability of that state.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.protein_annotation import protein_entity
from depictio.recipes.lib.protein_families import texts_by_file
from depictio.recipes.lib.secondary_structure import SS2_SCHEMA, parse_ss2

RAW_DC_TAG = "s4pred_ss2_raw"
# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        dc_ref=RAW_DC_TAG,
        input_schema={"raw_line": pl.Utf8, "source_path": pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = dict(SS2_SCHEMA)


def _entity_and_sample(path: str) -> tuple[str, str]:
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    name = parts[-1] if parts else ""
    stem = name[: -len(".ss2")] if name.endswith(".ss2") else name
    sample = parts[-3] if len(parts) >= 3 and parts[-2] == "ss2" else stem
    return protein_entity(stem), protein_entity(sample)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse every ss2 file into its residue rows."""
    frames = []
    for path, text in texts_by_file(sources["raw"], text_col="raw_line").items():
        entity, sample = _entity_and_sample(path)
        frame = parse_ss2(text, entity, sample)
        if not frame.is_empty():
            frames.append(frame)
    if not frames:
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    return pl.concat(frames).sort(["sample", "entity", "position"]).select(list(OUTPUT_SCHEMA))
