"""Identified precursors of a DIA-NN run: one row per precursor and run.

``diannsummary/diann_report.tsv`` is DIA-NN's main report: one row per precursor
(modified sequence and charge) in every run it was identified in, at the precursor
q-value DIA-NN was told to keep (1% by default). This recipe renames its columns,
converts nothing but the retention-time error, and derives what the dashboard
slices peptides by:

* ``length``: residues of the stripped sequence;
* ``missed_cleavages``: K or R inside the sequence and not followed by P (trypsin
  rule; it says little for another protease);
* ``n_variable_mods`` and ``modification_state``: ``(UniMod:n)`` marks other than
  the fixed carbamidomethylation (UniMod:4);
* ``rt_error_min``: observed minus library-predicted retention time, minutes;
* ``peak_width_min``: width of the elution peak, minutes;
* ``log10_quantity``: log10 of the normalised precursor quantity.

The group column named by the template's ``group_col`` parameter (the hub's
``condition`` by default) is joined from ``samples``, so figures colour by it.

Output schema (the group column right after ``run_id``):
    run_id : Utf8
    protein_group : Utf8            DIA-NN protein group (accessions, ';'-joined)
    protein_name : Utf8             entry names of the group
    genes : Utf8
    peptide : Utf8                  stripped sequence
    peptidoform : Utf8              sequence with its modifications
    charge : Int64
    charge_state : Utf8             e.g. 2+
    length : Int64
    missed_cleavages : Int64
    n_variable_mods : Int64
    modification_state : Utf8       Modified or Unmodified
    specificity : Utf8              Proteotypic or Shared
    q_value : Float64               precursor q-value in the run
    pg_q_value : Float64            protein-group q-value in the run
    cscore : Float64
    evidence : Float64
    spectrum_similarity : Float64
    ms1_profile_corr : Float64
    rt_min : Float64
    predicted_rt_min : Float64
    rt_error_min : Float64
    peak_width_min : Float64
    quantity_quality : Float64
    log10_quantity : Float64
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

HUB_DC_TAG = "samples"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="report",
        path="diannsummary/diann_report.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 20000, "null_values": ["NA"]},
        input_schema={
            "Run": pl.Utf8,
            "Protein.Group": pl.Utf8,
            "Protein.Names": pl.Utf8,
            "Genes": pl.Utf8,
            "Stripped.Sequence": pl.Utf8,
            "Modified.Sequence": pl.Utf8,
            "Precursor.Charge": pl.Int64,
            "Q.Value": pl.Float64,
            "PG.Q.Value": pl.Float64,
            "CScore": pl.Float64,
            "Evidence": pl.Float64,
            "Spectrum.Similarity": pl.Float64,
            "Ms1.Profile.Corr": pl.Float64,
            "RT": pl.Float64,
            "RT.Start": pl.Float64,
            "RT.Stop": pl.Float64,
            "Predicted.RT": pl.Float64,
            "Proteotypic": pl.Int64,
            "Quantity.Quality": pl.Float64,
            "Precursor.Normalised": pl.Float64,
        },
    ),
    RecipeSource(ref="hub", dc_ref=HUB_DC_TAG, optional=True, input_schema={"run_id": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "protein_group": pl.Utf8,
    "protein_name": pl.Utf8,
    "genes": pl.Utf8,
    "peptide": pl.Utf8,
    "peptidoform": pl.Utf8,
    "charge": pl.Int64,
    "charge_state": pl.Utf8,
    "length": pl.Int64,
    "missed_cleavages": pl.Int64,
    "n_variable_mods": pl.Int64,
    "modification_state": pl.Utf8,
    "specificity": pl.Utf8,
    "q_value": pl.Float64,
    "pg_q_value": pl.Float64,
    "cscore": pl.Float64,
    "evidence": pl.Float64,
    "spectrum_similarity": pl.Float64,
    "ms1_profile_corr": pl.Float64,
    "rt_min": pl.Float64,
    "predicted_rt_min": pl.Float64,
    "rt_error_min": pl.Float64,
    "peak_width_min": pl.Float64,
    "quantity_quality": pl.Float64,
    "log10_quantity": pl.Float64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All runs"
FIXED_MOD = "(UniMod:4)"


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
    report = sources["report"]
    seq = pl.col("Stripped.Sequence")
    # K or R that is not the last residue and is not followed by P: mask the KP / RP
    # pairs first, then count what is left before the C-terminus.
    masked = seq.str.replace_all("KP", "XX").str.replace_all("RP", "XX")
    n_marks = pl.col("Modified.Sequence").str.count_matches(r"\(UniMod:\d+\)")
    n_fixed = pl.col("Modified.Sequence").str.count_matches(r"\(UniMod:4\)")
    out = report.select(
        pl.col("Run").cast(pl.Utf8).alias("run_id"),
        pl.col("Protein.Group").alias("protein_group"),
        pl.col("Protein.Names").alias("protein_name"),
        pl.col("Genes").alias("genes"),
        seq.alias("peptide"),
        pl.col("Modified.Sequence").alias("peptidoform"),
        pl.col("Precursor.Charge").cast(pl.Int64).alias("charge"),
        (pl.col("Precursor.Charge").cast(pl.Utf8) + "+").alias("charge_state"),
        seq.str.len_chars().cast(pl.Int64).alias("length"),
        masked.str.slice(0, pl.max_horizontal(seq.str.len_chars() - 1, pl.lit(0)))
        .str.count_matches("[KR]")
        .cast(pl.Int64)
        .alias("missed_cleavages"),
        (n_marks - n_fixed).cast(pl.Int64).alias("n_variable_mods"),
        pl.col("Proteotypic")
        .cast(pl.Int64)
        .map_elements(lambda v: "Proteotypic" if v == 1 else "Shared", return_dtype=pl.Utf8)
        .alias("specificity"),
        pl.col("Q.Value").cast(pl.Float64).alias("q_value"),
        pl.col("PG.Q.Value").cast(pl.Float64).alias("pg_q_value"),
        pl.col("CScore").cast(pl.Float64).alias("cscore"),
        pl.col("Evidence").cast(pl.Float64).alias("evidence"),
        pl.col("Spectrum.Similarity").cast(pl.Float64).alias("spectrum_similarity"),
        pl.col("Ms1.Profile.Corr").cast(pl.Float64).alias("ms1_profile_corr"),
        pl.col("RT").cast(pl.Float64).alias("rt_min"),
        pl.col("Predicted.RT").cast(pl.Float64).alias("predicted_rt_min"),
        (pl.col("RT") - pl.col("Predicted.RT")).round(4).cast(pl.Float64).alias("rt_error_min"),
        (pl.col("RT.Stop") - pl.col("RT.Start")).round(4).cast(pl.Float64).alias("peak_width_min"),
        pl.col("Quantity.Quality").cast(pl.Float64).alias("quantity_quality"),
        pl.when(pl.col("Precursor.Normalised") > 0)
        .then(pl.col("Precursor.Normalised").log10().round(4))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("log10_quantity"),
    ).with_columns(
        pl.when(pl.col("n_variable_mods") > 0)
        .then(pl.lit("Modified"))
        .otherwise(pl.lit("Unmodified"))
        .alias("modification_state")
    )
    group_name, lookup = group_lookup(sources.get("hub"), params)
    out = out.join(lookup, on="run_id", how="left").with_columns(
        pl.col(group_name).fill_null("Unassigned" if group_name != NO_GROUP_COL else NO_GROUP_VALUE)
    )
    ordered = ["run_id", group_name, *[c for c in OUTPUT_SCHEMA if c != "run_id"]]
    return out.select(ordered).sort(["run_id", "protein_group", "peptidoform", "charge"])
