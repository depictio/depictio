"""Per-position nucleotide substitution and gap rates around the cut site.

``cigar/<sample>_subs-perc.csv`` lists, for every amplicon position the CIGAR
parser inspected, the percentage of aligned reads carrying each base (and
``-`` for a gap). The dominant base at a position is taken as the reference;
the substitution rate is the share of reads carrying any other base, the gap
rate the share carrying ``-``. Positions are placed relative to the cut site
read from ``<sample>_cutSite.json`` and kept within the profile window. Base
editors show as a substitution peak a few bases upstream of the cut; nuclease
edits as a gap peak at it.

Output:
    sample : Utf8               library id
    offset : Int64              position minus the cut site, bp
    position : Int64            position on the amplicon
    reference_nt : Utf8         dominant base at the position
    substitution_pct : Float64  reads with another base, percent
    gap_pct : Float64           reads with a gap, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import substitutions_per_library

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="subs",
        glob_pattern="**/*_subs-perc.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", ""]},
        source_path="source_path",
    ),
    RecipeSource(
        ref="cut",
        glob_pattern="**/*_cutSite.json",
        format="csv",
        read_kwargs={"has_header": False, "new_columns": ["cut_site"], "infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "offset": pl.Int64,
    "position": pl.Int64,
    "reference_nt": pl.Utf8,
    "substitution_pct": pl.Float64,
    "gap_pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    return substitutions_per_library(sources["subs"], sources["cut"]).select(list(EXPECTED_SCHEMA))
