"""Indel position profile around the cut site per guide: median library and interquartile band.

At every offset of the profile window, the median, first and third quartile
over each guide's libraries of the share of reads whose deletion covers the
position and of the share with an insertion starting there. A library without
an indel at an offset counts as zero. The per-library profiles are derived from
the indel alleles (``crisprseq_indels``) in process, so no table with one row
per library and offset is shipped.

Output:
    guide : Utf8                       protospacer
    offset : Int64                     position minus the cut site, bp
    median_deletion_pct : Float64      median share of reads with a deletion covering it
    q1_deletion_pct, q3_deletion_pct   its first and third quartile
    median_insertion_pct : Float64     median share of reads with an insertion starting there
    q1_insertion_pct, q3_insertion_pct its first and third quartile
    libraries_with_signal : Int64      libraries with an indel at that offset
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import (
    PROFILE_WINDOW,
    cut_site_per_library,
    guide_quartiles,
    library_guides,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref="samples"),
    RecipeSource(ref="summary", dc_ref="crisprseq_edit_summary"),
    RecipeSource(ref="indels", dc_ref="crisprseq_indels"),
]

_VALUES = ["deletion_pct", "insertion_pct"]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "guide": pl.Utf8,
    "offset": pl.Int64,
    **{f"{s}_{v}": pl.Float64 for v in _VALUES for s in ("median", "q1", "q3")},
    "libraries_with_signal": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    libs = library_guides(sources["samples"], sources["summary"])
    profile = cut_site_per_library(sources["indels"])
    offsets = pl.DataFrame(
        {"offset": list(range(-PROFILE_WINDOW, PROFILE_WINDOW + 1))}, schema={"offset": pl.Int64}
    )
    keys = libs.select("guide").unique().join(offsets, how="cross")
    out = guide_quartiles(profile, libs, "offset", _VALUES, fill_zero=True, keys=keys)
    return out.select(list(EXPECTED_SCHEMA))
