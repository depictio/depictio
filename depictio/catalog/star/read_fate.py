"""Where every input read went, per sample, from STAR's ``Log.final.out``.

The long companion of ``star/log_final``: one row per sample and fate, so a
stacked bar (or a composition card) splits each sample's input into uniquely
mapped, multi-mapped, mapped to too many loci and the three unmapped reasons.
The six shares are STAR's own percentages and sum to about 100 (chimeric reads
are counted inside the mapped ones, so they are not a fate of their own).

Input: every ``*.Log.final.out`` under the run, one LINE per row, with the file
path in ``source_path``. Parsing in ``depictio.recipes.lib.star_logs``.

Output schema:
    sample : Utf8          STAR's file prefix, the samplesheet id
    fate : Utf8            Uniquely mapped, Multi-mapped, Too many loci,
                           Unmapped: too short, Unmapped: other,
                           Unmapped: too many mismatches
    fate_order : Int64     1 to 6, the order above (mapped first)
    reads : Int64          reads with that fate
    reads_pct : Float64    of the sample's input, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.star_logs import RAW_LINE_COL, SOURCE_PATH_COL, parse_log_final

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="logs",
        glob_pattern="**/*.Log.final.out",
        format="csv",
        read_kwargs={
            "separator": "\x1e",
            "has_header": False,
            "new_columns": [RAW_LINE_COL],
            "quote_char": None,
            "infer_schema_length": 0,
        },
        source_path=SOURCE_PATH_COL,
        input_schema={RAW_LINE_COL: pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "fate": pl.Utf8,
    "fate_order": pl.Int64,
    "reads": pl.Int64,
    "reads_pct": pl.Float64,
}

#: (label, count column, percent column), in the order the bar stacks them.
FATES: list[tuple[str, str, str]] = [
    ("Uniquely mapped", "uniquely_mapped", "uniquely_mapped_pct"),
    ("Multi-mapped", "multimapped", "multimapped_pct"),
    ("Too many loci", "too_many_loci", "too_many_loci_pct"),
    ("Unmapped: too short", "unmapped_too_short", "unmapped_too_short_pct"),
    ("Unmapped: other", "unmapped_other", "unmapped_other_pct"),
    ("Unmapped: too many mismatches", "unmapped_mismatches", "unmapped_mismatches_pct"),
]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt the six fates of every report into one row each."""
    logs = parse_log_final(sources["logs"])
    parts = [
        logs.select(
            "sample",
            pl.lit(label).alias("fate"),
            pl.lit(order, dtype=pl.Int64).alias("fate_order"),
            pl.col(count).cast(pl.Int64).alias("reads"),
            pl.col(pct).cast(pl.Float64).alias("reads_pct"),
        )
        for order, (label, count, pct) in enumerate(FATES, start=1)
    ]
    return (
        pl.concat(parts)
        .filter(pl.col("reads").is_not_null())
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "fate_order"])
    )
