"""NanoPlot's NanoStat summary, one row per sample.

``NanoStats.txt`` is not a table. It is a block of ``Key: value`` lines padded
to a column that moves between NanoPlot versions, then a yield ladder tagged
``>Q5:``, then two "top 5" blocks whose rows are all numbered ``1:`` to ``5:``
and can only be told apart by the heading above them::

    General summary:
    Mean read length:                   796.2
    Number of reads:              2,861,374.0
    Read length N50:                    919.0
    Number, percentage and megabases of reads above quality cutoffs
    >Q7:	2179721 (76.2%) 1896.9Mb
    Top 5 longest reads and their mean basecall quality score
    1:	16679 (5.5)

Nothing about that survives a CSV reader, so the raw DC scans it with a
separator that never occurs in the file (one whole line per row) plus
``include_file_paths``, and this recipe walks the lines itself, tracking which
heading it is under. The same two-step feeds ``nanostats_quality.py``, which
reads the ladder out of the same raw frame.

The sample id is not in the file: NanoPlot writes into a directory named after
the sample (``nanoplot/fastq/<sample>/NanoStats.txt``) or, on other pipelines,
a file named after it (``<sample>_NanoStats.txt``). Both spellings are read,
the file name first.

Output: one row per sample, read-length and read-quality summaries plus the
two extremes, with ``total_gigabases`` derived so a yield card has a unit a
reader recognises.
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
    "n_reads": pl.Float64,
    "total_bases": pl.Float64,
    "total_gigabases": pl.Float64,
    "mean_read_length": pl.Float64,
    "median_read_length": pl.Float64,
    "read_length_n50": pl.Float64,
    "stdev_read_length": pl.Float64,
    "mean_read_quality": pl.Float64,
    "median_read_quality": pl.Float64,
    "longest_read_length": pl.Float64,
    "top_read_quality": pl.Float64,
}

#: NanoStat key (lower-cased, colon stripped) -> output column.
_KEY_MAP: dict[str, str] = {
    "number of reads": "n_reads",
    "total bases": "total_bases",
    "mean read length": "mean_read_length",
    "median read length": "median_read_length",
    "read length n50": "read_length_n50",
    "stdev read length": "stdev_read_length",
    "mean read quality": "mean_read_quality",
    "median read quality": "median_read_quality",
}

_LONGEST_HEADING = "top 5 longest reads"
_QUALITY_HEADING = "top 5 highest mean basecall quality"
_RANKED_LINE = re.compile(r"^\s*1:\s*([0-9.]+)")


def _number(text: str) -> float | None:
    """A NanoStat value: thousands separators, a trailing unit, or neither."""
    cleaned = text.replace(",", "").strip()
    match = re.match(r"^-?[0-9]*\.?[0-9]+", cleaned)
    return float(match.group(0)) if match else None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Free-form NanoStat text -> one tidy row per sample."""
    raw = sources["raw"]
    rows: list[dict[str, object]] = []

    for (path,), block in raw.group_by(SOURCE_PATH_COL, maintain_order=True):
        record: dict[str, object] = {"sample": sample_of_report(str(path))}
        heading = ""
        for line in block[RAW_LINE_COL].to_list():
            text = str(line or "")
            lowered = text.strip().lower()
            if lowered.startswith(_LONGEST_HEADING):
                heading = "longest"
                continue
            if lowered.startswith(_QUALITY_HEADING):
                heading = "quality"
                continue
            ranked = _RANKED_LINE.match(text)
            if ranked and heading:
                column = "longest_read_length" if heading == "longest" else "top_read_quality"
                record.setdefault(column, float(ranked.group(1)))
                continue
            if ":" not in text or text.strip().startswith(">Q"):
                continue
            key, _, value = text.partition(":")
            column = _KEY_MAP.get(key.strip().lower())
            if column:
                record[column] = _number(value)
        rows.append(record)

    # `infer_schema_length=None`: a key first seen after the 100th report is
    # still a column, not silently dropped.
    frame = pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame({"sample": []})
    for column, dtype in EXPECTED_SCHEMA.items():
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=dtype).alias(column))
    frame = frame.with_columns(
        pl.col("sample").cast(pl.Utf8),
        *[pl.col(c).cast(pl.Float64, strict=False) for c in EXPECTED_SCHEMA if c != "sample"],
    ).with_columns((pl.col("total_bases") / 1e9).alias("total_gigabases"))
    return frame.select(list(EXPECTED_SCHEMA)).sort("sample")
