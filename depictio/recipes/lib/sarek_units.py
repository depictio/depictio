"""Who a nf-core/sarek call belongs to: a sample, or a tumour/normal pair.

sarek calls variants per *unit*. A unit is one sample (``S1``) or, for the callers
that read a tumour against its matched normal, a pair named ``<tumour>_vs_<normal>``.
Every published file carries the unit in its name, never a column, so the recipes
that read calls ask this module what a unit is:

``germline``
    a single sample whose samplesheet ``status`` is 0 (normal), or one the sheet does
    not describe (the graceful default of a run read from ``variantcalled.csv`` alone);
``tumour_only``
    a single sample with ``status`` 1, called without a matched normal;
``paired``
    a ``<tumour>_vs_<normal>`` unit.

The hub (``samples``) is the only place the status lives, so the split is made from it.
The three classes are never mixed on one scale: the germline tabs read ``germline``,
the Somatic tabs read the other two.

Also here: ``design``, the per-patient label the hub carries (``Paired``,
``Germline only``, ``Tumour-only``), from the same status column.
"""

from __future__ import annotations

import polars as pl

#: A paired somatic caller names its unit after the pair: ``<tumour>_vs_<normal>``.
PAIR_SEP = "_vs_"

GERMLINE = "germline"
TUMOUR_ONLY = "tumour_only"
PAIRED = "paired"
UNIT_TYPES = (GERMLINE, TUMOUR_ONLY, PAIRED)

#: The hub's per-patient design labels.
DESIGN_PAIRED = "Paired"
DESIGN_GERMLINE = "Germline only"
DESIGN_TUMOUR_ONLY = "Tumour-only"

#: Schema of :func:`unit_frame`.
UNIT_SCHEMA: dict[str, type[pl.DataType]] = {
    "unit": pl.Utf8,
    "unit_type": pl.Utf8,
    "patient": pl.Utf8,
    "sample": pl.Utf8,
    "normal": pl.Utf8,
}


def is_pair(unit: str | None) -> bool:
    """True for a ``<tumour>_vs_<normal>`` unit name."""
    return bool(unit) and PAIR_SEP in str(unit)


def split_pair(unit: str) -> tuple[str, str | None]:
    """``(tumour, normal)`` of a pair, ``(unit, None)`` of a single sample."""
    tumour, sep, normal = unit.partition(PAIR_SEP)
    return (tumour, normal) if sep else (unit, None)


def design_label(statuses: list[int | None]) -> str:
    """The design of one patient from the status of its samples.

    A tumour and a normal make a pair; tumours alone are tumour-only; anything else
    (normals, or samples whose status is unknown) is germline only, the behaviour of
    a run that never told sarek about tumours.
    """
    has_tumour = any(s == 1 for s in statuses)
    has_normal = any(s != 1 for s in statuses)
    if has_tumour and has_normal:
        return DESIGN_PAIRED
    if has_tumour:
        return DESIGN_TUMOUR_ONLY
    return DESIGN_GERMLINE


def unit_frame(units: list[str | None] | pl.Series, hub: pl.DataFrame | None) -> pl.DataFrame:
    """One row per distinct unit: its type, patient, tumour sample and normal sample.

    ``sample`` is the sample whose reads carry the call: the sample itself for a
    single-sample unit, the tumour of a pair. ``normal`` is the pair's normal, null
    otherwise. ``hub`` is the ``samples`` collection (``sample_id``, ``patient``,
    ``status``); without it every single sample is ``germline`` and the patient is
    unknown.
    """
    names = sorted(
        {str(u) for u in (units.to_list() if isinstance(units, pl.Series) else units) if u}
    )
    parts = pl.col("unit").str.splitn(PAIR_SEP, 2)
    df = pl.DataFrame({"unit": names}, schema={"unit": pl.Utf8}).with_columns(
        parts.struct.field("field_0").alias("sample"),
        parts.struct.field("field_1").alias("normal"),
    )
    if hub is not None and not hub.is_empty() and "sample_id" in hub.columns:
        lookup = hub.select(
            pl.col("sample_id").cast(pl.Utf8).alias("sample"),
            (pl.col("patient") if "patient" in hub.columns else pl.lit(None))
            .cast(pl.Utf8)
            .alias("patient"),
            (pl.col("status") if "status" in hub.columns else pl.lit(None))
            .cast(pl.Int64, strict=False)
            .alias("_status"),
        ).unique(subset="sample", keep="first")
        df = df.join(lookup, on="sample", how="left")
    else:
        df = df.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("patient"),
            pl.lit(None, dtype=pl.Int64).alias("_status"),
        )
    return df.select(
        "unit",
        pl.when(pl.col("normal").is_not_null())
        .then(pl.lit(PAIRED))
        .when(pl.col("_status") == 1)
        .then(pl.lit(TUMOUR_ONLY))
        .otherwise(pl.lit(GERMLINE))
        .alias("unit_type"),
        "patient",
        "sample",
        "normal",
    )


def keep_unit_types(
    df: pl.DataFrame, hub: pl.DataFrame | None, *types: str, unit_col: str = "sample"
) -> pl.DataFrame:
    """The rows of ``df`` whose ``unit_col`` is a unit of one of ``types``."""
    if df.is_empty():
        return df
    units = unit_frame(df[unit_col], hub).filter(pl.col("unit_type").is_in(types))
    return df.join(units.select(pl.col("unit").alias(unit_col)), on=unit_col, how="inner")
