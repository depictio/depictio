"""Every number of an AGAT ``agat_sp_statistics.pl`` report, as a long table.

One row per assembly, feature type, isoform view and metric, in the order AGAT
prints them (``metric_order``). The ``longest`` view repeats a feature type
with one transcript per gene, the longest, and exists only for types with
isoforms. The parsing lives in ``depictio.recipes.lib.agat_stats``.

Input: every ``*.stats.txt`` under the run, one line per row, with its path in
``source_path`` (the assembly is the file name without ``.stats.txt``). A file
without AGAT's section rules is not an AGAT report and contributes nothing.

Output schema:
    genome : Utf8          assembly, from the file name
    feature_type : Utf8    the block: mrna, lnc_rna, trna, region...
    isoforms : Utf8        all, or longest (one transcript per gene)
    metric : Utf8          AGAT's wording ("Number of gene", "mean exon length (bp)")
    value : Float64        its value; null where AGAT printed na
    metric_order : Int64   rank of the metric in its block, as printed
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.agat_stats import (
    LONG_SCHEMA,
    RAW_LINE_COL,
    READ_KWARGS,
    SOURCE_PATH_COL,
    parse_reports,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reports",
        glob_pattern="**/*.stats.txt",
        format="csv",
        read_kwargs=READ_KWARGS,
        source_path=SOURCE_PATH_COL,
        input_schema={RAW_LINE_COL: pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = dict(LONG_SCHEMA)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse every report; fail when none of the files was an AGAT report."""
    out = parse_reports(sources["reports"])
    if out.is_empty():
        raise ValueError("agat_statistics: no AGAT statistics block in the matched files")
    return out.select(list(OUTPUT_SCHEMA))
