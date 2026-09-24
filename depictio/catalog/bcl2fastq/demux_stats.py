"""Reads per library and lane, with the undetermined reads, from bcl2fastq ``Stats.json``.

bcl2fastq writes one ``Stats/Stats.json`` per demultiplexing run. Its
``ConversionResults`` list holds one entry per lane; each entry lists the
libraries of that lane (``DemuxResults``) and the reads no index matched
(``Undetermined``)::

    {"Flowcell": "000000000-ABCDE", "RunId": "...",
     "ConversionResults": [
       {"LaneNumber": 1, "TotalClustersRaw": 34153016, "TotalClustersPF": 30721480,
        "DemuxResults": [
          {"SampleId": "S1", "SampleName": "S1",
           "IndexMetrics": [{"IndexSequence": "AAGAGGCA+TCGACTAG",
                             "MismatchCounts": {"0": 1336529, "1": 139717}}],
           "NumberReads": 1476246, "Yield": 445826292,
           "ReadMetrics": [{"ReadNumber": 1, "Yield": ..., "YieldQ30": ...,
                            "QualityScoreSum": ...}, ...]}],
        "Undetermined": {"NumberReads": ..., "Yield": ..., "ReadMetrics": [...]}}]}

One row per (lane, library), plus one ``Undetermined`` row per lane, so a
stacked bar or a sunburst over a lane sums to every read the lane delivered and
the share nobody claimed stays visible. ``pct_of_lane`` is taken against that
total. A run demultiplexed lane by lane writes one ``Stats.json`` per lane; the
recipe reads them all and keeps the first report of a (flowcell, lane) pair.

The file is read one LINE per row (the text-scan idiom), so no JSON reader has
to be declared on the collection::

    dc_specific_properties:
      format: TSV
      polars_kwargs:
        separator: "\\x1f"
        quote_char: null
        has_header: false
        new_columns: ["raw"]
        include_file_paths: "source_path"
        infer_schema_length: 0

Output schema:
    flowcell : Utf8                   flowcell id
    lane : Int64                      lane number
    lane_label : Utf8                 "Lane <n>", a categorical axis label
    sample : Utf8                     library name, or "Undetermined"
    index : Utf8                      index sequence(s), i7+i5; empty for Undetermined
    is_undetermined : Boolean         true on the per-lane Undetermined row
    level : Utf8                      "Library" on every row, the single rank a composition bar reads
    reads : Int64                     read clusters assigned (pairs count once)
    pct_of_lane : Float64             reads over every read of the lane, percent
    yield_mb : Float64                bases passing filter, megabases, all reads
    pct_q30 : Float64                 bases at Q30 or above, percent of the yield
    mean_quality : Float64            mean Phred score of the yield
    pct_perfect_index : Float64       reads whose index matched with no mismatch, percent
    pct_one_mismatch_index : Float64  reads whose index matched with one mismatch, percent
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
    "sample": pl.Utf8,
    "index": pl.Utf8,
    "is_undetermined": pl.Boolean,
    "level": pl.Utf8,
    "reads": pl.Int64,
    "pct_of_lane": pl.Float64,
    "yield_mb": pl.Float64,
    "pct_q30": pl.Float64,
    "mean_quality": pl.Float64,
    "pct_perfect_index": pl.Float64,
    "pct_one_mismatch_index": pl.Float64,
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


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (lane, library) plus the lane's Undetermined row."""
    rows: list[dict] = []
    for flowcell, lane in _lanes(_load_reports(sources["stats"])):
        lane_no = int(lane.get("LaneNumber", 0))
        entries: list[dict] = []
        for lib in lane.get("DemuxResults") or []:
            index_metrics = lib.get("IndexMetrics") or []
            mismatches: dict[str, int] = {}
            for im in index_metrics:
                for k, v in (im.get("MismatchCounts") or {}).items():
                    mismatches[k] = mismatches.get(k, 0) + int(v)
            reads = int(lib.get("NumberReads", 0))
            entries.append(
                {
                    "sample": str(lib.get("SampleName") or lib.get("SampleId")),
                    "index": str(index_metrics[0].get("IndexSequence") or "")
                    if index_metrics
                    else "",
                    "is_undetermined": False,
                    "reads": reads,
                    "metrics": lib.get("ReadMetrics") or [],
                    "perfect": mismatches.get("0"),
                    "one": mismatches.get("1"),
                }
            )
        und = lane.get("Undetermined")
        if und:
            entries.append(
                {
                    "sample": "Undetermined",
                    "index": "",
                    "is_undetermined": True,
                    "reads": int(und.get("NumberReads", 0)),
                    "metrics": und.get("ReadMetrics") or [],
                    "perfect": None,
                    "one": None,
                }
            )
        lane_total = sum(e["reads"] for e in entries)
        for e in entries:
            yield_bp, pct_q30, mean_q = _quality(e["metrics"])
            reads = e["reads"]
            rows.append(
                {
                    "flowcell": flowcell,
                    "lane": lane_no,
                    "lane_label": f"Lane {lane_no}",
                    "sample": e["sample"],
                    "index": e["index"],
                    "is_undetermined": e["is_undetermined"],
                    "level": "Library",
                    "reads": reads,
                    "pct_of_lane": 100.0 * reads / lane_total if lane_total else None,
                    "yield_mb": yield_bp / 1e6,
                    "pct_q30": pct_q30,
                    "mean_quality": mean_q,
                    "pct_perfect_index": (
                        100.0 * e["perfect"] / reads if e["perfect"] is not None and reads else None
                    ),
                    "pct_one_mismatch_index": (
                        100.0 * e["one"] / reads if e["one"] is not None and reads else None
                    ),
                }
            )
    if not rows:
        raise ValueError("bcl2fastq_demux_stats: no lane carried a library")
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["flowcell", "lane", "sample"])
