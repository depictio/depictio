"""The most expressed slice of the DESeq2 table, for the pinned reference tile.

A reference table rides every tab, so it is the one tile whose cost is paid
seven times. Pinning all 208 722 DESeq2 rows there meant an AG Grid with row
selection enabled over a collection two orders of magnitude larger than
anything a reader scrolls, on every tab, in a four-row-high tile.

This is the same table ranked by ``baseMean`` and cut to ``TOP_N``: the genes
the run actually measured well, which is what a reader reaches for when they
want to check a number against the plots. The full table stays available as
its own collection and is what the volcano, MA, QQ and barplot tiles read, so
nothing is hidden, only unpinned.

Schema is identical to ``deseq2_results.py`` (same helper), so the same
``use: deseq2/...`` renders bind to it.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bambu import DESEQ2_COLUMNS, contrast_label, deseq2_on_bambu

RAW_DC_TAG = "deseq2_results_raw"
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="raw", dc_ref=RAW_DC_TAG),
    RecipeSource(
        ref="samplesheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
        optional=True,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = dict(DESEQ2_COLUMNS)

#: Rows kept, ranked by mean normalised count.
TOP_N = 200


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Raw DESeq2 table -> its TOP_N best-measured rows."""
    return (
        deseq2_on_bambu(sources["raw"], contrast_label(sources.get("samplesheet")))
        .sort("base_mean", descending=True, nulls_last=True)
        .head(TOP_N)
    )
