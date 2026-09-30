"""Nx curve of every assessed assembly, from the lengths `samtools idxstats` lists.

N50 is one point of a curve: for every x from 0 to 100, Nx is the length of the
sequence at which the sequences, longest first, reach x percent of the assembly,
and Lx how many it took. nf-core/genomeassembler aligns the reads back to every
assembly it assesses and publishes `samtools idxstats` for each alignment as
`<sample>_<stage>.idxstats`; its first two columns are every sequence of the
assembly and its exact length. Scaffolding moves the curve right, polishing
leaves it where it was, and two assemblers are compared on the whole curve
rather than on its midpoint.

Only the idxstats files named after an assembly stage are read; the reads
aligned to the reference (`_to_reference`) and the polishing short reads
(`_shortreads`) are not assemblies and are skipped.

Input: the ``samtools_idxstats_raw`` data collection, a recursive Table scan
(regex '^.+\\.idxstats$', TSV, no header, `new_columns: [sequence, length,
mapped, unmapped]`, `include_file_paths: source_path`, `infer_schema_length: 0`).

Output schema:
    assembly_id : Utf8        `<sample>_<stage>`
    sample : Utf8             samplesheet sample
    stage : Utf8              assembly, a polisher or a scaffolder
    nx : Float64              percent of the assembly's bases, 0 to 100
    sequence_length : Int64   Nx, the length of the sequence that reaches that percent
    n_sequences : Int64       Lx, how many sequences it took
    total_length : Int64      assembled bases
"""

from __future__ import annotations

import re
from bisect import bisect_left
from itertools import accumulate
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "samtools_idxstats_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="idxstats", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "sample": pl.Utf8,
    "stage": pl.Utf8,
    "nx": pl.Float64,
    "sequence_length": pl.Int64,
    "n_sequences": pl.Int64,
    "total_length": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

#: The pipeline's stage words, as in `assemblies.py`.
STAGE_WORDS = (
    "assembly",
    "medaka",
    "dorado",
    "pilon",
    "links",
    "longstitch",
    "ragtag",
    "yahs",
    "hic",
)
_LABEL = re.compile(rf"^(?P<sample>.+)_(?P<stage>{'|'.join(STAGE_WORDS)})$")


def nx_rows(lengths: list[int]) -> list[tuple[float, int, int]]:
    """(x, Nx, Lx) for x = 0, 1, ..., 100."""
    ordered = sorted((v for v in lengths if v > 0), reverse=True)
    total = sum(ordered)
    if not total:
        return []
    cumulative = list(accumulate(ordered))
    rows: list[tuple[float, int, int]] = []
    for x in range(101):
        # First sequence whose running sum reaches x percent of the bases.
        index = bisect_left(cumulative, total * x / 100)
        index = min(index, len(ordered) - 1)
        rows.append((float(x), ordered[index], index + 1))
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One Nx row per percent per assessed assembly."""
    raw = sources["idxstats"]
    if raw.is_empty():
        raise ValueError("genomeassembler nx_curve: the scanned idxstats files are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError("genomeassembler nx_curve: the scan must include_file_paths: source_path")
    name_col, length_col = [c for c in raw.columns if c != SOURCE_PATH_COL][:2]
    tidy = raw.select(
        pl.col(SOURCE_PATH_COL)
        .map_elements(
            lambda p: PurePosixPath(p.replace("\\", "/")).name.removesuffix(".idxstats"),
            return_dtype=pl.Utf8,
        )
        .alias("assembly_id"),
        pl.col(name_col).cast(pl.Utf8).alias("name"),
        pl.col(length_col).cast(pl.Float64, strict=False).cast(pl.Int64).alias("length"),
    ).filter((pl.col("name") != "*") & pl.col("length").is_not_null())

    records = []
    for (label,), group in tidy.group_by(["assembly_id"], maintain_order=True):
        match = _LABEL.match(str(label))
        if match is None:
            continue
        lengths = group["length"].to_list()
        total = sum(v for v in lengths if v > 0)
        for x, nx, lx in nx_rows(lengths):
            records.append(
                {
                    "assembly_id": label,
                    "sample": match.group("sample"),
                    "stage": match.group("stage"),
                    "nx": x,
                    "sequence_length": nx,
                    "n_sequences": lx,
                    "total_length": total,
                }
            )
    if not records:
        raise ValueError(
            "genomeassembler nx_curve: no idxstats file is named `<sample>_<stage>.idxstats`"
        )
    return pl.DataFrame(records, schema=EXPECTED_SCHEMA).sort(["assembly_id", "nx"])
