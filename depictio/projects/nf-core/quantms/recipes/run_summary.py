"""One row per run: what was identified and how clean the identifications are.

Built from the tables the other recipes produce, so every figure in it can be traced to
a row-level collection: precursors and peptides from ``quantms_precursors``, protein
groups from ``quantms_proteins`` and the MS2 spectrum count from ``quantms_acquisition``.

* ``precursors`` and ``peptides``: distinct modified-sequence and charge pairs, and distinct
  stripped sequences, identified in the run;
* ``protein_groups``: groups with a quantity in the run;
* ``precursors_per_1000_ms2``: identification yield, precursors per thousand MS2 spectra;
* ``modified_pct`` and ``missed_cleavage_pct``: share of precursors carrying a variable
  modification and share with at least one missed cleavage;
* ``median_abs_rt_error_min``: median absolute gap between the observed and the
  library-predicted retention time;
* ``median_peak_width_min`` and ``median_log10_quantity``: median elution-peak width and
  median normalised precursor quantity.

The group column named by the template's ``group_col`` parameter (the hub's ``condition``
by default) and the hub's short ``run_label`` (condition and replicate, for an axis) are
joined from ``samples``; without a hub the label is the run id.

Output schema (the group column right after ``run_id``):
    run_id : Utf8
    precursors : Int64
    peptides : Int64
    protein_groups : Int64
    ms2_spectra : Int64
    precursors_per_1000_ms2 : Float64
    modified_pct : Float64
    missed_cleavage_pct : Float64
    median_abs_rt_error_min : Float64
    median_peak_width_min : Float64
    median_log10_quantity : Float64
    run_label : Utf8
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

HUB_DC_TAG = "samples"
PRECURSORS_DC_TAG = "quantms_precursors"
PROTEINS_DC_TAG = "quantms_proteins"
ACQUISITION_DC_TAG = "quantms_acquisition"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="precursors",
        dc_ref=PRECURSORS_DC_TAG,
        input_schema={
            "run_id": pl.Utf8,
            "peptide": pl.Utf8,
            "peptidoform": pl.Utf8,
            "charge": pl.Int64,
            "missed_cleavages": pl.Int64,
            "modification_state": pl.Utf8,
            "rt_error_min": pl.Float64,
            "peak_width_min": pl.Float64,
            "log10_quantity": pl.Float64,
        },
    ),
    RecipeSource(
        ref="proteins", dc_ref=PROTEINS_DC_TAG, optional=True, input_schema={"run_id": pl.Utf8}
    ),
    RecipeSource(
        ref="acquisition",
        dc_ref=ACQUISITION_DC_TAG,
        optional=True,
        input_schema={"run_id": pl.Utf8},
    ),
    RecipeSource(ref="hub", dc_ref=HUB_DC_TAG, optional=True, input_schema={"run_id": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "precursors": pl.Int64,
    "peptides": pl.Int64,
    "protein_groups": pl.Int64,
    "ms2_spectra": pl.Int64,
    "precursors_per_1000_ms2": pl.Float64,
    "modified_pct": pl.Float64,
    "missed_cleavage_pct": pl.Float64,
    "median_abs_rt_error_min": pl.Float64,
    "median_peak_width_min": pl.Float64,
    "median_log10_quantity": pl.Float64,
    "run_label": pl.Utf8,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All runs"


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
    prec = sources["precursors"]
    out = prec.group_by("run_id").agg(
        pl.struct("peptidoform", "charge").n_unique().cast(pl.Int64).alias("precursors"),
        pl.col("peptide").n_unique().cast(pl.Int64).alias("peptides"),
        ((pl.col("modification_state") == "Modified").mean() * 100).round(2).alias("modified_pct"),
        ((pl.col("missed_cleavages") > 0).mean() * 100).round(2).alias("missed_cleavage_pct"),
        pl.col("rt_error_min").abs().median().round(4).alias("median_abs_rt_error_min"),
        pl.col("peak_width_min").median().round(4).alias("median_peak_width_min"),
        pl.col("log10_quantity").median().round(4).alias("median_log10_quantity"),
    )

    proteins = sources.get("proteins")
    if proteins is not None and not proteins.is_empty():
        counts = proteins.group_by("run_id").agg(pl.len().cast(pl.Int64).alias("protein_groups"))
    else:
        counts = prec.group_by("run_id").agg(
            pl.col("protein_group").n_unique().cast(pl.Int64).alias("protein_groups")
        )
    out = out.join(counts, on="run_id", how="left")

    acquisition = sources.get("acquisition")
    if acquisition is not None and not acquisition.is_empty():
        out = out.join(acquisition.select("run_id", "ms2_spectra"), on="run_id", how="left")
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Int64).alias("ms2_spectra"))
    out = out.with_columns(
        pl.when(pl.col("ms2_spectra") > 0)
        .then((pl.col("precursors") / pl.col("ms2_spectra") * 1000).round(2))
        .otherwise(None)
        .alias("precursors_per_1000_ms2")
    )

    group_name, lookup = group_lookup(sources.get("hub"), params)
    out = out.join(lookup, on="run_id", how="left").with_columns(
        pl.col(group_name).fill_null("Unassigned" if group_name != NO_GROUP_COL else NO_GROUP_VALUE)
    )
    hub = sources.get("hub")
    if hub is not None and "run_label" in hub.columns:
        labels = hub.select(pl.col("run_id").cast(pl.Utf8), "run_label").unique(
            subset="run_id", keep="first"
        )
        out = out.join(labels, on="run_id", how="left")
    else:
        out = out.with_columns(pl.col("run_id").alias("run_label"))
    out = out.with_columns(pl.col("run_label").fill_null(pl.col("run_id")))
    return out.select("run_id", group_name, *list(OUTPUT_SCHEMA)[1:]).sort("run_id")
