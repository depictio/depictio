"""Top unknown barcodes per lane, classed as likely index swaps, from BCL Convert reports.

``Reports/Top_Unknown_Barcodes.csv`` lists the most frequent unassigned index
pairs per lane::

    Lane,index,index2,# Reads,% of Unknown Barcodes,% of All Reads

The indexes in use on each lane come from ``Demultiplex_Stats.csv`` (second
source). The schema and the four swap classes are identical to
``bcl2fastq/unknown_barcodes``; see there for their meaning. The recipe keeps
the 100 most frequent barcodes of each lane.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bclconvert_reports import num, with_run
from depictio.recipes.lib.demux_barcodes import classify

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="unknown",
        dc_ref="bclconvert_unknown_raw",
        input_schema={
            "Lane": pl.Utf8,
            "# Reads": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="demux",
        dc_ref="bclconvert_demux_raw",
        input_schema={
            "SampleID": pl.Utf8,
            "Lane": pl.Utf8,
            "# Reads": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
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


DEMUX_DC_TAG = "bclconvert_demux_raw"
QUALITY_DC_TAG = "bclconvert_quality_raw"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Up to ``TOP_N_PER_LANE`` rows per lane, most frequent first."""
    unknown, demux = sources["unknown"], sources["demux"]
    if unknown is None or unknown.is_empty():
        raise ValueError("bclconvert_unknown_barcodes: Top_Unknown_Barcodes.csv is empty")
    d = (
        with_run(demux)
        .with_columns(
            pl.col("SampleID").cast(pl.Utf8).alias("sample"),
            num(demux, "# Reads", pl.Int64).alias("reads"),
            pl.col("Index").cast(pl.Utf8).str.replace_all("-", "+").alias("index")
            if "Index" in demux.columns
            else pl.lit("", dtype=pl.Utf8).alias("index"),
        )
        .unique(subset=["flowcell", "lane", "sample"], keep="first", maintain_order=True)
    )
    lane_info: dict[tuple[str, int], dict] = {}
    for (flowcell, lane), g in d.group_by(["flowcell", "lane"]):
        libs = g.filter(pl.col("sample") != "Undetermined")
        i7s, i5s = set(), set()
        for idx in libs["index"].fill_null("").to_list():
            i7, _, i5 = idx.partition("+")
            i7s.add(i7)
            if i5:
                i5s.add(i5)
        lane_info[(flowcell, lane)] = {
            "i7": i7s,
            "i5": i5s,
            "und": int(g.filter(pl.col("sample") == "Undetermined")["reads"].sum() or 0),
            "total": int(g["reads"].sum() or 0),
        }
    u = with_run(unknown).with_columns(
        pl.col("index").cast(pl.Utf8).fill_null("").alias("index1")
        if "index" in unknown.columns
        else pl.lit("", dtype=pl.Utf8).alias("index1"),
        pl.col("index2").cast(pl.Utf8).fill_null("").alias("index2")
        if "index2" in unknown.columns
        else pl.lit("", dtype=pl.Utf8).alias("index2"),
        num(unknown, "# Reads", pl.Int64).alias("reads"),
    )
    rows: list[dict] = []
    for (flowcell, lane), g in u.group_by(["flowcell", "lane"], maintain_order=True):
        info = lane_info.get((flowcell, lane), {"i7": set(), "i5": set(), "und": 0, "total": 0})
        top = g.sort("reads", descending=True).head(TOP_N_PER_LANE)
        for rank, rec in enumerate(top.iter_rows(named=True), start=1):
            i7, i5, reads = rec["index1"], rec["index2"], int(rec["reads"] or 0)
            i7_in, i5_in, swap = classify(i7, i5, info["i7"], info["i5"])
            rows.append(
                {
                    "flowcell": flowcell,
                    "lane": lane,
                    "lane_label": f"Lane {lane}",
                    "barcode": f"{i7}+{i5}" if i5 else i7,
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
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA).sort(["flowcell", "lane", "rank"])
