"""Identification yield and immunopeptidome signature, one row per sample.

Reduces the ``mhcquant_peptides`` collection to the numbers a reader compares
samples on: PSMs, distinct peptides and peptidoforms, source proteins, the share
of modified peptides, the length profile (median length, 9-mer share, share in
the class I window of 8 to 12 residues and the class II window of 13 to 25), and
the score and retention-time error medians. When the run quantified, the
replicate collection adds how reproducible the sample is: the share of peptides
quantified in every replicate and the median and lowest Pearson correlation of
log10 intensities over replicate pairs.
"""

from __future__ import annotations

from itertools import combinations

import polars as pl

from depictio.models.models.transforms import RecipeSource

PEPTIDES_DC_TAG = "mhcquant_peptides"
REPLICATES_DC_TAG = "mhcquant_replicate_intensity"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="peptides", dc_ref=PEPTIDES_DC_TAG),
    RecipeSource(ref="replicates", dc_ref=REPLICATES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "psms": pl.Int64,
    "peptides": pl.Int64,
    "peptidoforms": pl.Int64,
    "proteins": pl.Int64,
    "modified_fraction": pl.Float64,
    "median_length": pl.Float64,
    "ninemer_fraction": pl.Float64,
    "class_i_fraction": pl.Float64,
    "class_ii_fraction": pl.Float64,
    "median_score": pl.Float64,
    "median_abs_rt_error_min": pl.Float64,
    "replicates": pl.Int64,
    "all_replicates_fraction": pl.Float64,
    "replicate_median_r": pl.Float64,
    "replicate_min_r": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# Fewer shared quantified peptides than this and a correlation is noise.
MIN_PAIR_PEPTIDES = 20


def _replicate_stats(rep: pl.DataFrame | None) -> pl.DataFrame:
    schema = {
        "sample": pl.Utf8,
        "replicates": pl.Int64,
        "all_replicates_fraction": pl.Float64,
        "replicate_median_r": pl.Float64,
        "replicate_min_r": pl.Float64,
    }
    if rep is None or rep.is_empty():
        return pl.DataFrame(schema=schema)
    rows = []
    for (sample,), frame in rep.group_by("sample"):
        wide = frame.pivot(on="replicate", index="peptide", values="log10_intensity")
        reps = [c for c in wide.columns if c != "peptide"]
        detected = wide.select(
            pl.all_horizontal([pl.col(c).is_not_null() for c in reps])
        ).to_series()
        rs = []
        for a, b in combinations(reps, 2):
            pair = wide.select(a, b).drop_nulls()
            if pair.height >= MIN_PAIR_PEPTIDES:
                rs.append(pair.select(pl.corr(a, b)).item())
        rows.append(
            {
                "sample": sample,
                "replicates": len(reps),
                "all_replicates_fraction": float(detected.mean()) if wide.height else None,
                "replicate_median_r": float(pl.Series(rs).median()) if rs else None,
                "replicate_min_r": float(min(rs)) if rs else None,
            }
        )
    return pl.DataFrame(rows, schema=schema)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    pep = sources["peptides"]
    per_sequence = pep.unique(subset=["sample", "sequence"])
    base = pep.group_by("sample").agg(
        pl.col("psms").sum().cast(pl.Int64).alias("psms"),
        pl.col("sequence").n_unique().cast(pl.Int64).alias("peptides"),
        pl.col("peptide").n_unique().cast(pl.Int64).alias("peptidoforms"),
        pl.col("proteins").str.split(";").flatten().n_unique().cast(pl.Int64).alias("proteins"),
        (pl.col("modification_state") == "Modified").mean().alias("modified_fraction"),
        pl.col("score").median().alias("median_score"),
        pl.col("rt_error_min").abs().median().alias("median_abs_rt_error_min"),
    )
    lengths = per_sequence.group_by("sample").agg(
        pl.col("length").median().cast(pl.Float64).alias("median_length"),
        (pl.col("length") == 9).mean().alias("ninemer_fraction"),
        pl.col("length").is_between(8, 12).mean().alias("class_i_fraction"),
        pl.col("length").is_between(13, 25).mean().alias("class_ii_fraction"),
    )
    out = base.join(lengths, on="sample", how="left").join(
        _replicate_stats(sources.get("replicates")), on="sample", how="left"
    )
    return out.select(list(EXPECTED_SCHEMA)).sort("sample")
