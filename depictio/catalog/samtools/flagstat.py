"""One row per (sample, filter stage) from a `samtools flagstat` report.

`samtools flagstat` writes twelve fixed-label lines
(`<pass> + <fail> <category> [(<pct>% : <pct>%)]`) and never names the sample or
the stage it ran at inside the file, both live only in the path: a directory
that differs per stage (`samtools/stats/` before a mapping-quality filter,
`samtools/filtered_stats/` after it, in the run this recipe was written
against) and a filename suffix (`_flagstat.stats` / `_postfilterflagstat.stats`).
So this recipe is the raw-scan-plus-`dc_ref` idiom `preseq/complexity_curve.py`
documents: the DC declared under `RAW_DC_TAG` reads every matched file one LINE
per row (`separator` set to a byte flagstat text cannot contain, so nothing
splits) with `include_file_paths: source_path`, and only here, with the path in
hand, does parsing happen.

Input: the `samtools_flagstat_raw` data collection, declared by the template as::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*flagstat\\.stats$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\x1f"
          has_header: false
          new_columns: ["raw"]
          include_file_paths: "source_path"
          infer_schema_length: 0

Output schema:
    sample : Utf8                     library the report was written for
    stage : Utf8                      "pre-filter" or "post-filter"
    total_reads : Int64                QC-passed + QC-failed reads
    mapped_reads : Int64                reads flagged mapped
    mapped_pct : Float64                mapped / total, as flagstat reports it (nullable: N/A on an empty report)
    duplicate_reads : Int64             reads flagged duplicate
    properly_paired_reads : Int64       reads in a properly paired pair
    properly_paired_pct : Float64       properly paired / total (nullable: N/A)
    singleton_pct : Float64             singletons / total (nullable: N/A)
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan the raw reports into (see module
#: docstring). Any pipeline reusing this recipe declares a DC with this tag.
RAW_DC_TAG = "samtools_flagstat_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lines", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "stage": pl.Utf8,
    "total_reads": pl.Int64,
    "mapped_reads": pl.Int64,
    "mapped_pct": pl.Float64,
    "duplicate_reads": pl.Int64,
    "properly_paired_reads": pl.Int64,
    "properly_paired_pct": pl.Float64,
    "singleton_pct": pl.Float64,
}

SOURCE_PATH_COL = "source_path"

# `<sample>_flagstat.stats` (pre-filter) or `<sample>_postfilterflagstat.stats`
# (post-filter), the naming convention of the run this recipe was written
# against. A pipeline with a different suffix repoints the DC's scan regex; the
# stem still has to end in `flagstat` for this pattern to resolve the sample.
_STEM_RE = re.compile(r"^(?P<sample>.+?)_(?:post ?filter)?flagstat$", re.IGNORECASE)


def _int(text: str, pattern: str) -> int:
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        raise ValueError(f"samtools_flagstat: pattern not found: {pattern!r}")
    return int(m.group(1))


def _pct_value(raw: str) -> float | None:
    """flagstat prints either `12.34%` or a bare `N/A` in the pct slot."""
    return None if raw == "N/A" else float(raw.rstrip("%"))


def _pct(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        raise ValueError(f"samtools_flagstat: pattern not found: {pattern!r}")
    return _pct_value(m.group(1))


# The pct slot is `<float>%` when the denominator is nonzero, or a bare `N/A`
# (no `%`) when it is not, flagstat never prints `N/A%`.
_PCT_TOKEN = r"([\d.]+%|N/A)"


def _parse_report(source_path: str, text: str) -> dict:
    stem = Path(source_path).stem  # "<x>_flagstat" or "<x>_postfilterflagstat"
    match = _STEM_RE.match(stem)
    sample = match.group("sample") if match else stem
    stage = "post-filter" if "postfilter" in stem.lower() else "pre-filter"

    mapped = re.search(rf"^(\d+) \+ \d+ mapped \({_PCT_TOKEN}", text, re.MULTILINE)
    if not mapped:
        raise ValueError(f"samtools_flagstat: no 'mapped' line in {source_path}")
    properly = re.search(rf"^(\d+) \+ \d+ properly paired \({_PCT_TOKEN}", text, re.MULTILINE)
    if not properly:
        raise ValueError(f"samtools_flagstat: no 'properly paired' line in {source_path}")

    return {
        "sample": sample,
        "stage": stage,
        "total_reads": _int(text, r"^(\d+) \+ \d+ in total"),
        "mapped_reads": int(mapped.group(1)),
        "mapped_pct": _pct_value(mapped.group(2)),
        "duplicate_reads": _int(text, r"^(\d+) \+ \d+ duplicates"),
        "properly_paired_reads": int(properly.group(1)),
        "properly_paired_pct": _pct_value(properly.group(2)),
        "singleton_pct": _pct(text, rf"^\d+ \+ \d+ singletons \({_PCT_TOKEN}"),
    }


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Reassemble every matched flagstat report from its lines and parse it."""
    raw = sources["lines"]
    if raw.is_empty():
        raise ValueError("samtools_flagstat: the scanned reports are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "samtools_flagstat: no source_path column, the DC must scan with "
            "include_file_paths: source_path"
        )

    records = [
        _parse_report(str(path), "\n".join(line or "" for line in group["raw"].to_list()))
        for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True)
    ]
    if not records:
        raise ValueError("samtools_flagstat: no report parsed")

    return pl.DataFrame(records, schema=EXPECTED_SCHEMA).sort(["sample", "stage"])
