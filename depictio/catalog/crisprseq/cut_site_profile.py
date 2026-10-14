"""Where indels fall around the cut site, per library.

From the indel alleles of ``crisprseq_indels``: at every position within the
profile window of the cut site, the share of the library's classified reads
whose deletion covers that position (a deletion of length L starting at offset
o covers o to o + L - 1) and the share with an insertion starting there. A
Cas9 cut shows as a deletion peak straddling offset 0; a peak elsewhere points
at a misplaced cut site, a second site or amplicon-end artefacts. Positions
with no indel are left out.

Output:
    sample : Utf8              library id
    offset : Int64             position minus the cut site, bp
    deletion_pct : Float64     reads with a deletion covering the position, percent
    insertion_pct : Float64    reads with an insertion starting there, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import cut_site_per_library

RAW_DC_TAG = "crisprseq_indels"
# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="indels",
        dc_ref=RAW_DC_TAG,
        input_schema={
            "sample": pl.Utf8,
            "indel_type": pl.Utf8,
            "offset": pl.Int64,
            "length": pl.Int64,
            "pct_reads": pl.Float64,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "offset": pl.Int64,
    "deletion_pct": pl.Float64,
    "insertion_pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    return cut_site_per_library(sources["indels"]).select(list(OUTPUT_SCHEMA))
