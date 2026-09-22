"""CpG M-bias curve, one row per sample x read x position.

``bismark_methylation_extractor --mbias_only`` writes one
``<sample>_bismark_bt2_pe.deduplicated.M-bias.txt`` per library: six
tab-separated tables in one file (CpG / CHG / CHH, each for read 1 and read
2), each row giving the % methylation and coverage observed at one read
position. A read-position bias that does not flatten out is Bismark's own
advice to add an `--ignore` / `--ignore_r2` trim before re-extracting.

MultiQC's own ``bismark_mbias`` panel draws the same curve per context/read,
but as a picture with no cross-tile selection; this recipe keeps the CpG
context (the context nf-core/methylseq's default human/mouse references
report on) queryable and linkable through `selection_column: sample`. CHG and
CHH are not extracted here, the MultiQC panel (`multiqc/bismark`, section
`bismark`) already surfaces those for the samples that need them.

Input: the ``bismark_mbias_raw`` data collection, a recursive Table scan of the
per-sample M-bias files read one LINE per row (six tables share one file with
no shared column count, so no single tabular read fits it, see
``alignment_summary.py``). The DC must be declared with::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*\\.M-bias\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "|"
          has_header: false
          new_columns: ["line"]
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8                library Bismark ran on
    read : Utf8                  R1 or R2
    series : Utf8                "<sample> <read>" (e.g. "S1 R1"), the profile kind's series role
    position : Int64             base position inside the read
    pct_methylation : Float64    % methylated calls at this position, CpG context
    coverage : Int64             calls (methylated + unmethylated) behind the percentage
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bismark_reports import parse_mbias, report_lines

RAW_DC_TAG = "bismark_mbias_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lines", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "read": pl.Utf8,
    "series": pl.Utf8,
    "position": pl.Int64,
    "pct_methylation": pl.Float64,
    "coverage": pl.Int64,
}

# `bismark_[a-z0-9]+`: the bismark_hisat route writes `_bismark_hisat2_`.
_SUFFIX_RE = re.compile(
    r"(_\d+)?(_val_\d+)?_bismark_[a-z0-9]+_(pe|se)(\.deduplicated)?\.M-bias\.txt$"
)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Re-assemble each M-bias file from its lines, keep the CpG sections."""
    rows: list[dict[str, object]] = []
    for sample, lines in report_lines(sources["lines"], "bismark_mbias_curve", _SUFFIX_RE):
        rows.extend(parse_mbias(sample, lines, contexts=("CpG",)))

    if not rows:
        raise ValueError("bismark_mbias_curve: no CpG row was parsed from any M-bias file")

    frame = pl.DataFrame(rows, infer_schema_length=None)
    return frame.select(
        pl.col("sample"),
        pl.col("read"),
        (pl.col("sample") + pl.lit(" ") + pl.col("read")).alias("series"),
        pl.col("position").cast(pl.Int64, strict=False),
        pl.col("pct_methylation").cast(pl.Float64, strict=False),
        pl.col("coverage").cast(pl.Int64, strict=False),
    ).sort(["sample", "read", "position"])
