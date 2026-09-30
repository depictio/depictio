"""One row per family member, with its identity to the family representative.

Sources:

- ``members`` (required, ``proteinfamilies_family_members_raw``): the
  two-column ``family_id`` / ``member_id`` rosters of EXTRACT_FAMILY_MEMBERS,
  ``family_reps/<sample>/<sample>.tsv`` for the families a run built and
  ``update_families/family_reps/<sample>/<sample>.tsv`` for the existing
  families an update run extended, the file in ``source_path``.
- ``alignments`` (optional, ``famsa_alignment_raw`` text scan of the full
  family alignments): each member's identity and coverage against the first
  (representative) row, and its ungapped length. Every member is kept here,
  where the MSA table caps its rows.

Output schema:
    family : Utf8               family id
    member_id : Utf8            member sequence id
    sample : Utf8               sample the family was built from or updated with
    origin : Utf8               new / updated (see family_metadata)
    is_representative : Boolean the family's representative (first aligned row)
    in_alignment : Boolean      the member is a row of the family's full alignment
    identity : Float64          identity to the representative over shared columns, 0-1
    coverage : Float64          share of the representative's residues the member covers, 0-1
    length : Int64              ungapped member length, residues
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.msa import msa_frame, parse_fasta_alignment
from depictio.recipes.lib.protein_families import (
    family_id,
    origin_from_path,
    sample_from_path,
    texts_by_file,
    ungapped,
)

MEMBERS_DC_TAG = "proteinfamilies_family_members_raw"
ALIGNMENT_DC_TAG = "famsa_alignment_raw"
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="members", dc_ref=MEMBERS_DC_TAG),
    RecipeSource(ref="alignments", dc_ref=ALIGNMENT_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "family": pl.Utf8,
    "member_id": pl.Utf8,
    "sample": pl.Utf8,
    "origin": pl.Utf8,
    "is_representative": pl.Boolean,
    "in_alignment": pl.Boolean,
    "identity": pl.Float64,
    "coverage": pl.Float64,
    "length": pl.Int64,
}

_ALIGNED_SCHEMA: dict[str, type[pl.DataType]] = {
    "family": pl.Utf8,
    "member_id": pl.Utf8,
    "rank": pl.Int64,
    "identity": pl.Float64,
    "coverage": pl.Float64,
    "length": pl.Int64,
}


def _aligned(raw: pl.DataFrame | None) -> pl.DataFrame:
    frames = []
    for path, text in texts_by_file(raw).items() if raw is not None else []:
        records = parse_fasta_alignment(text)
        if not records:
            continue
        frame = msa_frame(records, family_id(path), cap=len(records))
        frames.append(
            frame.select(
                pl.col("msa_id").alias("family"),
                pl.col("seq_id").alias("member_id"),
                "rank",
                "identity",
                "coverage",
                pl.Series("length", [len(ungapped(seq)) for _, seq in records], dtype=pl.Int64),
            )
        )
    if not frames:
        return pl.DataFrame(schema=_ALIGNED_SCHEMA)
    return (
        pl.concat(frames)
        .cast(_ALIGNED_SCHEMA)  # type: ignore[arg-type]
        .unique(["family", "member_id"], keep="first", maintain_order=True)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (family, member) of every roster."""
    raw = sources["members"]
    if raw is None or raw.height == 0 or "member_id" not in raw.columns:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    paths = raw["source_path"].cast(pl.Utf8).fill_null("").to_list()
    members = (
        raw.select(
            pl.col("family_id").cast(pl.Utf8).alias("family"),
            pl.col("member_id").cast(pl.Utf8),
            pl.Series("sample", [sample_from_path(p) for p in paths], dtype=pl.Utf8),
            pl.Series("origin", [origin_from_path(p) for p in paths], dtype=pl.Utf8),
        )
        .drop_nulls(["family", "member_id"])
        .unique(["family", "member_id"], keep="first", maintain_order=True)
    )
    out = members.join(_aligned(sources.get("alignments")), on=["family", "member_id"], how="left")
    out = out.with_columns(
        (pl.col("rank") == 0).fill_null(False).alias("is_representative"),
        pl.col("rank").is_not_null().alias("in_alignment"),
        pl.col("identity").round(3),
        pl.col("coverage").round(3),
    )
    return (
        out.select(list(EXPECTED_SCHEMA))
        .cast(EXPECTED_SCHEMA)  # type: ignore[arg-type]
        .sort(["sample", "family", "member_id"])
    )
