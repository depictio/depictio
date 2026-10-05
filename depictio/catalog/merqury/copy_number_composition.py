"""Share of solid read k-mers by copy number in the assembly, per assembly.

Merqury's `<prefix>.<asm>.spectra-cn.hist` is a histogram with three columns,
`Copies` (read-only, 1, 2, 3, 4, >4), `kmer_multiplicity` (how often the k-mer
occurs in the reads) and `Count`. Summed over the multiplicities above the read
error trough, each copy class gives the number of solid read k-mers the
assembly holds that many times; `read-only` is the solid k-mers it lost.

The error trough is found per file on the histogram summed over the copy
classes: the first multiplicity after which the count rises again. That is the
cutoff Merqury's own ploidy estimate reports as the error boundary, derived from
the file in hand rather than a fixed threshold.

Input: the ``merqury_spectra_cn_raw`` data collection, a recursive Table scan
(regex '^.+\\.spectra-cn\\.hist$', TSV with header, `include_file_paths:
source_path`, `infer_schema_length: 0`).

Output schema:
    assembly_id : Utf8     the file prefix (the part before the first dot)
    copy_class : Utf8      "Absent", "1 copy", "2 copies", "3 copies", "4 copies" or "More than 4"
    rank : Utf8            always "Copy number"
    class_order : Int64    0 for Absent, then 1 to 5 in copy order
    solid_kmers : Int64    solid read k-mers in the class
    percent : Float64      the class share of the solid read k-mers, percent
    error_cutoff : Int64   the read multiplicity at or below which k-mers were left out
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "merqury_spectra_cn_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="spectra", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "copy_class": pl.Utf8,
    "rank": pl.Utf8,
    "class_order": pl.Int64,
    "solid_kmers": pl.Int64,
    "percent": pl.Float64,
    "error_cutoff": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

#: Merqury copy label -> (display label, order).
CLASSES: dict[str, tuple[str, int]] = {
    "read-only": ("Absent", 0),
    "1": ("1 copy", 1),
    "2": ("2 copies", 2),
    "3": ("3 copies", 3),
    "4": ("4 copies", 4),
    ">4": ("More than 4", 5),
}


def file_prefix(source_path: str) -> str:
    """`<dir>/<prefix>.<asm>.spectra-cn.hist` -> `<prefix>`."""
    return PurePosixPath(source_path.replace("\\", "/")).name.split(".", 1)[0]


def error_trough(multiplicity: list[int], counts: list[int]) -> int:
    """The first multiplicity after which the summed histogram rises again.

    Falls back to 1 (drop only singletons) when the histogram never turns up.
    """
    pairs = sorted(zip(multiplicity, counts, strict=True))
    for (m, c), (_, next_c) in zip(pairs, pairs[1:], strict=False):
        if next_c > c:
            return m
    return 1


def _one_file(path: str, frame: pl.DataFrame) -> pl.DataFrame:
    totals = (
        frame.group_by("kmer_multiplicity").agg(pl.col("Count").sum()).sort("kmer_multiplicity")
    )
    cutoff = error_trough(totals["kmer_multiplicity"].to_list(), totals["Count"].to_list())
    by_class = (
        frame.filter(pl.col("kmer_multiplicity") > cutoff)
        .group_by("Copies")
        .agg(pl.col("Count").sum().alias("solid_kmers"))
    )
    total = by_class["solid_kmers"].sum()
    rows = []
    for copies, (label, order) in CLASSES.items():
        match = by_class.filter(pl.col("Copies") == copies)
        kmers = int(match["solid_kmers"][0]) if match.height else 0
        rows.append(
            {
                "assembly_id": file_prefix(path),
                "copy_class": label,
                "rank": "Copy number",
                "class_order": order,
                "solid_kmers": kmers,
                "percent": (100.0 * kmers / total) if total else None,
                "error_cutoff": cutoff,
            }
        )
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Sum each copy class above the per-file error trough."""
    raw = sources["spectra"]
    if raw.is_empty():
        raise ValueError("merqury_copy_number_composition: the scanned spectra are empty")
    needed = {"Copies", "kmer_multiplicity", "Count", SOURCE_PATH_COL}
    if not needed.issubset(raw.columns):
        raise ValueError(
            f"merqury_copy_number_composition: need {sorted(needed)}, got {raw.columns}"
        )
    tidy = raw.select(
        pl.col(SOURCE_PATH_COL).cast(pl.Utf8),
        pl.col("Copies").cast(pl.Utf8).str.strip_chars(),
        pl.col("kmer_multiplicity").cast(pl.Float64, strict=False).cast(pl.Int64),
        pl.col("Count").cast(pl.Float64, strict=False).cast(pl.Int64),
    ).drop_nulls()
    parts = [
        _one_file(str(path), group)
        for (path,), group in tidy.group_by([SOURCE_PATH_COL], maintain_order=True)
    ]
    if not parts:
        raise ValueError("merqury_copy_number_composition: no spectrum carried a data row")
    return (
        pl.concat(parts, how="vertical")
        .unique(subset=["assembly_id", "copy_class"], keep="first", maintain_order=True)
        .sort(["assembly_id", "class_order"])
    )
