"""Nx curve per assembly, from the contig lengths the depth tables carry.

QUAST reports N50 and N75 as two numbers; the Nx curve is the whole function
they are two points of. For every x from 0 to 100, Nx is the length of the
contig at which the contigs sorted longest first reach x percent of the
assembly's bases, and Lx is how many contigs that took. A long-read assembly
holds a high plateau far to the right, a fragmented short-read one falls off
early, and the gap between two assemblers is read off the whole curve rather
than off its midpoint.

nf-core/mag does not publish the assemblies' FASTA, but it does publish one
`jgi_summarize_bam_contig_depths` table per assembly, and those list every
contig of the assembly with its length. This recipe reads the lengths from the
same raw scan `mag/contig_depths.py` uses (header rows included as data, which
is why rows whose length column is not a number are dropped here), keeps the
contigs of at least ``MIN_CONTIG_LENGTH`` bases (QUAST's own default, so the
curve at x = 50 equals the N50 of the assembly report), and computes the curve
at every integer percent.

Input: the ``mag_contig_depths_raw`` data collection (see
`depictio/catalog/mag/contig_depths.py` for its scan declaration).

Output schema:
    assembly_id : Utf8      <assembler>-<sample>
    assembler : Utf8        assembler that built it
    sample : Utf8           sample the assembly was built from
    nx : Float64            percent of the assembly's bases, 0 to 100
    contig_length : Int64   Nx, the length of the contig that reaches that percent
    n_contigs : Int64       Lx, how many contigs it took to get there
    total_length : Int64    bases in contigs of at least MIN_CONTIG_LENGTH
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mag_bins import file_stem

RAW_DC_TAG = "mag_contig_depths_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="depths", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "assembler": pl.Utf8,
    "sample": pl.Utf8,
    "nx": pl.Float64,
    "contig_length": pl.Int64,
    "n_contigs": pl.Int64,
    "total_length": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

#: QUAST's default `--min-contig`, so the curve agrees with the assembly report.
MIN_CONTIG_LENGTH = 500

#: One point per integer percent: 101 points per assembly, under the profile cap.
_PERCENTS = list(range(0, 101))

_FILE_SUFFIXES = ("-depth.txt.gz", "-depth.txt", ".txt.gz", ".txt")


def _nx_rows(assembly_id: str, lengths: list[int]) -> list[dict]:
    """The Nx curve of one assembly, from its contig lengths."""
    ordered = sorted(lengths, reverse=True)
    total = sum(ordered)
    assembler, _, sample = assembly_id.partition("-")
    rows: list[dict] = []
    cumulative = 0
    index = 0
    for percent in _PERCENTS:
        target = total * percent / 100.0
        # Walk forward until the contigs so far hold at least `target` bases;
        # the contig that crosses the line is Nx, its rank is Lx.
        while index < len(ordered) - 1 and cumulative + ordered[index] < target:
            cumulative += ordered[index]
            index += 1
        rows.append(
            {
                "assembly_id": assembly_id,
                "assembler": assembler or None,
                "sample": sample or None,
                "nx": float(percent),
                "contig_length": ordered[index],
                "n_contigs": index + 1,
                "total_length": total,
            }
        )
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Contig lengths per depth table, then the Nx curve of each assembly."""
    raw = sources["depths"]
    if raw.is_empty():
        raise ValueError("mag_nx_curve: the scanned depth tables are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "mag_nx_curve: the scan must set "
            f"`include_file_paths: {SOURCE_PATH_COL}`; the assembly is named by its file"
        )
    field_columns = [column for column in raw.columns if column != SOURCE_PATH_COL]
    if len(field_columns) < 2:
        raise ValueError(f"mag_nx_curve: expected a name and a length column, got {field_columns}")
    length_column = field_columns[1]

    lengths = (
        raw.select(
            pl.col(SOURCE_PATH_COL).cast(pl.Utf8),
            pl.col(length_column)
            .cast(pl.Utf8)
            .str.strip_chars()
            .cast(pl.Float64, strict=False)
            .cast(pl.Int64, strict=False)
            .alias("_length"),
        )
        # The header row of each file reads `contigLen` and casts to null.
        .drop_nulls("_length")
        .filter(pl.col("_length") >= MIN_CONTIG_LENGTH)
    )

    rows: list[dict] = []
    for (path,), part in lengths.group_by([SOURCE_PATH_COL], maintain_order=True):
        assembly_id = file_stem(str(path), *_FILE_SUFFIXES)
        rows.extend(_nx_rows(assembly_id, part["_length"].to_list()))

    if not rows:
        raise ValueError(
            f"mag_nx_curve: no contig reached {MIN_CONTIG_LENGTH} bp in any depth table"
        )

    return (
        pl.DataFrame(rows, schema=EXPECTED_SCHEMA)
        .select(list(EXPECTED_SCHEMA))
        .sort(["assembly_id", "nx"])
    )
