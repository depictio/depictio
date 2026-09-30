"""Run health per lane from bcl2fastq ``Stats.json``: clusters, yield, quality, balance.

One row per (flowcell, lane), the numbers a sequencing facility reads first:
how many clusters the lane made and how many passed the chastity filter, how
many bases that delivered and how good they were, how much of it no index
claimed, and how evenly the libraries shared what was claimed.

``pct_q30`` and ``mean_quality`` are pooled over every read of the lane
(libraries and Undetermined, all non-index reads), weighted by bases, the way
bcl2fastq's own lane table computes them. ``library_reads_cv`` is the
coefficient of variation of the reads per library on the lane (standard
deviation over mean, percent): 0 is a perfectly balanced pool.
``lowest_library_pct_of_mean`` is the smallest library's reads as a percent of
the mean library, the number that says whether one library needs a top-up.

Read with the same one-line-per-row scan as ``bcl2fastq/demux_stats``.

Output schema:
    flowcell : Utf8                          flowcell id
    lane : Int64                             lane number
    lane_label : Utf8                        "Lane <n>"
    clusters_raw : Int64                     clusters detected
    clusters_pf : Int64                      clusters passing filter
    pct_pf : Float64                         clusters_pf over clusters_raw, percent
    yield_gb : Float64                       bases passing filter, gigabases
    pct_q30 : Float64                        bases at Q30 or above, percent
    mean_quality : Float64                   mean Phred score
    n_libraries : Int64                      libraries demultiplexed on the lane
    library_reads : Int64                    reads assigned to a library
    undetermined_reads : Int64               reads no index matched
    pct_undetermined : Float64               undetermined over all reads, percent
    library_reads_cv : Float64               CV of reads per library, percent
    lowest_library_pct_of_mean : Float64     smallest library over the mean library, percent
"""

from __future__ import annotations

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the template must scan ``Stats.json`` into, one line per row.
RAW_DC_TAG = "bcl2fastq_stats_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="stats", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "flowcell": pl.Utf8,
    "lane": pl.Int64,
    "lane_label": pl.Utf8,
    "clusters_raw": pl.Int64,
    "clusters_pf": pl.Int64,
    "pct_pf": pl.Float64,
    "yield_gb": pl.Float64,
    "pct_q30": pl.Float64,
    "mean_quality": pl.Float64,
    "n_libraries": pl.Int64,
    "library_reads": pl.Int64,
    "undetermined_reads": pl.Int64,
    "pct_undetermined": pl.Float64,
    "library_reads_cv": pl.Float64,
    "lowest_library_pct_of_mean": pl.Float64,
}

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"


def _load_reports(raw: pl.DataFrame) -> list[dict]:
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


def _lanes(reports: list[dict]) -> list[tuple[str, dict]]:
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


def _quality(read_metrics: list[dict]) -> tuple[float, float | None, float | None]:
    """(yield in bases, percent at Q30 or above, mean Phred) over every read."""
    yield_bp = float(sum(m.get("Yield", 0) for m in read_metrics))
    q30 = float(sum(m.get("YieldQ30", 0) for m in read_metrics))
    qsum = float(sum(m.get("QualityScoreSum", 0) for m in read_metrics))
    if yield_bp <= 0:
        return 0.0, None, None
    return yield_bp, 100.0 * q30 / yield_bp, qsum / yield_bp


def _balance(reads: list[int]) -> tuple[float | None, float | None]:
    """(CV percent, smallest over mean percent) of the reads per library."""
    if not reads:
        return None, None
    mean = sum(reads) / len(reads)
    if mean <= 0:
        return None, None
    var = sum((r - mean) ** 2 for r in reads) / (len(reads) - 1) if len(reads) > 1 else 0.0
    return 100.0 * var**0.5 / mean, 100.0 * min(reads) / mean


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (flowcell, lane)."""
    rows: list[dict] = []
    for flowcell, lane in _lanes(_load_reports(sources["stats"])):
        lane_no = int(lane.get("LaneNumber", 0))
        libraries = lane.get("DemuxResults") or []
        und = lane.get("Undetermined") or {}
        metrics = [m for lib in libraries for m in (lib.get("ReadMetrics") or [])]
        metrics += und.get("ReadMetrics") or []
        yield_bp, pct_q30, mean_q = _quality(metrics)
        lib_reads = [int(lib.get("NumberReads", 0)) for lib in libraries]
        und_reads = int(und.get("NumberReads", 0))
        total = sum(lib_reads) + und_reads
        raw = lane.get("TotalClustersRaw")
        pf = lane.get("TotalClustersPF")
        cv, lowest = _balance(lib_reads)
        rows.append(
            {
                "flowcell": flowcell,
                "lane": lane_no,
                "lane_label": f"Lane {lane_no}",
                "clusters_raw": int(raw) if raw is not None else None,
                "clusters_pf": int(pf) if pf is not None else None,
                "pct_pf": 100.0 * pf / raw if raw and pf is not None else None,
                "yield_gb": yield_bp / 1e9,
                "pct_q30": pct_q30,
                "mean_quality": mean_q,
                "n_libraries": len(libraries),
                "library_reads": sum(lib_reads),
                "undetermined_reads": und_reads,
                "pct_undetermined": 100.0 * und_reads / total if total else None,
                "library_reads_cv": cv,
                "lowest_library_pct_of_mean": lowest,
            }
        )
    if not rows:
        raise ValueError("bcl2fastq_lane_summary: no lane in the scanned reports")
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["flowcell", "lane"])
