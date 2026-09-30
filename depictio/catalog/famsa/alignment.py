"""The protein module's MSA table from per-family aligned FASTA files.

Consumes the raw ``famsa_alignment_raw`` scan, one file line per row::

    dc_specific_properties:
      format: TSV
      polars_kwargs:
        separator: "\\x1f"
        quote_char: null
        has_header: false
        new_columns: ["raw"]
        include_file_paths: "source_path"
        infer_schema_length: 0

Each file is one family alignment (``<step>/<sample>/<family>.aln``). The first
row is the family representative and becomes rank 0; identity and coverage of
every other row are measured against it (``depictio.recipes.lib.msa``). Rows
are capped at 500 per family in file order, which is what the ``msa`` kind
draws; the member table keeps every member.

Output schema (the contract's MSA table plus the sample):
    msa_id : Utf8              family id (the file name without its suffix)
    seq_id : Utf8              aligned sequence id (first word of the header)
    rank : Int64               row order, 0 = the family representative
    aligned_sequence : Utf8    aligned row, gaps as "-"
    identity : Float64         identity to the representative over shared columns, 0-1
    coverage : Float64         share of the representative's residues the row covers, 0-1
    sample : Utf8              sample the family was built from (directory of the file)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.msa import DEFAULT_CAP, MSA_SCHEMA, msa_frame, parse_fasta_alignment
from depictio.recipes.lib.protein_families import family_id, sample_from_path, texts_by_file

RAW_DC_TAG = "famsa_alignment_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="alignments", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {**MSA_SCHEMA, "sample": pl.Utf8}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per aligned sequence of every family, representative first."""
    frames: list[pl.DataFrame] = []
    for path, text in texts_by_file(sources["alignments"]).items():
        records = parse_fasta_alignment(text)
        if not records:
            continue
        frame = msa_frame(records, family_id(path), cap=DEFAULT_CAP)
        frames.append(frame.with_columns(pl.lit(sample_from_path(path)).alias("sample")))
    if not frames:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    return (
        pl.concat(frames, how="vertical")
        .unique(subset=["msa_id", "rank"], keep="first", maintain_order=True)
        .select(list(EXPECTED_SCHEMA))
        .cast(EXPECTED_SCHEMA)  # type: ignore[arg-type]
    )
