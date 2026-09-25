"""Replicate membership matrix, one row per sample and peptidoform.

One 0/1 column per replicate index (``rep_1``, ``rep_2`` ...) saying whether the
peptide was quantified in that raw file. Pooled over samples, an UpSet plot of
it shows how much of each immunopeptidome is seen in every replicate and how
much hangs on a single injection. A sample with fewer replicates than the widest
one has 0 in the extra columns.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

REPLICATES_DC_TAG = "mhcquant_replicate_intensity"

SOURCES: list[RecipeSource] = [RecipeSource(ref="replicates", dc_ref=REPLICATES_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "peptide": pl.Utf8,
    "replicates_detected": pl.Int64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    rep = sources["replicates"].with_columns(
        ("rep_" + pl.col("replicate").cast(pl.Utf8)).alias("_set")
    )
    wide = rep.pivot(
        on="_set", index=["sample", "peptide"], values="detected", aggregate_function="max"
    )
    sets = sorted((c for c in wide.columns if c.startswith("rep_")), key=lambda c: int(c[4:]))
    wide = wide.with_columns([pl.col(c).fill_null(0).cast(pl.Int64) for c in sets])
    wide = wide.with_columns(pl.sum_horizontal(sets).cast(pl.Int64).alias("replicates_detected"))
    # Peptides quantified in no replicate carry no membership to draw.
    wide = wide.filter(pl.col("replicates_detected") > 0)
    return wide.select(["sample", "peptide", "replicates_detected", *sets]).sort(
        ["sample", "peptide"]
    )
