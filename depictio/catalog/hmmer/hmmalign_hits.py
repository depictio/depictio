"""How much of its family HMM each member covers, from the hmmalign alignment.

Consumes the raw ``hmmer_hmmalign_raw`` scan: the Stockholm alignment of every
family against its HMM (``hmmalign``, ``full_msa/raw/hmmer_hmmalign/<sample>/
<family>.sto.gz``), one file line per row in ``raw`` plus ``source_path``. There
is no domain table in nf-core/proteinfamilies, so the hits an HMM logo draws under
its states are derived from the alignment: one row per member, with the stretch of
the model it covers.

The columns are the ones ``hmmer/hmmsearch_domtbl`` writes and the ``hmm_logo``
kind's hits lane reads, so the lane binds with its defaults:

- ``entity`` is the member (the row name, as in ``proteinfamilies/family_members``)
  and ``label`` the family, the HMM name that ``hmmer/hmm_profile`` calls ``entity``;
- ``hmm_from`` / ``hmm_to`` are the first and last match state the member has a
  residue at, ``hmm_length`` the number of match states (the ``#=GC RF`` columns),
  ``hmm_coverage`` the share of the model between the two;
- ``ali_from`` / ``ali_to`` are the member's residues at those two states, counted
  from 1 along its own sequence, and ``protein_length`` its length;
- ``i_evalue`` and ``dom_score`` are null: an alignment carries no search
  statistics, so a lane reading them sets ``hits_evalue_max: null``.

A member with no residue in any match state is left out; ``sample`` is the
directory the file sits in. Deletions inside the covered stretch are not
subtracted.

Output schema:
    entity : Utf8          member sequence id
    sample : Utf8          sample the family was built from
    label : Utf8           family id (the HMM name)
    protein_length : Int64 residues of the member
    hmm_length : Int64     match states of the model
    hmm_from, hmm_to : Int64    first and last match state the member covers
    ali_from, ali_to : Int64    its residues at those states
    hmm_coverage : Float64      share of the model between hmm_from and hmm_to
    i_evalue, dom_score : Float64    always null
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.hmm import member_spans_from_stockholm
from depictio.recipes.lib.protein_families import family_id, sample_from_path, texts_by_file

RAW_DC_TAG = "hmmer_hmmalign_raw"
# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="alignments",
        dc_ref=RAW_DC_TAG,
        input_schema={"raw": pl.Utf8, "source_path": pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "label": pl.Utf8,
    "protein_length": pl.Int64,
    "hmm_length": pl.Int64,
    "hmm_from": pl.Int64,
    "hmm_to": pl.Int64,
    "ali_from": pl.Int64,
    "ali_to": pl.Int64,
    "hmm_coverage": pl.Float64,
    "i_evalue": pl.Float64,
    "dom_score": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per member of every family alignment."""
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for path, text in texts_by_file(sources["alignments"]).items():
        family, sample = family_id(path), sample_from_path(path)
        if (sample, family) in seen:
            continue
        seen.add((sample, family))
        try:
            spans = member_spans_from_stockholm(text)
        except ValueError:  # rows of unequal width, or no sequence: not an alignment
            continue
        for span in spans:
            rows.append(
                {
                    "entity": span.name,
                    "sample": sample,
                    "label": family,
                    "protein_length": span.length,
                    "hmm_length": span.n_states,
                    "hmm_from": span.hmm_from,
                    "hmm_to": span.hmm_to,
                    "ali_from": span.ali_from,
                    "ali_to": span.ali_to,
                    "hmm_coverage": round((span.hmm_to - span.hmm_from + 1) / span.n_states, 3),
                    "i_evalue": None,
                    "dom_score": None,
                }
            )
    if not rows:
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA).sort(["sample", "label", "entity"])
