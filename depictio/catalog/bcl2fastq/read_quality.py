"""Base quality per lane and read from bcl2fastq ``Stats.json``.

One row per (flowcell, lane, read): the yield of that read and how much of it
reached Q30, pooled over every library of the lane and the Undetermined reads.
Index reads are not reported by bcl2fastq and do not appear. A read 2 that
drops well below read 1 on one lane only is a lane problem; on every lane it
is the chemistry.

``frac_q30`` repeats ``pct_q30`` as a 0 to 1 fraction, the unit a dot size
role expects, so a lane by read dot plot can size the dots by it and colour
them by ``mean_quality``.

Read with the same one-line-per-row scan as ``bcl2fastq/demux_stats``.

Output schema:
    flowcell : Utf8          flowcell id
    lane : Int64             lane number
    lane_label : Utf8        "Lane <n>"
    read : Int64             read number (1, 2 for a paired run)
    read_label : Utf8        "Read <n>"
    yield_gb : Float64       bases passing filter in that read, gigabases
    pct_q30 : Float64        bases at Q30 or above, percent
    frac_q30 : Float64       the same as a fraction, 0 to 1
    mean_quality : Float64   mean Phred score
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
    "read": pl.Int64,
    "read_label": pl.Utf8,
    "yield_gb": pl.Float64,
    "pct_q30": pl.Float64,
    "frac_q30": pl.Float64,
    "mean_quality": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (flowcell, lane, read)."""
    rows: list[dict] = []
    for flowcell, lane in lanes(load_reports(sources["stats"])):
        lane_no = int(lane.get("LaneNumber", 0))
        by_read: dict[int, list[dict]] = {}
        blocks = [lib.get("ReadMetrics") or [] for lib in lane.get("DemuxResults") or []]
        blocks.append((lane.get("Undetermined") or {}).get("ReadMetrics") or [])
        for block in blocks:
            for m in block:
                by_read.setdefault(int(m.get("ReadNumber", 0)), []).append(m)
        for read_no in sorted(by_read):
            yield_bp, pct_q30, mean_q = quality(by_read[read_no])
            rows.append(
                {
                    "flowcell": flowcell,
                    "lane": lane_no,
                    "lane_label": f"Lane {lane_no}",
                    "read": read_no,
                    "read_label": f"Read {read_no}",
                    "yield_gb": yield_bp / 1e9,
                    "pct_q30": pct_q30,
                    "frac_q30": pct_q30 / 100.0 if pct_q30 is not None else None,
                    "mean_quality": mean_q,
                }
            )
    if not rows:
        raise ValueError("bcl2fastq_read_quality: no read metrics in the scanned reports")
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA).sort(["flowcell", "lane", "read"])
