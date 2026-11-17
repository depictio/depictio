"""Spectra acquired per run: one row per mzML file.

quantms converts every raw file to mzML and writes its spectrum table
(``mzmlstatistics/<run>_mzml_info.tsv``: one row per spectrum with its MS level, the
number of peaks, the base-peak intensity, the retention time in seconds and the
precursor m/z of an MS2). This recipe reduces each table to the numbers that say whether
the runs were acquired alike: the MS1 and MS2 spectrum counts, how many MS2 spectra
fall on each MS1, the median peaks per MS2 and the median MS2 base-peak intensity, and
the retention-time span.

The run is read from the file name (``<run>_mzml_info.tsv``). The group column named by
the template's ``group_col`` parameter (the hub's ``condition`` by default) is joined
from ``samples``.

Output schema (the group column right after ``run_id``):
    run_id : Utf8
    ms1_spectra : Int64
    ms2_spectra : Int64
    ms2_per_ms1 : Float64               MS2 spectra per MS1 spectrum
    median_ms2_peaks : Float64          median peaks in an MS2 spectrum
    median_base_peak_intensity : Float64 median base-peak intensity of the MS2 spectra
    rt_start_min : Float64              first spectrum, minutes
    rt_end_min : Float64                last spectrum, minutes
    gradient_min : Float64              span of the acquisition, minutes
    ms2_per_min : Float64               MS2 spectra per minute of the acquisition
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
            "MS2_peaks": pl.Float64,
            "Base_Peak_Intensity": pl.Float64,
            "Retention_Time": pl.Float64,
        },
    ),
    RecipeSource(ref="hub", dc_ref=HUB_DC_TAG, optional=True, input_schema={"run_id": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "ms1_spectra": pl.Int64,
    "ms2_spectra": pl.Int64,
    "ms2_per_ms1": pl.Float64,
    "median_ms2_peaks": pl.Float64,
    "median_base_peak_intensity": pl.Float64,
    "rt_start_min": pl.Float64,
    "rt_end_min": pl.Float64,
    "gradient_min": pl.Float64,
    "ms2_per_min": pl.Float64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All runs"
_SUFFIX = "_mzml_info.tsv"


def run_of_path(path_expr: pl.Expr) -> pl.Expr:
    """The run named by ``mzmlstatistics/<run>_mzml_info.tsv``."""
    return path_expr.str.split("/").list.last().str.replace(_SUFFIX, "", literal=True)


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
    spectra = sources["spectra"].with_columns(run_of_path(pl.col("source_path")).alias("run_id"))
    ms2 = pl.col("MSLevel") == 2
    out = (
        spectra.group_by("run_id")
        .agg(
            (pl.col("MSLevel") == 1).sum().cast(pl.Int64).alias("ms1_spectra"),
            ms2.sum().cast(pl.Int64).alias("ms2_spectra"),
            pl.col("MS2_peaks").filter(ms2).median().alias("median_ms2_peaks"),
            pl.col("Base_Peak_Intensity")
            .filter(ms2)
            .median()
            .round(1)
            .alias("median_base_peak_intensity"),
            (pl.col("Retention_Time").min() / 60.0).round(3).alias("rt_start_min"),
            (pl.col("Retention_Time").max() / 60.0).round(3).alias("rt_end_min"),
        )
        .with_columns(
            pl.when(pl.col("ms1_spectra") > 0)
            .then((pl.col("ms2_spectra") / pl.col("ms1_spectra")).round(3))
            .otherwise(None)
            .alias("ms2_per_ms1"),
            (pl.col("rt_end_min") - pl.col("rt_start_min")).round(3).alias("gradient_min"),
        )
        .with_columns(
            pl.when(pl.col("gradient_min") > 0)
            .then((pl.col("ms2_spectra") / pl.col("gradient_min")).round(2))
            .otherwise(None)
            .alias("ms2_per_min")
        )
    )
    group_name, lookup = group_lookup(sources.get("hub"), params)
    out = out.join(lookup, on="run_id", how="left").with_columns(
        pl.col(group_name).fill_null("Unassigned" if group_name != NO_GROUP_COL else NO_GROUP_VALUE)
    )
    return out.select("run_id", group_name, *list(OUTPUT_SCHEMA)[1:]).sort("run_id")
