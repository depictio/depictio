"""How many peaks an MS2 spectrum holds, per run: one row per run and peak-count bin.

Counts the MS2 spectra of every run (``mzmlstatistics/<run>_mzml_info.tsv``) by the number
of peaks they hold, in bins of 100 up to 1000 and one bin above, the "peaks per MS2" plot
of the pipeline's own QC report. A run whose spectra are mostly nearly empty was acquired or
centroided differently from its neighbours.

The group column named by the template's ``group_col`` parameter (the hub's ``condition``
by default) is joined from ``samples``.

Output schema (the group column right after ``run_id``):
    run_id : Utf8
    peaks : Utf8          bin label, e.g. 100 to 199 or 1000 or more
    bin_start : Int64     first peak count of the bin, for ordering
    spectra : Int64       MS2 spectra in the bin
    fraction : Float64    share of the run's MS2 spectra
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

HUB_DC_TAG = "samples"
BIN_WIDTH = 100
TOP_BIN = 1000

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="spectra",
        glob_pattern="mzmlstatistics/*_mzml_info.tsv",
        format="tsv",
        source_path="source_path",
        read_kwargs={"infer_schema_length": 20000, "null_values": ["NA"]},
        input_schema={"MSLevel": pl.Int64, "MS2_peaks": pl.Float64},
    ),
    RecipeSource(ref="hub", dc_ref=HUB_DC_TAG, optional=True, input_schema={"run_id": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "peaks": pl.Utf8,
    "bin_start": pl.Int64,
    "spectra": pl.Int64,
    "fraction": pl.Float64,
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


def _label(start: int) -> str:
    if start >= TOP_BIN:
        return f"{TOP_BIN} or more"
    return f"{start} to {start + BIN_WIDTH - 1}"


def transform(sources: dict[str, pl.DataFrame | None], params: dict | None = None) -> pl.DataFrame:
    spectra = (
        sources["spectra"]
        .filter((pl.col("MSLevel") == 2) & pl.col("MS2_peaks").is_not_null())
        .with_columns(
            pl.col("source_path")
            .str.split("/")
            .list.last()
            .str.replace(_SUFFIX, "", literal=True)
            .alias("run_id"),
            (pl.col("MS2_peaks") // BIN_WIDTH * BIN_WIDTH)
            .clip(upper_bound=TOP_BIN)
            .cast(pl.Int64)
            .alias("bin_start"),
        )
    )
    counts = spectra.group_by(["run_id", "bin_start"]).agg(pl.len().cast(pl.Int64).alias("spectra"))
    # Every run gets every bin, so a stacked bar or a line has no gap.
    runs = counts.select("run_id").unique()
    bins = pl.DataFrame(
        {"bin_start": list(range(0, TOP_BIN + BIN_WIDTH, BIN_WIDTH))},
        schema={"bin_start": pl.Int64},
    )
    grid = runs.join(bins, how="cross")
    out = (
        grid.join(counts, on=["run_id", "bin_start"], how="left")
        .with_columns(pl.col("spectra").fill_null(0))
        .with_columns(
            (pl.col("spectra") / pl.col("spectra").sum().over("run_id")).round(5).alias("fraction"),
            pl.col("bin_start").map_elements(_label, return_dtype=pl.Utf8).alias("peaks"),
        )
    )
    group_name, lookup = group_lookup(sources.get("hub"), params)
    out = out.join(lookup, on="run_id", how="left").with_columns(
        pl.col(group_name).fill_null("Unassigned" if group_name != NO_GROUP_COL else NO_GROUP_VALUE)
    )
    return out.select("run_id", group_name, *list(OUTPUT_SCHEMA)[1:]).sort(["run_id", "bin_start"])
