"""Indel size distribution per library.

Sums the indel alleles of ``crisprseq_indels`` by signed size (insertions
positive, deletions and deletion-insertions negative) as a share of the
library's classified reads. Templated repair after a Cas9 cut favours a few
sizes (a 1 bp insertion, short microhomology deletions), so the shape of this
curve is a guide's repair signature. Sizes beyond the profile window are left
out.

Output:
    sample : Utf8          library id
    size : Int64           signed indel size, bp
    reads : Int64          indel reads of that size
    pct_reads : Float64    share of the library's classified reads, percent
    pct_indel_reads : Float64  share of the library's indel reads, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import indel_sizes_per_library

RAW_DC_TAG = "crisprseq_indels"
SOURCES: list[RecipeSource] = [RecipeSource(ref="indels", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "size": pl.Int64,
    "reads": pl.Int64,
    "pct_reads": pl.Float64,
    "pct_indel_reads": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    return indel_sizes_per_library(sources["indels"]).select(list(EXPECTED_SCHEMA))
