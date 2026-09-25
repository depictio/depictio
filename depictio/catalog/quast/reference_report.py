"""The reference-based columns of a QUAST report, one row per assembly.

QUAST adds a second block of columns to `transposed_report.tsv` when it is given
a reference: genome fraction, duplication ratio, misassembly counts, mismatch
and indel rates per 100 kbp, and the alignment-aware contiguity (NA50, NGA50,
LGA50). `quast/assembly_report.py` reads the reference-free block; this recipe
reads the other one from the same scan, and raises when the run had no
reference, so a template marks the collection optional.

Besides the `Assembly` label QUAST prints (the FASTA stem), each row carries the
name of the report directory it came from, ``report_id``. Pipelines that give
each assessed assembly its own QUAST directory name it after the assembly
(nf-core/genomeassembler: `QC/QUAST/<sample>_<stage>/`), which is the key their
other QC tools publish under; when the directory is QUAST's own (`QUAST`,
`quast`) the `Assembly` label is used instead.

Input: the ``quast_assembly_raw`` data collection `quast/assembly_report.py`
documents, scanned with `include_file_paths: source_path`.

Output schema:
    assembly_id : Utf8                 assembly as QUAST labelled it
    report_id : Utf8                   the report directory name, or assembly_id
    reference_length : Int64           reference bases
    genome_fraction : Float64          percent of the reference covered by aligned contigs
    duplication_ratio : Float64        aligned bases over covered reference bases
    misassemblies : Int64              relocations, translocations and inversions
    misassembled_contigs : Int64       contigs carrying at least one misassembly
    misassembled_length : Int64        bases in those contigs
    local_misassemblies : Int64        breakpoints under 1 kbp apart on the reference
    mismatches_per_100kbp : Float64    substitution rate against the reference
    indels_per_100kbp : Float64        indel rate against the reference
    unaligned_length : Int64           assembly bases that align nowhere on the reference
    largest_alignment : Int64          longest aligned block
    total_aligned_length : Int64       aligned bases
    ng50 : Int64                       N50 against the reference length
    nga50 : Int64                      NG50 of the blocks left after cutting at misassemblies
    lga50 : Int64                      how many blocks make up that NGA50
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.quast_report import column_map

RAW_DC_TAG = "quast_assembly_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="reports", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "report_id": pl.Utf8,
    "reference_length": pl.Int64,
    "genome_fraction": pl.Float64,
    "duplication_ratio": pl.Float64,
    "misassemblies": pl.Int64,
    "misassembled_contigs": pl.Int64,
    "misassembled_length": pl.Int64,
    "local_misassemblies": pl.Int64,
    "mismatches_per_100kbp": pl.Float64,
    "indels_per_100kbp": pl.Float64,
    "unaligned_length": pl.Int64,
    "largest_alignment": pl.Int64,
    "total_aligned_length": pl.Int64,
    "ng50": pl.Int64,
    "nga50": pl.Int64,
    "lga50": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

#: Output column -> QUAST column name after `quast_report.fold`.
REFERENCE_COLUMNS: dict[str, str] = {
    "reference_length": "reference_length",
    "genome_fraction": "genome_fraction",
    "duplication_ratio": "duplication_ratio",
    "misassemblies": "n_misassemblies",
    "misassembled_contigs": "n_misassembled_contigs",
    "misassembled_length": "misassembled_contigs_length",
    "local_misassemblies": "n_local_misassemblies",
    "mismatches_per_100kbp": "n_mismatches_per_100_kbp",
    "indels_per_100kbp": "n_indels_per_100_kbp",
    "unaligned_length": "unaligned_length",
    "largest_alignment": "largest_alignment",
    "total_aligned_length": "total_aligned_length",
    "ng50": "ng50",
    "nga50": "nga50",
    "lga50": "lga50",
}

#: QUAST's own output directory names, which say nothing about the assembly.
_GENERIC_DIRS = frozenset({"quast", "quast_results", "results", ""})


def report_dir(source_path: str) -> str:
    """The directory a transposed report sits in."""
    return PurePosixPath(source_path.replace("\\", "/")).parent.name


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Keep the reference-based columns of every QUAST row."""
    raw = sources["reports"]
    if raw.is_empty():
        raise ValueError("quast_reference_report: the scanned QUAST reports are empty")
    mapping = column_map(raw.columns)
    assembly_column = mapping.get("assembly")
    if assembly_column is None:
        raise ValueError(f"quast_reference_report: no `Assembly` column in {raw.columns}")
    if mapping.get("genome_fraction") is None:
        raise ValueError(
            "quast_reference_report: no `Genome fraction (%)` column; QUAST ran without a "
            "reference, declare this collection optional"
        )

    label = pl.col(assembly_column).cast(pl.Utf8)
    if SOURCE_PATH_COL in raw.columns:
        directory = pl.col(SOURCE_PATH_COL).map_elements(report_dir, return_dtype=pl.Utf8)
        report_id = (
            pl.when(directory.str.to_lowercase().is_in(list(_GENERIC_DIRS)))
            .then(label)
            .otherwise(directory)
        )
    else:
        report_id = label

    selected = [label.alias("assembly_id"), report_id.alias("report_id")]
    for alias, folded in REFERENCE_COLUMNS.items():
        dtype = EXPECTED_SCHEMA[alias]
        original = mapping.get(folded)
        if original is None:
            selected.append(pl.lit(None, dtype=dtype).alias(alias))
            continue
        # QUAST writes "3 + 3 part" for partial counts; the leading number is the full count.
        value = (
            pl.col(original)
            .cast(pl.Utf8)
            .str.extract(r"^\s*(-?[\d.]+)", 1)
            .cast(pl.Float64, strict=False)
        )
        selected.append(
            (value.cast(pl.Int64, strict=False) if dtype == pl.Int64 else value).alias(alias)
        )

    out = (
        raw.select(selected)
        .drop_nulls(["assembly_id"])
        .unique(subset=["report_id"], keep="first", maintain_order=True)
    )
    if out.is_empty():
        raise ValueError("quast_reference_report: no row carried an assembly name")
    return out.select(list(EXPECTED_SCHEMA)).sort("report_id")
