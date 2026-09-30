"""Where every ZMW of a library went in CCS: passed, or the filter that removed it.

The companion of ``pbccs/zmw_yield``: the same ``*.report.json`` scan, but each
outcome of the CCS report becomes a row (``Passed`` plus every
``zmw_filtered_*`` attribute), summed over the chunks of a library and
expressed as a share of the ZMWs that went in, so the outcomes of a library
stack to 100 %. A run losing most ZMWs to ``Lacking full passes`` had short
movies or long inserts; a jump in ``Below SNR threshold`` or the draft
failures points at the chemistry or the polymerase. Filters that removed
nothing in any library are dropped. See ``pbccs/zmw_yield`` for how ``sample``
and ``library`` are derived.

Output schema (one row per library and outcome):
    sample : Utf8          sample the library belongs to
    library : Utf8         samplesheet row / SMRT cell prefix
    rank : Utf8            constant "CCS outcome" (the composition level)
    outcome : Utf8         "Passed" or the filter, as the CCS report names it
    zmws : Int64           ZMWs with that outcome
    pct_of_input : Float64 zmws over the library's input ZMWs, percent
"""

from __future__ import annotations

import json
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reports",
        glob_pattern="**/*.report.json",
        format="csv",
        read_kwargs={
            "separator": "\x1f",
            "quote_char": None,
            "has_header": False,
            "new_columns": ["raw"],
            "infer_schema_length": 0,
        },
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "library": pl.Utf8,
    "rank": pl.Utf8,
    "outcome": pl.Utf8,
    "zmws": pl.Int64,
    "pct_of_input": pl.Float64,
}

_CHUNK = re.compile(r"\.chunk\.?\d+$")
_FILTER = "ccs_processing.zmw_filtered_"
_INPUT = "__input__"
PASSED = "Passed"


def _library(path: str) -> str:
    base = path.rstrip("/").split("/")[-1].removesuffix(".report.json")
    return _CHUNK.sub("", base)


def _rows(library: str, attrs: list[dict]) -> list[dict]:
    rows = []
    for a in attrs:
        aid = str(a.get("id", ""))
        value = int(a.get("value") or 0)
        if aid == "ccs_processing.zmw_input":
            rows.append({"library": library, "outcome": _INPUT, "zmws": value})
        elif aid == "ccs_processing.zmw_passed_yield":
            rows.append({"library": library, "outcome": PASSED, "zmws": value})
        elif aid.startswith(_FILTER) and aid != _FILTER + "yield":
            rows.append({"library": library, "outcome": str(a.get("name") or aid), "zmws": value})
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["reports"]
    rows: list[dict] = []
    for (path,), group in raw.group_by(["source_path"], maintain_order=True):
        text = "\n".join(line or "" for line in group["raw"].to_list())
        try:
            report = json.loads(text)
        except json.JSONDecodeError:
            continue
        if report.get("id") != "ccs_processing":
            continue
        rows.extend(_rows(_library(str(path)), report.get("attributes") or []))
    if not rows:
        raise ValueError("pbccs: no CCS report (id ccs_processing) among the scanned *.report.json")
    frame = pl.DataFrame(rows, schema={"library": pl.Utf8, "outcome": pl.Utf8, "zmws": pl.Int64})
    summed = frame.group_by("library", "outcome").agg(pl.col("zmws").sum().cast(pl.Int64))
    inputs = summed.filter(pl.col("outcome") == _INPUT).select(
        "library", pl.col("zmws").alias("_input")
    )
    outcomes = summed.filter(pl.col("outcome") != _INPUT)
    used = (
        outcomes.group_by("outcome")
        .agg(pl.col("zmws").sum().alias("_all"))
        .filter((pl.col("_all") > 0) | (pl.col("outcome") == PASSED))
    )
    return (
        outcomes.join(used.select("outcome"), on="outcome", how="semi")
        .join(inputs, on="library", how="left")
        .with_columns(
            pl.col("library").str.replace(r"_\d+$", "").alias("sample"),
            pl.lit("CCS outcome").alias("rank"),
            pl.when(pl.col("_input") > 0)
            .then(pl.col("zmws") * 100.0 / pl.col("_input"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("pct_of_input"),
        )
        .sort("sample", "library", "zmws", descending=[False, False, True])
        .select(list(EXPECTED_SCHEMA))
    )
