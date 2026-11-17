"""The profile HMM of every family as the table an HMM logo reads.

Consumes the raw ``hmmer_hmm_raw`` scan: the family HMMs ``hmmbuild`` wrote
(``<family>.hmm.gz``, HMMER3 text), one file line per row in ``raw`` plus
``source_path``. Each model becomes one row per match state and letter
(``depictio.recipes.lib.hmm.profile_frame``, the columns the ``hmm_logo`` kind
reads): the emission probability, the letter height in bits, the state's
information content, insert and delete behaviour, occupancy and the consensus,
RF and CS annotation characters.

``entity`` is the family, the HMM ``NAME``, which is the id the family's residue
and alignment tables carry too (``famsa/conservation``, ``famsa/alignment``).
``position`` links a state to a residue of the family representative. It is
filled when the run's ``hmmalign`` alignment of the family is also scanned
(``hmmer_hmmalign_raw``, ``full_msa/raw/hmmer_hmmalign/<sample>/<family>.sto.gz``)
and the representative is known:

- the representative is the ``Representative Id`` of the family in the family
  metadata scan (``proteinfamilies_family_meta_raw``): the sequence the family
  alignment lists first and ``famsa/conservation`` numbers its residues along;
- its row in the Stockholm file says which residue sits at each match state
  (insert columns skipped but counted, a deletion leaves the state without a
  residue);
- residues are numbered from 1 along the representative's own sequence, whatever
  ``/start-end`` suffix its id carries, which is the numbering of the family
  residue table and of a structure predicted from the representative.

A family with no alignment or no known representative keeps a null ``position``
(its logo is drawn, but selecting a state selects no residue). Families an update
run extended (``update_families/``) have no alignment of that kind either.

A family's model is read once: the filtered HMM of ``hmm/filtered/`` wins over a
raw model of the same name, and a file that is not a complete HMMER3 record is
left out. ``sample`` is the directory the file sits in.

Files are read one at a time (``iter_texts_by_file``), and of an alignment only
the representative's residue numbers are kept, so a run of thousands of families
is never held as text next to its table (#1418).

Output schema (``PROFILE_SCHEMA`` plus the sample):
    entity : Utf8          family id (the HMM name)
    position : Int64       residue of the representative at the state, null if none
    hmm_name, hmm_acc : Utf8    model NAME and ACC
    hmm_position : Int64   match state, 1 to M
    hmm_letter : Utf8      amino acid of the row
    emission : Float64     match emission probability of the letter
    height_bits : Float64  letter height, relative entropy above background
    info_bits : Float64    stack height of the state
    insert_prob, insert_length, occupancy, delete_prob : Float64
    consensus, rf, cs : Utf8    annotation characters of the state
    map_column : Int64     column of the seed alignment the state was built from
    sample : Utf8          sample the family was built from
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib import hmm as hmm_lib
from depictio.recipes.lib.hmm import PROFILE_SCHEMA, profile_frame
from depictio.recipes.lib.protein_families import (
    family_id,
    iter_texts_by_file,
    representative_positions,
    representatives,
    sample_from_path,
)

RAW_DC_TAG = "hmmer_hmm_raw"
ALIGNMENT_DC_TAG = "hmmer_hmmalign_raw"
META_DC_TAG = "proteinfamilies_family_meta_raw"
# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="hmms",
        dc_ref=RAW_DC_TAG,
        input_schema={"raw": pl.Utf8, "source_path": pl.Utf8},
    ),
    RecipeSource(
        ref="alignments",
        dc_ref=ALIGNMENT_DC_TAG,
        optional=True,
        input_schema={"raw": pl.Utf8, "source_path": pl.Utf8},
    ),
    RecipeSource(
        ref="family_meta",
        dc_ref=META_DC_TAG,
        optional=True,
        input_schema={
            "Family Id": pl.Utf8,
            "Representative Id": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {**PROFILE_SCHEMA, "sample": pl.Utf8}


def _is_raw_model(path: str) -> bool:
    """A model of ``hmm/raw/``: built before the family filter, kept only if nothing better exists."""
    return "/hmm/raw/" in "/" + path.replace("\\", "/")


def _positions_by_family(
    alignments: pl.DataFrame | None, reps: dict[tuple[str, str], str]
) -> dict[tuple[str, str], list[int | None] | None]:
    """The representative's residue at each match column of every family alignment.

    Read one alignment at a time, keeping only the numbers. ``None`` for an
    alignment the representative is absent from, or that does not parse. The
    model's length is checked against them later, when the model is read.
    """
    positions: dict[tuple[str, str], list[int | None] | None] = {}
    for path, text in iter_texts_by_file(alignments):
        key = (sample_from_path(path), family_id(path))
        representative = reps.get(key)
        if not (text and representative):
            positions.pop(key, None)  # as a later file of the same family would
            continue
        try:
            positions[key] = representative_positions(text, representative)
        except ValueError:  # representative absent, rows of unequal width, ...
            positions[key] = None
    return positions


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per match state and letter of every family HMM."""
    reps = representatives(sources.get("family_meta"))
    aligned = _positions_by_family(sources.get("alignments"), reps)
    frames: list[pl.DataFrame] = []
    seen: set[str] = set()
    # Filtered models first, raw ones after; scan order within each group.
    for path, text in iter_texts_by_file(sources["hmms"], order=_is_raw_model):
        try:
            parsed = hmm_lib.parse_hmm(text)
        except ValueError:
            continue
        sample = sample_from_path(path)
        for model in parsed:
            if model.name in seen:
                continue
            seen.add(model.name)
            positions = aligned.get((sample, model.name))
            if positions is not None and len(positions) != model.length:
                positions = None  # the states and the RF columns disagree
            frames.append(
                profile_frame(model, entity=model.name, positions=positions).with_columns(
                    pl.lit(sample, dtype=pl.Utf8).alias("sample")
                )
            )
    if not frames:
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    return pl.concat(frames).select(list(OUTPUT_SCHEMA)).cast(OUTPUT_SCHEMA)  # type: ignore[arg-type]
