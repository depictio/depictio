"""One row per protein family: representative, size, seed, model and alignment summary.

Sources (every one a raw scan the template declares):

- ``family_meta`` (required, ``proteinfamilies_family_meta_raw``): the
  ``<sample>_meta_mqc.csv`` tables of EXTRACT_FAMILY_REPS, MultiQC header lines
  starting with ``#`` dropped by the scan's ``comment_prefix``, then
  ``Sample Name,Family Id,Size,Representative Length,Representative Id,Sequence``
  (``Sample Name`` repeats the family id: it is MultiQC's row key). New
  families sit under ``family_reps/<sample>/``, the existing families an update
  run extended under ``update_families/family_reps/<sample>/``.
- ``hmms`` (optional, ``hmmer_hmm_raw`` text scan of the family ``.hmm.gz``):
  seed size (``NSEQ``), effective sequence number (``EFFN``), model length
  (``LENG``).
- ``alignments`` (optional, ``famsa_alignment_raw`` text scan of the full
  family alignments): aligned members, alignment width, mean identity and
  coverage of the members to the representative (first row), mean residue
  conservation along the representative and the share of its conserved
  residues (``depictio.recipes.lib.protein_families.column_conservation``).

The sample and the origin (``new`` / ``updated``) come from the file layout,
the family from the table (or, for models and alignments, the file name).

Output schema:
    family : Utf8                  family id
    sample : Utf8                  sample the family was built from or updated with
    origin : Utf8                  new (built by this run) / updated (an existing family extended)
    size : Int64                   member sequences
    representative_id : Utf8       id of the representative sequence
    representative_length : Int64  residues of the representative
    sequence : Utf8                representative sequence
    seed_size : Int64              sequences the family HMM was built from (NSEQ)
    recruited : Int64              members beyond the seed (size - seed_size, floored at 0)
    effective_sequences : Float64  HMMER effective sequence number (EFFN)
    model_length : Int64           match states of the family HMM (LENG)
    aligned_members : Int64        rows of the full alignment
    alignment_columns : Int64      columns of the full alignment
    mean_identity : Float64        mean identity of the members to the representative, 0-1
    mean_coverage : Float64        mean share of the representative the members cover, 0-1
    mean_conservation : Float64    mean conservation score along the representative, 0-1
    conserved_share : Float64      share of representative residues scored conserved, 0-1
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.msa import msa_frame, parse_fasta_alignment
from depictio.recipes.lib.protein_families import (
    column_conservation,
    conservation_class,
    family_id,
    origin_from_path,
    parse_hmm,
    sample_from_path,
    texts_by_file,
)

META_DC_TAG = "proteinfamilies_family_meta_raw"
HMM_DC_TAG = "hmmer_hmm_raw"
ALIGNMENT_DC_TAG = "famsa_alignment_raw"
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="family_meta", dc_ref=META_DC_TAG),
    RecipeSource(ref="hmms", dc_ref=HMM_DC_TAG, optional=True),
    RecipeSource(ref="alignments", dc_ref=ALIGNMENT_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "family": pl.Utf8,
    "sample": pl.Utf8,
    "origin": pl.Utf8,
    "size": pl.Int64,
    "representative_id": pl.Utf8,
    "representative_length": pl.Int64,
    "sequence": pl.Utf8,
    "seed_size": pl.Int64,
    "recruited": pl.Int64,
    "effective_sequences": pl.Float64,
    "model_length": pl.Int64,
    "aligned_members": pl.Int64,
    "alignment_columns": pl.Int64,
    "mean_identity": pl.Float64,
    "mean_coverage": pl.Float64,
    "mean_conservation": pl.Float64,
    "conserved_share": pl.Float64,
}

_META_COLUMNS = {
    "Family Id": "family",
    "Size": "size",
    "Representative Length": "representative_length",
    "Representative Id": "representative_id",
    "Sequence": "sequence",
}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _hmm_rows(raw: pl.DataFrame | None) -> pl.DataFrame:
    rows = []
    for path, text in texts_by_file(raw).items() if raw is not None else []:
        model = parse_hmm(text)
        rows.append(
            {
                "family": model["name"] or family_id(path),
                "seed_size": model["nseq"],
                "effective_sequences": model["effn"],
                "model_length": model["length"],
            }
        )
    schema = {
        "family": pl.Utf8,
        "seed_size": pl.Int64,
        "effective_sequences": pl.Float64,
        "model_length": pl.Int64,
    }
    return pl.DataFrame(rows, schema=schema).unique("family", keep="first", maintain_order=True)


def _alignment_rows(raw: pl.DataFrame | None) -> pl.DataFrame:
    rows = []
    for path, text in texts_by_file(raw).items() if raw is not None else []:
        records = parse_fasta_alignment(text)
        if not records:
            continue
        frame = msa_frame(records, family_id(path), cap=len(records))
        members = frame.filter(pl.col("rank") > 0)
        residues = column_conservation(records)
        scores = [r["value"] for r in residues]
        conserved = [s for s in scores if conservation_class(s) == "conserved"]
        rows.append(
            {
                "family": family_id(path),
                "aligned_members": len(records),
                "alignment_columns": len(records[0][1]),
                "mean_identity": members["identity"].mean() if members.height else None,
                "mean_coverage": members["coverage"].mean() if members.height else None,
                "mean_conservation": _mean(scores),
                "conserved_share": len(conserved) / len(scores) if scores else None,
            }
        )
    schema = {
        "family": pl.Utf8,
        "aligned_members": pl.Int64,
        "alignment_columns": pl.Int64,
        "mean_identity": pl.Float64,
        "mean_coverage": pl.Float64,
        "mean_conservation": pl.Float64,
        "conserved_share": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema).unique("family", keep="first", maintain_order=True)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per family of every sample, new and updated."""
    meta = sources["family_meta"]
    if meta is None or meta.height == 0 or "Family Id" not in meta.columns:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    paths = meta["source_path"].cast(pl.Utf8).fill_null("").to_list()
    families = (
        meta.rename({k: v for k, v in _META_COLUMNS.items() if k in meta.columns})
        .with_columns(
            pl.Series("sample", [sample_from_path(p) for p in paths], dtype=pl.Utf8),
            pl.Series("origin", [origin_from_path(p) for p in paths], dtype=pl.Utf8),
            pl.col("size").cast(pl.Int64, strict=False),
            pl.col("representative_length").cast(pl.Int64, strict=False),
        )
        .filter(pl.col("family").is_not_null())
        .unique(["sample", "family"], keep="first", maintain_order=True)
        .select(["family", "sample", "origin", *list(_META_COLUMNS.values())[1:]])
    )
    out = families.join(_hmm_rows(sources.get("hmms")), on="family", how="left").join(
        _alignment_rows(sources.get("alignments")), on="family", how="left"
    )
    out = out.with_columns(
        (pl.col("size") - pl.col("seed_size")).clip(lower_bound=0).alias("recruited")
    )
    return out.select(list(EXPECTED_SCHEMA)).cast(EXPECTED_SCHEMA).sort(["sample", "family"])  # type: ignore[arg-type]
