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

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bcl2fastq_reports import lanes, load_reports, quality

#: Data-collection tag the template must scan ``Stats.json`` into, one line per row.
RAW_DC_TAG = "bcl2fastq_stats_raw"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="stats",
        input_schema={
            "raw": pl.Utf8,
            "source_path": pl.Utf8,
        },
        dc_ref=RAW_DC_TAG,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
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


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (lane, library) plus the lane's Undetermined row."""
    rows: list[dict] = []
    for flowcell, lane in lanes(load_reports(sources["stats"])):
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
            yield_bp, pct_q30, mean_q = quality(e["metrics"])
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
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA).sort(["flowcell", "lane", "sample"])
