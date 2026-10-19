"""Repeat classes and families of each assembly, from RepeatMasker's ``.tbl``.

One row per class line of the summary table, ranked so a composition bar can
stack the classes that partition the masked bases (``rank == 'Class'``: SINEs,
LINEs, LTR elements, Penelope, DNA transposons, rolling-circles, unclassified,
small RNA, satellites, simple repeats, low complexity) while the families under
them (``Family``) and the lines that add classes up (``Summary``: Retroelements,
Total interspersed repeats) stay apart. The parsing lives in
``depictio.recipes.lib.repeatmasker_tbl``.

Input: every ``*.tbl`` under the run, one line per row, with its path in
``source_path`` (the assembly is the file name without ``.tbl``).

Output schema:
    genome : Utf8          assembly, from the file name
    repeat_class : Utf8    class or family as RepeatMasker names it
    parent_class : Utf8    the line it sits under (null for a top line)
    rank : Utf8            Class, Family or Summary
    class_order : Int64    rank of the line in the table, as printed
    elements : Int64       elements masked (null on Total interspersed repeats)
    length_bp : Int64      bases they occupy
    genome_pct : Float64   their share of the assembly, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.repeatmasker_tbl import (
    CLASS_SCHEMA,
    RAW_LINE_COL,
    READ_KWARGS,
    SOURCE_PATH_COL,
    parse_classes,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="tables",
        glob_pattern="**/*.tbl",
        format="csv",
        read_kwargs=READ_KWARGS,
        source_path=SOURCE_PATH_COL,
        input_schema={RAW_LINE_COL: pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = dict(CLASS_SCHEMA)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    out = parse_classes(sources["tables"])
    if out.is_empty():
        raise ValueError("repeatmasker_repeat_classes: no class line in the RepeatMasker tables")
    return out.select(list(OUTPUT_SCHEMA)).sort(["genome", "class_order"])
