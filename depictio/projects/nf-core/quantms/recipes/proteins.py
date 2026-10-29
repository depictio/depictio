"""Protein-group quantities of a DIA-NN run: one row per protein group and run.

``diannsummary/diann_report.pg_matrix.tsv`` is DIA-NN's protein-group matrix, filtered
at the protein-group q-value and quantified by MaxLFQ: one row per group, one column per
mzML file, a blank where the group was not quantified in the run. This recipe turns it
into a long table with the groups a run did not quantify left out, so a row is a
detection. How many peptides back a group in each run comes from the precursor table.

The group column named by the template's ``group_col`` parameter (the hub's ``condition``
by default) is joined from ``samples``.

Output schema (the group column right after ``run_id``):
    run_id : Utf8
    protein_group : Utf8       DIA-NN protein group (accessions, ';'-joined)
    protein_name : Utf8        entry names of the group
    genes : Utf8
    description : Utf8         description of the first protein
    intensity : Float64        MaxLFQ intensity
    log2_intensity : Float64
    peptides : Int64           distinct peptide sequences the run identified for the group
    precursors : Int64         distinct precursors the run identified for the group
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

PRECURSORS_DC_TAG = "quantms_precursors"
HUB_DC_TAG = "samples"
_ID_COLUMNS = (
    "Protein.Group",
    "Protein.Ids",
    "Protein.Names",
    "Genes",
    "First.Protein.Description",
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="matrix",
        path="diannsummary/diann_report.pg_matrix.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 20000, "null_values": ["NA"]},
        input_schema={"Protein.Group": pl.Utf8, "Protein.Names": pl.Utf8, "Genes": pl.Utf8},
    ),
    RecipeSource(
        ref="precursors",
        dc_ref=PRECURSORS_DC_TAG,
        optional=True,
        input_schema={"run_id": pl.Utf8, "protein_group": pl.Utf8, "peptide": pl.Utf8},
    ),
    RecipeSource(ref="hub", dc_ref=HUB_DC_TAG, optional=True, input_schema={"run_id": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "protein_group": pl.Utf8,
    "protein_name": pl.Utf8,
    "genes": pl.Utf8,
    "description": pl.Utf8,
    "intensity": pl.Float64,
    "log2_intensity": pl.Float64,
    "peptides": pl.Int64,
    "precursors": pl.Int64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All runs"
_RAW_SUFFIX = re.compile(
    r"\.(d\.tar\.gz|d\.tar|d\.zip|mzml\.gz|mzml|raw|d|wiff|mzxml)$", re.IGNORECASE
)


def run_id_of(name: str) -> str:
    """Column or file name without directory or MS extension."""
    base = str(name).rstrip("/").split("/")[-1].split("\\")[-1]
    return _RAW_SUFFIX.sub("", base)


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
    matrix = sources["matrix"]
    run_cols = [c for c in matrix.columns if c not in _ID_COLUMNS]
    if not run_cols:
        raise ValueError("quantms proteins: the protein-group matrix has no run column")
    ids = [c for c in _ID_COLUMNS if c in matrix.columns]
    renames = {c: run_id_of(c) for c in run_cols}
    long = (
        matrix.select(ids + run_cols)
        .with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in run_cols])
        .rename(renames)
        .unpivot(
            index=ids, on=list(renames.values()), variable_name="run_id", value_name="intensity"
        )
        .filter(pl.col("intensity").is_not_null() & (pl.col("intensity") > 0))
    )
    out = long.select(
        pl.col("run_id").cast(pl.Utf8),
        pl.col("Protein.Group").alias("protein_group"),
        pl.col("Protein.Names").alias("protein_name"),
        pl.col("Genes").alias("genes"),
        (
            pl.col("First.Protein.Description")
            if "First.Protein.Description" in long.columns
            else pl.lit(None, dtype=pl.Utf8)
        ).alias("description"),
        pl.col("intensity").cast(pl.Float64),
        pl.col("intensity").log(2).round(4).cast(pl.Float64).alias("log2_intensity"),
    )
    precursors = sources.get("precursors")
    if precursors is not None and not precursors.is_empty():
        counts = precursors.group_by(["run_id", "protein_group"]).agg(
            pl.col("peptide").n_unique().cast(pl.Int64).alias("peptides"),
            pl.len().cast(pl.Int64).alias("precursors"),
        )
        out = out.join(counts, on=["run_id", "protein_group"], how="left")
    else:
        out = out.with_columns(
            pl.lit(None, dtype=pl.Int64).alias("peptides"),
            pl.lit(None, dtype=pl.Int64).alias("precursors"),
        )
    group_name, lookup = group_lookup(sources.get("hub"), params)
    out = out.join(lookup, on="run_id", how="left").with_columns(
        pl.col(group_name).fill_null("Unassigned" if group_name != NO_GROUP_COL else NO_GROUP_VALUE)
    )
    ordered = ["run_id", group_name, *[c for c in OUTPUT_SCHEMA if c != "run_id"]]
    return out.select(ordered).sort(["run_id", "protein_group"])
