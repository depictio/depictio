"""CCS yield per library: how many ZMWs went in and how many became HiFi reads.

``ccs`` writes one ``<prefix>.report.json`` (pbcopper report, id
``ccs_processing``) per run, and a chunked run writes one per chunk
(``<prefix>.chunk<N>.report.json``). This recipe sums the chunks back into one
row per library, so the first number of a PacBio run, the share of ZMWs that
passed every CCS filter, reads per library rather than per compute chunk.

Sample ids. The library is the file prefix without the chunk suffix. nf-core/isoseq
prefixes every samplesheet row ``<sample>_<N>`` (N the 0-based row number, so two
SMRT cells of one sample stay apart); ``sample`` drops that trailing row counter,
the same rule the pipeline applies before TAMA merge. A prefix without it is its
own sample.

The source scans every ``*.report.json`` under the run one line per row and
keeps only the CCS reports (``"id": "ccs_processing"``), so other pbcopper
reports next to them (isoseq refine's ``*.filter_summary.report.json``) are
ignored.

Output schema (one row per library):
    sample : Utf8              sample the library belongs to
    library : Utf8             samplesheet row / SMRT cell prefix
    chunks : Int64             CCS chunks summed
    zmw_input : Int64          ZMWs read from the subreads
    zmw_passed : Int64         ZMWs that produced a CCS read
    zmw_filtered : Int64       ZMWs removed by any filter
    pct_passed : Float64       zmw_passed over zmw_input, percent (2 decimals)
    too_few_passes : Int64     removed for lacking full passes
    poor_snr : Int64           removed below the SNR threshold
    draft_failures : Int64     removed while drafting (failure, too different, coverage, length)
    other_filtered : Int64     removed for any other reason
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
    "chunks": pl.Int64,
    "zmw_input": pl.Int64,
    "zmw_passed": pl.Int64,
    "zmw_filtered": pl.Int64,
    "pct_passed": pl.Float64,
    "too_few_passes": pl.Int64,
    "poor_snr": pl.Int64,
    "draft_failures": pl.Int64,
    "other_filtered": pl.Int64,
}

_PREFIX = "ccs_processing."
_CHUNK = re.compile(r"\.chunk\.?\d+$")
_ROW = re.compile(r"_\d+$")


def library_of(path: str, suffix: str) -> str:
    """File prefix without directory, ``suffix`` and chunk number."""
    base = path.rstrip("/").split("/")[-1]
    if base.endswith(suffix):
        base = base[: -len(suffix)]
    return _CHUNK.sub("", base)


def sample_of(library: str) -> str:
    """The sample a library belongs to (nf-core/isoseq's ``_<row>`` suffix dropped)."""
    return _ROW.sub("", library) or library


def ccs_reports(raw: pl.DataFrame) -> list[tuple[str, dict[str, int]]]:
    """(source path, {attribute id: value}) for every CCS report in the scan."""
    out: list[tuple[str, dict[str, int]]] = []
    for (path,), group in raw.group_by(["source_path"], maintain_order=True):
        text = "\n".join(line or "" for line in group["raw"].to_list())
        try:
            report = json.loads(text)
        except json.JSONDecodeError:
            continue
        if report.get("id") != "ccs_processing":
            continue
        values = {
            str(a.get("id", "")).removeprefix(_PREFIX): int(a.get("value") or 0)
            for a in report.get("attributes") or []
            if isinstance(a.get("value"), int | float)
        }
        out.append((str(path), values))
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    rows = []
    for path, v in ccs_reports(sources["reports"]):
        filtered = v.get("zmw_filtered_yield", 0)
        few = v.get("zmw_filtered_too_few_passes", 0)
        snr = v.get("zmw_filtered_poor_snr", 0)
        draft = sum(
            n
            for k, n in v.items()
            if k.startswith("zmw_filtered_draft_") or k == "zmw_filtered_insufficient_draft_cov"
        )
        library = library_of(path, ".report.json")
        rows.append(
            {
                "sample": sample_of(library),
                "library": library,
                "chunks": 1,
                "zmw_input": v.get("zmw_input", 0),
                "zmw_passed": v.get("zmw_passed_yield", 0),
                "zmw_filtered": filtered,
                "too_few_passes": few,
                "poor_snr": snr,
                "draft_failures": draft,
                "other_filtered": max(filtered - few - snr - draft, 0),
            }
        )
    if not rows:
        raise ValueError("pbccs: no CCS report (id ccs_processing) among the scanned *.report.json")
    counts = [c for c in EXPECTED_SCHEMA if EXPECTED_SCHEMA[c] == pl.Int64]
    frame = pl.DataFrame(
        rows, schema={c: EXPECTED_SCHEMA[c] for c in ["sample", "library", *counts]}
    )
    out = frame.group_by("sample", "library").agg(pl.col(c).sum().cast(pl.Int64) for c in counts)
    return (
        out.with_columns(
            pl.when(pl.col("zmw_input") > 0)
            .then(pl.col("zmw_passed") * 100.0 / pl.col("zmw_input"))
            .otherwise(None)
            .cast(pl.Float64)
            .round(2)
            .alias("pct_passed")
        )
        .sort("sample", "library")
        .select(list(EXPECTED_SCHEMA))
    )
