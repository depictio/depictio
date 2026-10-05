"""Mean base quality per sequencing cycle, per lane and read, pooled over libraries.

fastp records, for every read of a library before any trimming, the mean
Phred score at each cycle (``read1_before_filtering.quality_curves.mean``,
same for read 2). Pooled over every library of a lane, that curve is the
run's per-cycle quality: a drop at one cycle on every lane is the chemistry
or the instrument, a drop on one lane is that lane, and a steady slide at the
end of read 2 is ordinary.

One row per (lane, read, cycle): the median of the libraries' mean quality at
that cycle, with the 10th and 90th percentiles as a band. The median keeps a
library of a few hundred reads (a failed index) from bending the curve. A
MiSeq or NovaSeq run of up to 300 cycles gives at most 300 points per series,
which the recipe thins to at most 200 so a profile stays light.

Read with the same one-line-per-row scan as ``fastp_library_qc``.

Output schema:
    series : Utf8           "Lane <n>, read <r>", one curve each
    lane : Int64            lane, null when the file names carry none
    lane_label : Utf8       "Lane <n>", or "All lanes"
    read : Int64            1 or 2
    cycle : Int64           sequencing cycle, 1-based
    median_quality : Float64  median over libraries of the mean Phred score
    p10_quality : Float64   10th percentile over libraries
    p90_quality : Float64   90th percentile over libraries
    n_libraries : Int64     libraries contributing at that cycle
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
    "series": pl.Utf8,
    "lane": pl.Int64,
    "lane_label": pl.Utf8,
    "read": pl.Int64,
    "cycle": pl.Int64,
    "median_quality": pl.Float64,
    "p10_quality": pl.Float64,
    "p90_quality": pl.Float64,
    "n_libraries": pl.Int64,
}

#: Most points kept per curve.
MAX_POINTS = 200

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


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (lane, read, cycle)."""
    records: list[dict] = []
    for stem, report in _load_reports(sources["reports"], "cycle_quality"):
        _, lane = _sample_lane(stem)
        for read in (1, 2):
            curves = (report.get(f"read{read}_before_filtering") or {}).get("quality_curves")
            mean = (curves or {}).get("mean") or []
            for cycle, value in enumerate(mean, start=1):
                records.append({"lane": lane, "read": read, "cycle": cycle, "q": float(value)})
    if not records:
        raise ValueError("cycle_quality: no fastp report carried a quality curve")
    per_cycle = (
        pl.DataFrame(
            records,
            schema={"lane": pl.Int64, "read": pl.Int64, "cycle": pl.Int64, "q": pl.Float64},
        )
        .group_by(["lane", "read", "cycle"])
        .agg(
            pl.col("q").median().alias("median_quality"),
            pl.col("q").quantile(0.1, "linear").alias("p10_quality"),
            pl.col("q").quantile(0.9, "linear").alias("p90_quality"),
            pl.len().cast(pl.Int64).alias("n_libraries"),
        )
        .sort(["lane", "read", "cycle"])
    )
    # Thin long runs evenly, always keeping the last cycle.
    per_cycle = per_cycle.with_columns(
        pl.col("cycle").max().over(["lane", "read"]).alias("_last")
    ).with_columns(
        ((pl.col("_last") + MAX_POINTS - 1) // MAX_POINTS).clip(lower_bound=1).alias("_step")
    )
    per_cycle = per_cycle.filter(
        ((pl.col("cycle") - 1) % pl.col("_step") == 0) | (pl.col("cycle") == pl.col("_last"))
    )
    lane_label = (
        pl.when(pl.col("lane").is_null())
        .then(pl.lit("All lanes"))
        .otherwise(pl.format("Lane {}", pl.col("lane")))
    )
    return (
        per_cycle.with_columns(lane_label.alias("lane_label"))
        .with_columns(
            pl.format("{}, read {}", pl.col("lane_label"), pl.col("read")).alias("series")
        )
        .select([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()])
    )
