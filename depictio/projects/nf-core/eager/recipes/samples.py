"""One row per eager LIBRARY, from the TSV samplesheet the run was launched with.

nf-core/eager 2.x's `--input` TSV is one row per sequencing LANE
(`Sample_Name, Library_ID, Lane, ...`): every downstream output (BAM,
DamageProfiler, Qualimap, ...) is published per `Library_ID` after eager merges
its lanes, so that is the hub the sample filter and every project link key on,
not `Sample_Name` (which can carry several libraries).

The sheet is read from any `DATA_ROOT/input/*.tsv`: eager 2.x does not publish
its `--input`, so the run's TSV is copied there by hand.

Output schema:
    sample_id : Utf8        Library_ID, the name every output file uses
    sample_name : Utf8      Sample_Name, the biological sample the library was prepared from
    organism : Utf8         samplesheet Organism
    seq_type : Utf8         SE or PE
    udg_treatment : Utf8    UDG treatment applied before library prep ("none", "half", "full")
    n_lanes : Int64          sequencing lanes merged into the library
    lane_ids : Utf8          those lanes' numbers, comma separated
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: The run's `--input` TSV (one row per lane), copied under DATA_ROOT/input/.
#: eager 2.x does not publish it, so any TSV there is read; several are
#: concatenated, which lets a multi-batch project ship one sheet per batch.
SAMPLESHEET_GLOB = "input/*.tsv"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        glob_pattern=SAMPLESHEET_GLOB,
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "sample_name": pl.Utf8,
    "organism": pl.Utf8,
    "seq_type": pl.Utf8,
    "udg_treatment": pl.Utf8,
    "n_lanes": pl.Int64,
    "lane_ids": pl.Utf8,
}

_REQUIRED = ["Sample_Name", "Library_ID", "Lane", "Organism", "SeqType", "UDG_Treatment"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Collapse the lane rows to one row per library."""
    df = sources["samplesheet"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"eager samples: samplesheet lacks columns {missing}")

    libraries = df.group_by("Library_ID").agg(
        pl.col("Sample_Name").first().alias("sample_name"),
        pl.col("Organism").first().alias("organism"),
        pl.col("SeqType").first().alias("seq_type"),
        pl.col("UDG_Treatment").first().alias("udg_treatment"),
        pl.len().cast(pl.Int64).alias("n_lanes"),
        pl.col("Lane").sort().str.join(",").alias("lane_ids"),
    )
    return (
        libraries.rename({"Library_ID": "sample_id"})
        .select(list(EXPECTED_SCHEMA))
        .sort("sample_id")
    )
