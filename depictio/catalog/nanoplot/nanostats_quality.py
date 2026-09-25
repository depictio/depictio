"""The yield-above-quality-cutoff ladder of a NanoStat summary.

Every NanoStat report ends its summary block with a ladder::

    Number, percentage and megabases of reads above quality cutoffs
    >Q5:	2652647 (92.7%) 2217.7Mb
    >Q7:	2179721 (76.2%) 1896.9Mb
    >Q10:	783272 (27.4%) 766.2Mb

which is the single most useful long-read QC reading there is: it says how
much of a library survives the quality floor an analysis wants to impose,
before any of it is spent. A mean quality of 8.5 hides whether that is a tight
distribution around 8.5 or a bimodal one, and the ladder does not.

One row per sample and cutoff, so it plots as one curve per sample over an
ordered numeric axis. Reads the same raw scan as ``nanostats.py`` (see that
module for why the report is scanned line by line and how the sample id is
recovered).
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.nanoplot import RAW_LINE_COL, SOURCE_PATH_COL, sample_of_report

RAW_DC_TAG = "nanoplot_nanostats_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "q_cutoff": pl.Int64,
    "n_reads": pl.Float64,
    "pct_reads": pl.Float64,
    "megabases": pl.Float64,
}

#: `>Q10:	783272 (27.4%) 766.2Mb`, with the whitespace NanoPlot happens to use.
_LADDER = re.compile(
    r"^>Q(\d+):\s*([0-9]+)\s*\(([0-9.]+)%\)\s*([0-9.]+)\s*Mb",
    re.IGNORECASE,
)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """NanoStat text -> one row per (sample, quality cutoff)."""
    raw = sources["raw"]
    rows: list[dict[str, object]] = []

    for (path,), block in raw.group_by(SOURCE_PATH_COL, maintain_order=True):
        sample = sample_of_report(str(path))
        for line in block[RAW_LINE_COL].to_list():
            match = _LADDER.match(str(line or "").strip())
            if not match:
                continue
            rows.append(
                {
                    "sample": sample,
                    "q_cutoff": int(match.group(1)),
                    "n_reads": float(match.group(2)),
                    "pct_reads": float(match.group(3)),
                    "megabases": float(match.group(4)),
                }
            )

    if not rows:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    return (
        pl.DataFrame(rows)
        .with_columns(
            pl.col("sample").cast(pl.Utf8),
            pl.col("q_cutoff").cast(pl.Int64),
            pl.col("n_reads").cast(pl.Float64),
            pl.col("pct_reads").cast(pl.Float64),
            pl.col("megabases").cast(pl.Float64),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "q_cutoff"])
    )
