"""M-bias in all three cytosine contexts, read 1 and read 2, one long frame.

``bismark_mbias_curve`` keeps the CpG sections of the M-bias file because a
single ``profile`` tile can only draw one set of curves and CpG is the one a
mammalian run is about. That leaves four of the file's six tables unread, and
they are not redundant: the CHH curve is the read-position view of the
bisulfite conversion rate, so a CHH panel that climbs at the 5' end says the
first bases of the read are not converting, which the CpG panel cannot tell you
and which a run-level conversion percentage averages away.

This output keeps all six tables and puts the context and the read in columns,
so one tile plus two small filters replaces six tiles. ``series`` is
pre-composed as ``<sample> <context> R<n>`` because ``profile`` splits curves on
a single column, and the curve a reader wants is one per library per panel once
the context and read filters have narrowed the frame.

Separate from ``mbias_curve.py`` rather than replacing it: that output's CpG-only
schema is seeded into the catalog-conformance project, and a bisulfite dashboard
wants both a plain CpG tile and a context explorer. The parser is duplicated
rather than shared because recipes cannot import one another; it is twenty lines
and the file format is Bismark's, which has not changed in a decade.

Input: the ``bismark_mbias_raw`` data collection (see ``mbias_curve.py`` for the
scan that builds it, one text line per row with ``include_file_paths``).

Output schema:
    sample : Utf8                library Bismark ran on
    context : Utf8               CpG, CHG or CHH
    read : Utf8                  R1 or R2
    series : Utf8                "<sample> <context> R<n>", the profile's series
    position : Int64             base position inside the read
    pct_methylation : Float64    % methylated calls at this position
    coverage : Int64             calls (methylated + unmethylated) behind it
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
    "context": pl.Utf8,
    "read": pl.Utf8,
    "series": pl.Utf8,
    "position": pl.Int64,
    "pct_methylation": pl.Float64,
    "coverage": pl.Int64,
}

# `bismark_[a-z0-9]+` rather than `bismark_bt2`, so the hisat2 route strips too.
_SUFFIX_RE = re.compile(
    r"(_\d+)?(_val_\d+)?_bismark_[a-z0-9]+_(pe|se)(\.deduplicated)?\.M-bias\.txt$", re.IGNORECASE
)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Re-assemble each M-bias file from its lines, keep all six sections."""
    rows: list[dict[str, object]] = []
    for sample, lines in report_lines(sources["lines"], "bismark_mbias_all_contexts", _SUFFIX_RE):
        rows.extend(parse_mbias(sample, lines))
    if not rows:
        raise ValueError("bismark_mbias_all_contexts: no row was parsed from any M-bias file")

    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .select(
            pl.col("sample").cast(pl.Utf8),
            pl.col("context").cast(pl.Utf8),
            pl.col("read").cast(pl.Utf8),
            (pl.col("sample") + pl.lit(" ") + pl.col("context") + pl.lit(" ") + pl.col("read"))
            .cast(pl.Utf8)
            .alias("series"),
            pl.col("position").cast(pl.Int64, strict=False),
            pl.col("pct_methylation").cast(pl.Float64, strict=False),
            pl.col("coverage").cast(pl.Int64, strict=False),
        )
        .sort(["sample", "context", "read", "position"])
    )
