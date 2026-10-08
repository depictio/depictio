"""Helpers shared by the bcl2fastq Stats.json recipes.

bcl2fastq writes one ``Stats.json`` per run; the raw collection scans it one line
per row. Rebuilding the reports, walking their lanes and summing read quality are
the same for every bcl2fastq recipe, and recipes may not import each other, so
they live here.
"""

from __future__ import annotations

import json

import polars as pl

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"


def load_reports(raw: pl.DataFrame) -> list[dict]:
    """Rebuild each scanned ``Stats.json`` from its lines."""
    if raw.is_empty():
        raise ValueError("bcl2fastq: the scanned Stats.json reports are empty")
    for column in (RAW_LINE_COL, SOURCE_PATH_COL):
        if column not in raw.columns:
            raise ValueError(
                f"bcl2fastq: no {column} column, the collection must scan one line "
                f"per row with include_file_paths: source_path"
            )
    reports: list[dict] = []
    for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        text = "\n".join(line or "" for line in group[RAW_LINE_COL].to_list())
        try:
            reports.append(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ValueError(f"bcl2fastq: {path} is not valid JSON: {exc}") from exc
    return reports


def lanes(reports: list[dict]) -> list[tuple[str, dict]]:
    """(flowcell, lane entry) pairs, the first report of a lane winning."""
    seen: set[tuple[str, int]] = set()
    out: list[tuple[str, dict]] = []
    for report in reports:
        flowcell = str(report.get("Flowcell") or "")
        for lane in report.get("ConversionResults") or []:
            key = (flowcell, int(lane.get("LaneNumber", 0)))
            if key in seen:
                continue
            seen.add(key)
            out.append((flowcell, lane))
    return out


def quality(read_metrics: list[dict]) -> tuple[float, float | None, float | None]:
    """(yield in bases, percent at Q30 or above, mean Phred) over every read."""
    yield_bp = float(sum(m.get("Yield", 0) for m in read_metrics))
    q30 = float(sum(m.get("YieldQ30", 0) for m in read_metrics))
    qsum = float(sum(m.get("QualityScoreSum", 0) for m in read_metrics))
    if yield_bp <= 0:
        return 0.0, None, None
    return yield_bp, 100.0 * q30 / yield_bp, qsum / yield_bp
