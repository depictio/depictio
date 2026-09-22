"""The contig-length ladder of each assembly, one row per length threshold.

QUAST reports its `--contig-thresholds` twice in every report, as
`# contigs (>= N bp)` and `Total length (>= N bp)`. Read across, those pairs are
the assembly's cumulative length curve: how many contigs, and how many bases,
survive each minimum length. It is the honest version of "this assembly is
125 Mb": an assembly whose length collapses between 1 kbp and 5 kbp is a
drift of fragments, one that holds its length out to 50 kbp is binnable.

QUAST's own Nx plot needs the per-contig lengths, which nf-core/mag does not
publish; this ladder is computed from numbers that are in every report.

Input: the same ``quast_assembly_raw`` scan `quast/assembly_report.py` reads.
The thresholds are discovered from the column names, so a run configured with
other `--contig-thresholds` produces the ladder it actually measured.

Output schema:
    assembly_id : Utf8       assembly as QUAST labelled it
    assembler : Utf8         assembler part of the label, null if unrecognised
    sample : Utf8            sample part of the label, null if unrecognised
    min_contig_length : Int64  the threshold this row reports on, in bp
    n_contigs : Int64        contigs at least that long
    total_length : Int64     bases held by those contigs
    length_fraction : Float64  those bases as a fraction of the longest rung, which
                               is the whole assembly when the run keeps QUAST's
                               default 0 bp threshold
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.quast_report import column_map, label_parts, threshold_columns

RAW_DC_TAG = "quast_assembly_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="reports", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "assembler": pl.Utf8,
    "sample": pl.Utf8,
    "min_contig_length": pl.Int64,
    "n_contigs": pl.Int64,
    "total_length": pl.Int64,
    "length_fraction": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpivot QUAST's threshold column pairs into one row per assembly and threshold."""
    raw = sources["reports"]
    if raw.is_empty():
        raise ValueError("quast_length_ladder: the scanned QUAST reports are empty")

    mapping = column_map(raw.columns)
    assembly_column = mapping.get("assembly")
    if assembly_column is None:
        raise ValueError(f"quast_length_ladder: no `Assembly` column in {raw.columns}")

    steps = threshold_columns(raw.columns)
    if not steps:
        raise ValueError(
            "quast_length_ladder: no `# contigs (>= N bp)` / `Total length (>= N bp)` "
            f"column pair in {raw.columns}"
        )

    def _threshold(original: str | None) -> pl.Expr:
        if original is None:
            return pl.lit(None, dtype=pl.Int64)
        return pl.col(original).cast(pl.Float64, strict=False).cast(pl.Int64, strict=False)

    rungs: list[pl.DataFrame] = []
    for bp, count_column, length_column in steps:
        rungs.append(
            raw.select(
                pl.col(assembly_column).cast(pl.Utf8).alias("assembly_id"),
                pl.lit(bp, dtype=pl.Int64).alias("min_contig_length"),
                _threshold(count_column).alias("n_contigs"),
                _threshold(length_column).alias("total_length"),
            )
        )

    ladder = pl.concat(rungs, how="vertical").drop_nulls(["assembly_id"])
    if ladder.is_empty():
        raise ValueError("quast_length_ladder: no row carried an assembly name")

    assembler, sample = label_parts(pl.col("assembly_id"))
    return (
        ladder.with_columns(
            assembler.alias("assembler"),
            sample.alias("sample"),
            (
                pl.col("total_length")
                / pl.col("total_length").max().over("assembly_id").cast(pl.Float64)
            ).alias("length_fraction"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["assembly_id", "min_contig_length"])
    )
