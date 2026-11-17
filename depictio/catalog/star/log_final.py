"""One row per sample from STAR's ``Log.final.out``.

STAR writes its read fate and error rates as a key/value list; this recipe
reads every key MultiQC reads and the splice counts it does not keep, then
derives three shares the dashboard cards read:

* ``mapped_pct``: uniquely plus multi-mapped reads, in percent of the input;
* ``splices_annotated_pct``: splices on a junction the annotation (sjdb)
  already holds, in percent of all splices, which falls when a sample is
  degraded, contaminated or simply off the annotation;
* ``splices_noncanonical_pct``: splices on a non-canonical motif, the share an
  alignment artefact or a mis-set ``--outSJfilter*`` inflates.

A share whose denominator is zero (a sample with no splice at all) is null,
never 0. The parsing lives in ``depictio.recipes.lib.star_logs``.

Input: every ``*.Log.final.out`` under the run, one LINE per row (a separator
the report cannot contain), with the file path in ``source_path``.

Output schema:
    sample : Utf8                    STAR's file prefix, the samplesheet id
    input_reads : Int64              reads STAR was given
    avg_input_read_length : Float64  their mean length (both mates of a pair)
    uniquely_mapped : Int64          reads placed at one locus
    uniquely_mapped_pct : Float64    of the input, percent
    multimapped : Int64              reads placed at 2 to --outFilterMultimapNmax loci
    multimapped_pct : Float64        of the input, percent
    too_many_loci_pct : Float64      reads past that limit, percent
    unmapped_pct : Float64           too many mismatches + too short + other, percent
    mapped_pct : Float64             uniquely + multi-mapped, percent
    avg_mapped_length : Float64      mean aligned length of a uniquely mapped read
    splices_total : Int64            splices crossed by uniquely mapped reads
    splices_annotated : Int64        of which on an annotated junction
    splices_annotated_pct : Float64  their share, percent; null without splices
    splices_noncanonical : Int64     splices on a non-canonical motif
    splices_noncanonical_pct : Float64  their share, percent; null without splices
    mismatch_rate_pct : Float64      mismatches per aligned base, percent
    deletion_rate_pct : Float64      deletions per aligned base, percent
    insertion_rate_pct : Float64     insertions per aligned base, percent
    chimeric_pct : Float64           chimeric reads, percent (0 unless chimeric output is on)
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
    "input_reads": pl.Int64,
    "avg_input_read_length": pl.Float64,
    "uniquely_mapped": pl.Int64,
    "uniquely_mapped_pct": pl.Float64,
    "multimapped": pl.Int64,
    "multimapped_pct": pl.Float64,
    "too_many_loci_pct": pl.Float64,
    "unmapped_pct": pl.Float64,
    "mapped_pct": pl.Float64,
    "avg_mapped_length": pl.Float64,
    "splices_total": pl.Int64,
    "splices_annotated": pl.Int64,
    "splices_annotated_pct": pl.Float64,
    "splices_noncanonical": pl.Int64,
    "splices_noncanonical_pct": pl.Float64,
    "mismatch_rate_pct": pl.Float64,
    "deletion_rate_pct": pl.Float64,
    "insertion_rate_pct": pl.Float64,
    "chimeric_pct": pl.Float64,
}


def _share(num: str, den: str) -> pl.Expr:
    return (
        pl.when(pl.col(den) > 0)
        .then(pl.col(num).cast(pl.Float64) * 100.0 / pl.col(den).cast(pl.Float64))
        .otherwise(None)
        .round(2)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Parse every report and derive the mapped, annotated and non-canonical shares."""
    logs = parse_log_final(sources["logs"])
    unmapped = ["unmapped_mismatches_pct", "unmapped_too_short_pct", "unmapped_other_pct"]
    return (
        logs.with_columns(
            pl.sum_horizontal([pl.col(c).fill_null(0.0) for c in unmapped])
            .round(2)
            .alias("unmapped_pct"),
            (pl.col("uniquely_mapped_pct") + pl.col("multimapped_pct"))
            .round(2)
            .alias("mapped_pct"),
            _share("splices_annotated", "splices_total").alias("splices_annotated_pct"),
            _share("splices_noncanonical", "splices_total").alias("splices_noncanonical_pct"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort("sample")
    )
