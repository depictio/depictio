"""Replicate-against-replicate peptide intensities, one row per peptide and pair.

For every sample and every pair of its raw replicates, the log10 intensities of
the peptides quantified in both. Plotted as x against y the cloud should hug the
diagonal; a pair whose cloud is wide or offset flags a replicate with a spray,
loading or alignment problem. A sample with three replicates gives three pairs.
"""

from __future__ import annotations

from itertools import combinations

import polars as pl

from depictio.models.models.transforms import RecipeSource

REPLICATES_DC_TAG = "mhcquant_replicate_intensity"

SOURCES: list[RecipeSource] = [RecipeSource(ref="replicates", dc_ref=REPLICATES_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "peptide": pl.Utf8,
    "pair": pl.Utf8,
    "intensity_a": pl.Float64,
    "intensity_b": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    rep = sources["replicates"].filter(pl.col("log10_intensity").is_not_null())
    frames = []
    for (sample,), frame in rep.group_by("sample"):
        wide = frame.pivot(on="replicate", index="peptide", values="log10_intensity")
        reps = sorted((c for c in wide.columns if c != "peptide"), key=int)
        for a, b in combinations(reps, 2):
            frames.append(
                wide.select(
                    pl.lit(sample).alias("sample"),
                    pl.col("peptide"),
                    pl.lit(f"Replicate {a} vs {b}").alias("pair"),
                    pl.col(a).cast(pl.Float64).alias("intensity_a"),
                    pl.col(b).cast(pl.Float64).alias("intensity_b"),
                ).drop_nulls()
            )
    if not frames:
        raise ValueError("mhcquant replicate pairs: no sample has two quantified replicates")
    return pl.concat(frames).select(list(EXPECTED_SCHEMA)).sort(["sample", "pair", "peptide"])
