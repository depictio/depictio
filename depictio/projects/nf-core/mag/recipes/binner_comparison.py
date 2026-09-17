"""How many bins did each binner recover per sample and assembler?

Reads `bin_summary` (already one row per bin) rather than the raw
contig-to-bin map again, and collapses it one level further: one row per
(sample, assembler, binner), counting bins and summarising the contigs-per-bin
spread each binner produced. This is the table the "binner agreement" bar
chart and the funnel-level cards read, how aggressively each binner split
the assembly, not whether the bins are any good (no completeness/contamination
table ships locally for that; see bin_summary.py's docstring).

Output schema:
    sample : Utf8                     sample the assembly was built from
    assembler : Utf8                  FLYE, MEGAHIT, METAMDBG or SPAdes
    binner : Utf8                     COMEBin, MaxBin2, MetaBAT2, MetaBinner or SemiBin2
    n_bins : Int64                    bins this binner recovered
    total_contigs : Int64             contigs placed into any bin
    mean_contigs_per_bin : Float64    total_contigs / n_bins
    median_contigs_per_bin : Float64  median bin size (contigs)
    max_contigs_per_bin : Int64       largest bin (contigs)
    min_contigs_per_bin : Int64       smallest bin (contigs)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="bins", dc_ref="bin_summary"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "binner": pl.Utf8,
    "n_bins": pl.Int64,
    "total_contigs": pl.Int64,
    "mean_contigs_per_bin": pl.Float64,
    "median_contigs_per_bin": pl.Float64,
    "max_contigs_per_bin": pl.Int64,
    "min_contigs_per_bin": pl.Int64,
}

_REQUIRED = ["sample", "assembler", "binner", "n_contigs"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Aggregate bin_summary to one row per (sample, assembler, binner)."""
    df = sources["bins"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"mag binner_comparison: bin_summary lacks columns {missing}")

    out = (
        df.group_by(["sample", "assembler", "binner"])
        .agg(
            pl.len().alias("n_bins"),
            pl.col("n_contigs").sum().alias("total_contigs"),
            pl.col("n_contigs").mean().alias("mean_contigs_per_bin"),
            pl.col("n_contigs").median().alias("median_contigs_per_bin"),
            pl.col("n_contigs").max().alias("max_contigs_per_bin"),
            pl.col("n_contigs").min().alias("min_contigs_per_bin"),
        )
        .with_columns(
            pl.col("n_bins").cast(pl.Int64),
            pl.col("total_contigs").cast(pl.Int64),
            pl.col("mean_contigs_per_bin").cast(pl.Float64),
            pl.col("median_contigs_per_bin").cast(pl.Float64),
            pl.col("max_contigs_per_bin").cast(pl.Int64),
            pl.col("min_contigs_per_bin").cast(pl.Int64),
        )
        .sort(["sample", "assembler", "binner"])
    )
    return out
