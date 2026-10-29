"""Acquisition over the gradient: one row per run and minute of retention time.

Bins every run's spectrum table (``mzmlstatistics/<run>_mzml_info.tsv``) by the minute the
spectrum was acquired and counts the MS1 and MS2 spectra in it, with the median base-peak
intensity of the MS2 spectra. Plotted per run, the MS2 rate shows whether the instrument
kept its duty cycle and the intensity trace is a base-peak chromatogram of the MS2 signal:
runs that were acquired alike have curves that lie on each other.

The group column named by the template's ``group_col`` parameter (the hub's ``condition``
by default) is joined from ``samples``.

Output schema (the group column right after ``run_id``):
    run_id : Utf8
    rt_min : Float64               start of the one-minute bin, minutes
    ms1_spectra : Int64
    ms2_spectra : Int64
    median_base_peak_intensity : Float64   median MS2 base-peak intensity in the bin
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

HUB_DC_TAG = "samples"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="spectra",
        glob_pattern="mzmlstatistics/*_mzml_info.tsv",
        format="tsv",
        source_path="source_path",
        read_kwargs={"infer_schema_length": 20000, "null_values": ["NA"]},
        input_schema={
            "MSLevel": pl.Int64,
            "Base_Peak_Intensity": pl.Float64,
            "Retention_Time": pl.Float64,
        },
    ),
    RecipeSource(ref="hub", dc_ref=HUB_DC_TAG, optional=True, input_schema={"run_id": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "rt_min": pl.Float64,
    "ms1_spectra": pl.Int64,
    "ms2_spectra": pl.Int64,
    "median_base_peak_intensity": pl.Float64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All runs"
_SUFFIX = "_mzml_info.tsv"


def group_lookup(hub: pl.DataFrame | None, params: dict | None) -> tuple[str, pl.DataFrame]:
    """The group column's name and a ``run_id`` to group value table."""
    wanted = (params or {}).get("group_col") or "condition"
    if hub is not None and not hub.is_empty() and "run_id" in hub.columns:
        col = (
            wanted
            if wanted in hub.columns
            else ("condition" if "condition" in hub.columns else None)
        )
        if col is not None:
            table = hub.select(
                pl.col("run_id").cast(pl.Utf8), pl.col(col).cast(pl.Utf8).alias(col)
            ).unique(subset="run_id", keep="first")
            return col, table
    return NO_GROUP_COL, pl.DataFrame(schema={"run_id": pl.Utf8, NO_GROUP_COL: pl.Utf8})


def transform(sources: dict[str, pl.DataFrame | None], params: dict | None = None) -> pl.DataFrame:
    spectra = sources["spectra"].with_columns(
        pl.col("source_path")
        .str.split("/")
        .list.last()
        .str.replace(_SUFFIX, "", literal=True)
        .alias("run_id"),
        (pl.col("Retention_Time") / 60.0).floor().alias("rt_min"),
    )
    ms2 = pl.col("MSLevel") == 2
    out = spectra.group_by(["run_id", "rt_min"]).agg(
        (pl.col("MSLevel") == 1).sum().cast(pl.Int64).alias("ms1_spectra"),
        ms2.sum().cast(pl.Int64).alias("ms2_spectra"),
        pl.col("Base_Peak_Intensity")
        .filter(ms2)
        .median()
        .round(1)
        .alias("median_base_peak_intensity"),
    )
    group_name, lookup = group_lookup(sources.get("hub"), params)
    out = out.join(lookup, on="run_id", how="left").with_columns(
        pl.col(group_name).fill_null("Unassigned" if group_name != NO_GROUP_COL else NO_GROUP_VALUE)
    )
    return out.select("run_id", group_name, *list(OUTPUT_SCHEMA)[1:]).sort(["run_id", "rt_min"])
