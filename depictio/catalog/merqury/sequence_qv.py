"""One row per assembled sequence, from Merqury's per-sequence QV files.

Next to the assembly-level `<prefix>.qv`, Merqury writes `<prefix>.<asm>.qv`
with the same five columns for every sequence of the assembly: its name, the
k-mers found only in the assembly, all its k-mers, the QV and the error rate.
The assembly is keyed on `<prefix>`, the part of the file name before the first
dot, which is the name the pipeline gave the run.

A sequence with no error k-mer gets QV `+inf`. That is kept as a null QV with
`error_free` set, so a numeric axis never meets an infinity.

Input: the ``merqury_sequence_qv_raw`` data collection, a recursive Table scan
(regex '^[^.]+\\..+\\.qv$', TSV, no header, `new_columns: [c1, c2, c3, c4, c5]`,
`include_file_paths: source_path`, `infer_schema_length: 0`).

Output schema:
    assembly_id : Utf8        the file prefix
    sequence : Utf8           contig or scaffold name
    asm_only_kmers : Int64    k-mers of the sequence never seen in the reads
    total_kmers : Int64       all k-mers of the sequence (its length minus k plus 1)
    qv : Float64              per-sequence QV (null when error_free)
    error_rate : Float64      per-base error rate
    error_free : Utf8         "yes" when the sequence has no error k-mer, else "no"
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "merqury_sequence_qv_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="sequences", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "sequence": pl.Utf8,
    "asm_only_kmers": pl.Int64,
    "total_kmers": pl.Int64,
    "qv": pl.Float64,
    "error_rate": pl.Float64,
    "error_free": pl.Utf8,
}

SOURCE_PATH_COL = "source_path"


def file_prefix(source_path: str) -> str:
    """`<dir>/<prefix>.<asm>.qv` -> `<prefix>`."""
    return PurePosixPath(source_path.replace("\\", "/")).name.split(".", 1)[0]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Key every per-sequence row on its file prefix and tame the infinite QVs."""
    raw = sources["sequences"]
    if raw.is_empty():
        raise ValueError("merqury_sequence_qv: the scanned per-sequence QV files are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError("merqury_sequence_qv: the scan must include_file_paths: source_path")
    cols = [c for c in raw.columns if c != SOURCE_PATH_COL]
    if len(cols) < 5:
        raise ValueError(f"merqury_sequence_qv: expected 5 columns, got {cols}")
    name, asm_only, total, qv, error = cols[:5]

    qv_value = pl.col(qv).cast(pl.Utf8).str.strip_chars().cast(pl.Float64, strict=False)
    return (
        raw.select(
            pl.col(SOURCE_PATH_COL)
            .map_elements(file_prefix, return_dtype=pl.Utf8)
            .alias("assembly_id"),
            pl.col(name).cast(pl.Utf8).alias("sequence"),
            pl.col(asm_only).cast(pl.Float64, strict=False).cast(pl.Int64).alias("asm_only_kmers"),
            pl.col(total).cast(pl.Float64, strict=False).cast(pl.Int64).alias("total_kmers"),
            pl.when(qv_value.is_infinite()).then(None).otherwise(qv_value).alias("qv"),
            pl.col(error).cast(pl.Float64, strict=False).alias("error_rate"),
            pl.when(qv_value.is_infinite() | (pl.col(asm_only).cast(pl.Float64, strict=False) == 0))
            .then(pl.lit("yes"))
            .otherwise(pl.lit("no"))
            .alias("error_free"),
        )
        .drop_nulls(["sequence"])
        .select(list(EXPECTED_SCHEMA))
        .sort(["assembly_id", "total_kmers"], descending=[False, True])
    )
