"""CheckQC verdicts per lane: which run-level thresholds the run failed, and by how much.

nf-core/demultiplex runs CheckQC on every flowcell and publishes
``checkqc_report.json``: one list of findings per handler that fired, plus a
``run_summary`` naming every handler it ran with its thresholds::

    {"exit_status": 1,
     "ReadsPerSampleHandler": [{"type": "error", "message": "...",
                                "data": {"lane": 1, "sample_name": "S7",
                                         "sample_reads": 0.000193, "threshold": 0.75}}],
     "UnidentifiedIndexHandler": [{"type": "error", "data": {"lane": 1,
                                   "msg": "Index: AAGAGGCA+CGTCTAAT on lane: 1 was
                                           significantly overrepresented (5.3%) ..."}}],
     "run_summary": {"instrument_and_reagent_type": "miseq_v3",
                     "handlers": [{"name": "Q30Handler", "warning": 80, "error": "unknown"}, ...]}}

One row per finding, and one ``pass`` row for each handler of the run summary
that reported nothing, so the table lists every check the run went through
rather than only the ones it failed. ``value`` is the measured number of the
finding (reads in millions, a percentage) and ``threshold`` the limit it was
held to; ``index`` is set on the unidentified-index findings.

Read one LINE per row (the text-scan idiom, ``quote_char: null``).

Output schema:
    report : Utf8          run folder the report sits in (lane folders skipped)
    handler : Utf8         CheckQC handler, "Handler" suffix dropped
    severity : Utf8        "error", "warning" or "pass"
    lane : Int64           lane of the finding, null on a pass row
    sample : Utf8          library of a per-sample finding
    index : Utf8           index pair of an unidentified-index finding
    value : Float64        measured number
    threshold : Float64    limit it was held to
    message : Utf8         CheckQC's own sentence
    instrument : Utf8      instrument and reagent type CheckQC resolved
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan ``checkqc_report.json`` into.
RAW_DC_TAG = "checkqc_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="reports", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "report": pl.Utf8,
    "handler": pl.Utf8,
    "severity": pl.Utf8,
    "lane": pl.Int64,
    "sample": pl.Utf8,
    "index": pl.Utf8,
    "value": pl.Float64,
    "threshold": pl.Float64,
    "message": pl.Utf8,
    "instrument": pl.Utf8,
}

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"

#: Keys of a finding's ``data`` that are context, not the measured value.
_CONTEXT_KEYS = frozenset(
    {"lane", "threshold", "computed_threshold", "number_of_samples", "read", "msg", "sample_name"}
)
_INDEX_MSG = re.compile(r"Index:\s*(?P<index>\S+)\s+on lane:\s*\d+.*?\((?P<pct>[\d.]+)%\)")


def _report_name(path: str) -> str:
    parts = PurePosixPath(str(path).replace("\\", "/")).parts[:-1]
    parts = tuple(p for p in parts if not re.fullmatch(r"L\d{3}", p))
    return parts[-1] if parts else ""


def _num(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _finding(report: str, handler: str, item: dict, instrument: str) -> dict:
    data = item.get("data") or {}
    message = str(item.get("message") or data.get("msg") or "")
    index = None
    value = None
    match = _INDEX_MSG.search(message)
    if match:
        index, value = match.group("index"), _num(match.group("pct"))
    if value is None:
        value = next(
            (_num(v) for k, v in data.items() if k not in _CONTEXT_KEYS and _num(v) is not None),
            None,
        )
    lane = data.get("lane")
    return {
        "report": report,
        "handler": handler.removesuffix("Handler"),
        "severity": str(item.get("type") or "error"),
        "lane": int(lane) if lane is not None else None,
        "sample": data.get("sample_name"),
        "index": index,
        "value": value,
        "threshold": _num(data.get("threshold")),
        "message": message,
        "instrument": instrument,
    }


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per finding plus one pass row per silent handler."""
    raw = sources["reports"]
    if raw is None or raw.is_empty():
        raise ValueError("checkqc_verdicts: the scanned CheckQC reports are empty")
    rows: list[dict] = []
    for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        text = "\n".join(line or "" for line in group[RAW_LINE_COL].to_list())
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"checkqc_verdicts: {path} is not valid JSON: {exc}") from exc
        report = _report_name(path)
        summary = payload.get("run_summary") or {}
        instrument = str(summary.get("instrument_and_reagent_type") or "")
        fired: set[str] = set()
        for handler, items in payload.items():
            if not handler.endswith("Handler") or not isinstance(items, list):
                continue
            fired.add(handler)
            rows.extend(_finding(report, handler, item, instrument) for item in items)
        for spec in summary.get("handlers") or []:
            name = str(spec.get("name") or "")
            if name and name not in fired:
                rows.append(
                    {
                        "report": report,
                        "handler": name.removesuffix("Handler"),
                        "severity": "pass",
                        "lane": None,
                        "sample": None,
                        "index": None,
                        "value": None,
                        "threshold": _num(spec.get("error")) or _num(spec.get("warning")),
                        "message": "No finding",
                        "instrument": instrument,
                    }
                )
    if not rows:
        raise ValueError("checkqc_verdicts: no handler in the scanned reports")
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(
        ["report", "severity", "handler", "lane"]
    )
