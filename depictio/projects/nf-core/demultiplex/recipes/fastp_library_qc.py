"""Per-library read QC after demultiplexing, from the fastp JSON reports.

nf-core/demultiplex runs fastp on every demultiplexed FASTQ pair (adapter and
quality trimming) and publishes one ``<sample>_S<n>_L<lane>.fastp.json`` per
library and lane. This recipe keeps the numbers that say whether a library is
worth sending on: how many reads survived, how duplicated it is, how much
adapter it carried, its GC content and base quality before and after.

The library name and lane come from the Illumina FASTQ file name
(``<sample>_S<n>_L<lane>``), the naming bcl2fastq and BCL Convert both use; a
report whose name does not follow it keeps its stem as the library name and a
null lane. ``fastq_id`` keeps the stem, the name MultiQC gives the fastp and
Falco rows of the library.

fastp counts both mates of a pair, so ``reads_before`` is twice the read pairs
bcl2fastq assigned.

Output schema:
    sample : Utf8                 library name
    lane : Int64                  lane, null when the file name carries none
    lane_label : Utf8             "Lane <n>", or "All lanes"
    fastq_id : Utf8               FASTQ stem, the MultiQC sample name of the report
    reads_before : Int64          reads fastp was given (both mates)
    reads_after : Int64           reads it kept
    pct_passed : Float64          reads kept, percent
    pct_low_quality : Float64     reads dropped for low quality, percent
    pct_too_many_n : Float64      reads dropped for too many N, percent
    pct_too_short : Float64       reads dropped as too short after trimming, percent
    pct_duplication : Float64     duplication rate fastp estimated, percent
    pct_adapter_trimmed : Float64 reads with adapter trimmed, percent
    gc_pct : Float64              GC content after filtering, percent
    pct_q30_before : Float64      bases at Q30 or above before filtering, percent
    pct_q30_after : Float64       the same after filtering, percent
    mean_length_after : Float64   mean read 1 length after trimming, bp
    insert_size_peak : Int64      most frequent insert size, bp (paired runs)
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan ``*.fastp.json`` into, one line per row.
RAW_DC_TAG = "fastp_json_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="reports", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "lane": pl.Int64,
    "lane_label": pl.Utf8,
    "fastq_id": pl.Utf8,
    "reads_before": pl.Int64,
    "reads_after": pl.Int64,
    "pct_passed": pl.Float64,
    "pct_low_quality": pl.Float64,
    "pct_too_many_n": pl.Float64,
    "pct_too_short": pl.Float64,
    "pct_duplication": pl.Float64,
    "pct_adapter_trimmed": pl.Float64,
    "gc_pct": pl.Float64,
    "pct_q30_before": pl.Float64,
    "pct_q30_after": pl.Float64,
    "mean_length_after": pl.Float64,
    "insert_size_peak": pl.Int64,
}

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"
#: Illumina FASTQ naming: <sample>_S<n>[_L<lane>], the stem fastp names its report after.
_FASTQ_STEM = re.compile(r"^(?P<sample>.+?)_S\d+(?:_L(?P<lane>\d{3}))?$")


def _load_reports(raw: pl.DataFrame, who: str) -> list[tuple[str, dict]]:
    """(file stem, parsed report) for every scanned ``*.fastp.json``."""
    if raw is None or raw.is_empty():
        raise ValueError(f"{who}: the scanned fastp reports are empty")
    for column in (RAW_LINE_COL, SOURCE_PATH_COL):
        if column not in raw.columns:
            raise ValueError(
                f"{who}: no {column} column, the collection must scan one line per row "
                f"with include_file_paths: source_path"
            )
    out: list[tuple[str, dict]] = []
    for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        text = "\n".join(line or "" for line in group[RAW_LINE_COL].to_list())
        try:
            report = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{who}: {path} is not valid JSON: {exc}") from exc
        name = PurePosixPath(str(path).replace("\\", "/")).name
        out.append((name.removesuffix(".json").removesuffix(".fastp"), report))
    return out


def _sample_lane(stem: str) -> tuple[str, int | None]:
    """Library name and lane of a FASTQ stem; the stem itself when it is not Illumina-named."""
    match = _FASTQ_STEM.match(stem)
    if not match:
        return stem, None
    lane = match.group("lane")
    return match.group("sample"), int(lane) if lane else None


def _pct(part: float | int | None, whole: float | int | None) -> float | None:
    if part is None or not whole:
        return None
    return 100.0 * float(part) / float(whole)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per fastp report, that is per (library, lane)."""
    rows: list[dict] = []
    for stem, report in _load_reports(sources["reports"], "fastp_library_qc"):
        sample, lane = _sample_lane(stem)
        summary = report.get("summary") or {}
        before = summary.get("before_filtering") or {}
        after = summary.get("after_filtering") or {}
        filt = report.get("filtering_result") or {}
        total = before.get("total_reads")
        q30_before, q30_after = before.get("q30_rate"), after.get("q30_rate")
        gc = after.get("gc_content")
        dup = (report.get("duplication") or {}).get("rate")
        peak = (report.get("insert_size") or {}).get("peak")
        rows.append(
            {
                "sample": sample,
                "lane": lane,
                "lane_label": f"Lane {lane}" if lane is not None else "All lanes",
                "fastq_id": stem,
                "reads_before": int(total) if total is not None else None,
                "reads_after": int(after["total_reads"]) if "total_reads" in after else None,
                "pct_passed": _pct(filt.get("passed_filter_reads"), total),
                "pct_low_quality": _pct(filt.get("low_quality_reads"), total),
                "pct_too_many_n": _pct(filt.get("too_many_N_reads"), total),
                "pct_too_short": _pct(filt.get("too_short_reads"), total),
                "pct_duplication": 100.0 * float(dup) if dup is not None else None,
                "pct_adapter_trimmed": _pct(
                    (report.get("adapter_cutting") or {}).get("adapter_trimmed_reads"), total
                ),
                "gc_pct": 100.0 * float(gc) if gc is not None else None,
                "pct_q30_before": 100.0 * float(q30_before) if q30_before is not None else None,
                "pct_q30_after": 100.0 * float(q30_after) if q30_after is not None else None,
                "mean_length_after": (
                    float(after["read1_mean_length"]) if "read1_mean_length" in after else None
                ),
                "insert_size_peak": int(peak) if peak is not None else None,
            }
        )
    if not rows:
        raise ValueError("fastp_library_qc: no fastp report was read")
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["sample", "lane"])
