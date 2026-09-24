"""Top unknown barcodes per lane, classed as likely index swaps, from bcl2fastq ``Stats.json``.

``UnknownBarcodes`` lists, per lane, the index sequences bcl2fastq saw most
often among the reads it could not assign, with their counts (the top 1000).
Read on its own that list is a wall of sequences. What a facility wants from
it is whether the unclaimed reads are:

* a pair of indexes that are both in use on the lane but were never pooled
  together (an index hop or a sample sheet swap: the two libraries whose
  indexes these are should be checked),
* one index in use and the other not (a wrong or missing i5/i7 in the sheet),
* neither in use (a library that was not in the sheet at all), or
* poly-G / N reads (no index read at all, typical of empty clusters on
  two-colour chemistry).

``swap_class`` names that class. The indexes in use come from the same
report's ``DemuxResults``. The recipe keeps the 100 most frequent barcodes of
each lane. ``pct_of_lane`` is taken against all reads of the lane,
``pct_of_undetermined`` against the lane's Undetermined reads.

Read with the same one-line-per-row scan as ``bcl2fastq/demux_stats``.

Output schema:
    flowcell : Utf8               flowcell id
    lane : Int64                  lane number
    lane_label : Utf8             "Lane <n>"
    barcode : Utf8                observed index sequence(s), i7+i5
    index1 : Utf8                 observed i7
    index2 : Utf8                 observed i5, empty on a single-index run
    reads : Int64                 reads carrying that barcode
    rank : Int64                  1 for the most frequent barcode of the lane
    pct_of_lane : Float64         reads over all reads of the lane, percent
    pct_of_undetermined : Float64 reads over the Undetermined reads of the lane, percent
    i7_in_use : Boolean           the i7 belongs to a library of the lane
    i5_in_use : Boolean           the i5 belongs to a library of the lane
    swap_class : Utf8             one of the four classes above
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
    "barcode": pl.Utf8,
    "index1": pl.Utf8,
    "index2": pl.Utf8,
    "reads": pl.Int64,
    "rank": pl.Int64,
    "pct_of_lane": pl.Float64,
    "pct_of_undetermined": pl.Float64,
    "i7_in_use": pl.Boolean,
    "i5_in_use": pl.Boolean,
    "swap_class": pl.Utf8,
}

#: Barcodes kept per lane, most frequent first.
TOP_N_PER_LANE = 100

SWAP_BOTH = "Both indexes in use"
SWAP_I7 = "Only i7 in use"
SWAP_I5 = "Only i5 in use"
SWAP_NONE = "Neither index in use"
SWAP_NO_INDEX = "Poly-G or N index"

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


def _split(barcode: str) -> tuple[str, str]:
    """(i7, i5) of an ``i7+i5`` barcode; i5 is empty on a single-index run."""
    i7, _, i5 = barcode.partition("+")
    return i7, i5


def _no_index(seq: str) -> bool:
    """A read with no usable index: all G (two-colour dark cycles) or any N."""
    return bool(seq) and ("N" in seq or set(seq) == {"G"})


def classify(i7: str, i5: str, used_i7: set[str], used_i5: set[str]) -> tuple[bool, bool, str]:
    """(i7 in use, i5 in use, swap class) of one unknown barcode."""
    i7_in = i7 in used_i7
    i5_in = bool(i5) and i5 in used_i5
    if _no_index(i7) or _no_index(i5):
        return i7_in, i5_in, SWAP_NO_INDEX
    if i7_in and i5_in:
        return i7_in, i5_in, SWAP_BOTH
    if i7_in:
        return i7_in, i5_in, SWAP_I7
    if i5_in:
        return i7_in, i5_in, SWAP_I5
    return i7_in, i5_in, SWAP_NONE


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Up to ``TOP_N_PER_LANE`` rows per lane, most frequent first."""
    reports = _load_reports(sources["stats"])
    lane_info: dict[tuple[str, int], dict] = {}
    for flowcell, lane in _lanes(reports):
        libs = lane.get("DemuxResults") or []
        used_i7: set[str] = set()
        used_i5: set[str] = set()
        for lib in libs:
            for im in lib.get("IndexMetrics") or []:
                i7, i5 = _split(str(im.get("IndexSequence") or ""))
                used_i7.add(i7)
                if i5:
                    used_i5.add(i5)
        und = int((lane.get("Undetermined") or {}).get("NumberReads", 0))
        total = sum(int(lib.get("NumberReads", 0)) for lib in libs) + und
        lane_info[(flowcell, int(lane.get("LaneNumber", 0)))] = {
            "i7": used_i7,
            "i5": used_i5,
            "und": und,
            "total": total,
        }

    rows: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for report in reports:
        flowcell = str(report.get("Flowcell") or "")
        for block in report.get("UnknownBarcodes") or []:
            lane_no = int(block.get("Lane", 0))
            if (flowcell, lane_no) in seen:
                continue
            seen.add((flowcell, lane_no))
            info = lane_info.get(
                (flowcell, lane_no), {"i7": set(), "i5": set(), "und": 0, "total": 0}
            )
            counts = sorted(
                ((str(k), int(v)) for k, v in (block.get("Barcodes") or {}).items()),
                key=lambda kv: -kv[1],
            )[:TOP_N_PER_LANE]
            for rank, (barcode, reads) in enumerate(counts, start=1):
                i7, i5 = _split(barcode)
                i7_in, i5_in, swap = classify(i7, i5, info["i7"], info["i5"])
                rows.append(
                    {
                        "flowcell": flowcell,
                        "lane": lane_no,
                        "lane_label": f"Lane {lane_no}",
                        "barcode": barcode,
                        "index1": i7,
                        "index2": i5,
                        "reads": reads,
                        "rank": rank,
                        "pct_of_lane": 100.0 * reads / info["total"] if info["total"] else None,
                        "pct_of_undetermined": 100.0 * reads / info["und"] if info["und"] else None,
                        "i7_in_use": i7_in,
                        "i5_in_use": i5_in,
                        "swap_class": swap,
                    }
                )
    if not rows:
        raise ValueError("bcl2fastq_unknown_barcodes: no UnknownBarcodes block in the reports")
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["flowcell", "lane", "rank"])
