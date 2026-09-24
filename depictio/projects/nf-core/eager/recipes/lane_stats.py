"""One row per sequencing LANE, joining AdapterRemoval's report to the samplesheet.

nf-core/eager 2.x trims and collapses each lane separately, then merges the
lanes into a library before mapping. The AdapterRemoval reports are therefore
the only per-lane numbers the run publishes, and they are the only place the
lane is a real factor: the library hub collapses the six lanes of this run onto
two libraries, so a filter sourced there cannot see them.

The reports do not name their lane either. eager names them after the FASTQ it
trimmed plus the samplesheet's ``Lane`` column::

    input R1  s3://.../ERR1943600_1.fastq.gz   Lane 8
    report    ERR1943600_1.fastq_L8.pe.settings

so the join key is rebuilt from the samplesheet rather than parsed out of the
report name, which keeps it exact. A report the samplesheet cannot explain
falls back to matching on the run accession (the file name's first
underscore-separated token), so a hand-written samplesheet with a slightly
different R1 spelling still lands its rows rather than dropping them silently.
The fallback carries the library, sample and sequencing columns only: the lane
itself is read off the report id's own ``_L<n>`` suffix, so two lanes of one
accession keep two rows with two lanes instead of collapsing onto the first
samplesheet row of that accession.

Sources:
    lanes        the ``adapterremoval_settings`` collection (catalog recipe)
    samplesheet  the run's ``--input`` TSV

Output schema:
    lane_id : Utf8                  the AdapterRemoval report's own id
    sample_id : Utf8                Library_ID, the key every other collection uses
    sample_name : Utf8              Sample_Name, the biological sample
    lane : Utf8                     samplesheet Lane
    run_accession : Utf8            sequencing run the lane's reads came from
    seq_type : Utf8                 SE or PE
    strandedness : Utf8             library strandedness (single, double)
    total_read_pairs : Int64        read pairs AdapterRemoval was given
    total_reads : Int64             reads it was given
    discarded_reads : Int64         reads it dropped on quality or length
    collapsed_pairs : Int64         pairs it merged into one sequence
    retained_reads : Int64          sequences it wrote out, the mapper's input
    retained_nucleotides : Int64    bases in them
    average_retained_length : Float64  mean retained length, bp
    collapse_rate : Float64         collapsed pairs over total pairs, 0-1
    discard_rate : Float64          discarded reads over total reads, 0-1
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag of the catalog-tidied AdapterRemoval reports.
SETTINGS_DC_TAG = "adapterremoval_settings"

#: The run's `--input` TSV (one row per lane), copied under DATA_ROOT/input/.
#: eager 2.x does not publish it, so any TSV there is read; several are
#: concatenated, which lets a multi-batch project ship one sheet per batch.
SAMPLESHEET_GLOB = "input/*.tsv"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lanes", dc_ref=SETTINGS_DC_TAG),
    RecipeSource(
        ref="samplesheet",
        glob_pattern=SAMPLESHEET_GLOB,
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "lane_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "sample_name": pl.Utf8,
    "lane": pl.Utf8,
    "run_accession": pl.Utf8,
    "seq_type": pl.Utf8,
    "strandedness": pl.Utf8,
    "total_read_pairs": pl.Int64,
    "total_reads": pl.Int64,
    "discarded_reads": pl.Int64,
    "collapsed_pairs": pl.Int64,
    "retained_reads": pl.Int64,
    "retained_nucleotides": pl.Int64,
    "average_retained_length": pl.Float64,
    "collapse_rate": pl.Float64,
    "discard_rate": pl.Float64,
}

_REQUIRED_SHEET = ["Sample_Name", "Library_ID", "Lane", "SeqType", "Strandedness", "R1"]

# Sheet columns the accession fallback may fill in, and the suffix the join
# gives its copy of them. `lane` is not one of them: the fallback keeps one
# sheet row per accession, and the lane is in the report id anyway.
_FALLBACK_COLUMNS = ["sample_id", "sample_name", "seq_type", "strandedness"]
_FALLBACK_SUFFIX = "_fb"
#: `ERR1943600_1.fastq_L8` -> `8`, eager's lane suffix on the trimmed FASTQ's name.
_LANE_SUFFIX_RE = r"_L(\d+)$"

_NUMERIC = [
    "total_read_pairs",
    "total_reads",
    "discarded_reads",
    "collapsed_pairs",
    "retained_reads",
    "retained_nucleotides",
    "average_retained_length",
    "collapse_rate",
    "discard_rate",
]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per lane, with the library it was merged into."""
    lanes = sources["lanes"]
    sheet = sources["samplesheet"]
    if lanes is None or lanes.is_empty():
        raise ValueError("eager_lane_stats: the adapterremoval_settings collection is empty")
    missing = [c for c in _REQUIRED_SHEET if c not in sheet.columns]
    if missing:
        raise ValueError(f"eager_lane_stats: samplesheet lacks columns {missing}")

    r1_stem = (
        pl.col("R1").str.split("/").list.last().str.replace(r"\.gz$", "").str.replace(r"\.bz2$", "")
    )
    sheet_keys = sheet.select(
        pl.col("Library_ID").alias("sample_id"),
        pl.col("Sample_Name").alias("sample_name"),
        pl.col("Lane").cast(pl.Utf8).alias("lane"),
        pl.col("SeqType").alias("seq_type"),
        pl.col("Strandedness").alias("strandedness"),
        r1_stem.str.split("_").list.get(0).alias("run_accession"),
        pl.format("{}_L{}", r1_stem, pl.col("Lane").cast(pl.Utf8)).alias("lane_id"),
    )

    joined = lanes.rename({"sample": "lane_id"}).join(sheet_keys, on="lane_id", how="left")

    # Fallback for a report the samplesheet's R1 spelling could not reach: match
    # on the run accession, which both sides always carry.
    by_accession = sheet_keys.drop("lane_id", "lane").unique(subset=["run_accession"], keep="first")
    joined = (
        joined.with_columns(
            pl.col("lane_id").str.split("_").list.get(0).alias("run_accession_fallback")
        )
        .join(
            by_accession,
            left_on="run_accession_fallback",
            right_on="run_accession",
            how="left",
            suffix=_FALLBACK_SUFFIX,
        )
        .with_columns(
            *[
                pl.coalesce(pl.col(c), pl.col(f"{c}{_FALLBACK_SUFFIX}")).alias(c)
                for c in _FALLBACK_COLUMNS
            ],
            pl.coalesce(pl.col("run_accession"), pl.col("run_accession_fallback")).alias(
                "run_accession"
            ),
        )
    )

    unresolved = joined.get_column("sample_id").null_count()
    if unresolved == joined.height:
        raise ValueError(
            "eager_lane_stats: no AdapterRemoval report could be matched to a "
            "samplesheet row; check that the TSV under input/ "
            "is this run's --input samplesheet"
        )

    return (
        joined.with_columns(
            *[pl.col(c).cast(EXPECTED_SCHEMA[c], strict=False) for c in _NUMERIC],
            pl.coalesce(
                pl.col("lane").cast(pl.Utf8),
                pl.col("lane_id").str.extract(_LANE_SUFFIX_RE, 1),
            ).alias("lane"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample_id", "lane"])
    )
