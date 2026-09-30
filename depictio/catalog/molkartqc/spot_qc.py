"""molkartqc's per-sample, per-segmentation QC sheet, typed, with the sample id
split from the method and the derived counts a dashboard reads directly.

nf-core/molkart's local MOLKARTQC process (``bin/collect_QC.py``) writes one
one-row CSV per sample and segmentation method,
``molkartqc/<sample>.<method>.spot_QC.csv``. Its ``sample_id`` column is
``<sample>_<method>``, not the samplesheet id, so the sample is recovered by
stripping the ``segmentation_method`` suffix the same row carries. The MultiQC
"QC statistics from segmentation" table is the concatenation of these files.

``total_spots`` and ``duplicated_total`` describe the sample's spot table, so
they repeat on every method row of a sample: sum them over one method only.

Output schema:
    sample : Utf8                    samplesheet sample id
    segmentation_method : Utf8       mesmer | cellpose | stardist | ilastik
    total_cells : Int64              cells after the area filter
    avg_area : Float64               mean cell area, pixels
    total_spots : Int64              non-duplicated spots of the sample
    spot_assign_per_cell : Float64   mean transcripts per cell
    spot_assign_total : Int64        spots that fell inside a cell
    spot_assign_percent : Float64    spot_assign_total over total_spots, percent
    spots_unassigned : Int64         total_spots minus spot_assign_total
    duplicated_total : Int64         spots Mindagap marked as duplicated on grid lines
    duplicated_percent : Float64     duplicated over all spots (kept + duplicated), percent
    labels_total : Int64             labels the segmentation produced, before the area filter
    labels_below_thresh : Int64      labels removed as too small
    labels_above_thresh : Int64      labels removed as too large
    labels_removed_percent : Float64 removed labels over labels_total, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="qc",
        glob_pattern="**/*.spot_QC.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "segmentation_method": pl.Utf8,
    "total_cells": pl.Int64,
    "avg_area": pl.Float64,
    "total_spots": pl.Int64,
    "spot_assign_per_cell": pl.Float64,
    "spot_assign_total": pl.Int64,
    "spot_assign_percent": pl.Float64,
    "spots_unassigned": pl.Int64,
    "duplicated_total": pl.Int64,
    "duplicated_percent": pl.Float64,
    "labels_total": pl.Int64,
    "labels_below_thresh": pl.Int64,
    "labels_above_thresh": pl.Int64,
    "labels_removed_percent": pl.Float64,
}

INT_COLUMNS = (
    "total_cells",
    "total_spots",
    "spot_assign_total",
    "duplicated_total",
    "labels_total",
    "labels_below_thresh",
    "labels_above_thresh",
)
FLOAT_COLUMNS = ("avg_area", "spot_assign_per_cell", "spot_assign_percent")


def _int(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Float64, strict=False).round(0).cast(pl.Int64).alias(name)


def _pct(num: pl.Expr, den: pl.Expr) -> pl.Expr:
    return pl.when(den > 0).then(100.0 * num / den).otherwise(0.0).cast(pl.Float64)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One-row spot_QC sheets -> one typed row per (sample, method)."""
    raw = sources["qc"]
    missing = {"sample_id", "segmentation_method"} - set(raw.columns)
    if missing:
        raise ValueError(f"molkartqc spot_qc: columns {sorted(missing)} missing, got {raw.columns}")
    for name in (*INT_COLUMNS, *FLOAT_COLUMNS):
        if name not in raw.columns:
            raw = raw.with_columns(pl.lit(None, dtype=pl.Utf8).alias(name))

    method = pl.col("segmentation_method").cast(pl.Utf8).str.strip_chars()
    sample_id = pl.col("sample_id").cast(pl.Utf8).str.strip_chars()
    suffix = pl.lit("_") + method
    frame = raw.select(
        pl.when(sample_id.str.ends_with(suffix))
        .then(sample_id.str.slice(0, sample_id.str.len_chars() - suffix.str.len_chars()))
        .otherwise(sample_id)
        .alias("sample"),
        method.alias("segmentation_method"),
        *[_int(c) for c in INT_COLUMNS],
        *[pl.col(c).cast(pl.Float64, strict=False).alias(c) for c in FLOAT_COLUMNS],
    )
    frame = frame.with_columns(
        (pl.col("total_spots") - pl.col("spot_assign_total")).alias("spots_unassigned"),
        _pct(pl.col("duplicated_total"), pl.col("total_spots") + pl.col("duplicated_total")).alias(
            "duplicated_percent"
        ),
        _pct(
            pl.col("labels_below_thresh").fill_null(0) + pl.col("labels_above_thresh").fill_null(0),
            pl.col("labels_total"),
        ).alias("labels_removed_percent"),
    )
    return (
        frame.select(list(EXPECTED_SCHEMA))
        .unique(subset=["sample", "segmentation_method"], keep="last", maintain_order=True)
        .sort(["sample", "segmentation_method"])
    )
