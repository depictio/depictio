"""One row per ATAC sample, derived from the samplesheet the run validated.

nf-core/atacseq 2.x takes a ``sample,fastq_1,fastq_2,replicate[,control,
control_replicate]`` samplesheet and re-publishes it as
``pipeline_info/samplesheet.valid.csv`` with one row per sequencing library.
The validated ``sample`` column is ``<group>_REP<replicate>_T<technical
replicate>``, and every downstream name is built from it: the merged, filtered
library is ``<group>_REP<replicate>.mLb.clN``, and MACS2 stamps exactly that
string into every peak name.

This recipe collapses the library rows into the sample table the dashboard uses
as its hub, and carries BOTH spellings of the sample so the project links can
reach either family of collections:

* ``sample`` (``WT_REP1``) is what the ataqv reports, the deepTools metrics,
  the DESeq2 QC tables and the MultiQC panels call the library;
* ``merged_library`` (``WT_REP1.mLb.clN``) is what the peak calls, the peak QC
  summary, the HOMER annotation and the consensus matrix call it.

The columns of the 1.x recipe (``nf-core/atacseq/recipes/sample_design.py``)
come first and mean the same, so the dashboards bind both versions alike; the
2.x samplesheet adds the read type and the control route.

The control route (``test_controls``) adds a control group and replicate per
row. The validator of 2.1.2 writes the ``control`` header twice on that route
(the first copy empty, the second filled), which polars reads as ``control``
and ``control_duplicated_0``; every such column is coalesced here, so both
routes yield the same schema.

Output schema:
    sample : Utf8           <group>_REP<replicate>, the canonical sample name
    merged_library : Utf8   <sample>.mLb.clN, the merged filtered library
    group : Utf8            design group, the level replicates are merged at
    replicate : Int64       biological replicate number inside the group
    replicate_label : Utf8  the replicate as a label (``REP1``), so a filter can
                            offer it as a factor rather than a numeric range
    read_type : Utf8        paired-end / single-end / mixed
    role : Utf8             control when another sample names this group as
                            its control, sample otherwise
    control : Utf8          <control group>_REP<control replicate>, empty
                            without a control
    n_libraries : Int64     sequencing libraries merged into the sample
    libraries : Utf8        those library ids, comma separated
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Suffix atacseq 2.x gives the merged, filtered library BAM, and therefore
#: every MACS2 peak name and consensus column derived from it.
MERGE_SUFFIX = ".mLb.clN"

#: ``<sample>_T<technical replicate>`` -> ``<sample>``.
_TECHNICAL_SUFFIX = r"_T\d+$"
#: ``<group>_REP<replicate>`` -> the two parts.
_SAMPLE_PATTERN = r"^(?<group>.+)_REP(?<replicate>\d+)$"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        glob_pattern="**/pipeline_info/samplesheet.valid.csv",
        format="CSV",
        input_schema={"sample": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "merged_library": pl.Utf8,
    "group": pl.Utf8,
    "replicate": pl.Int64,
    "replicate_label": pl.Utf8,
    "read_type": pl.Utf8,
    "role": pl.Utf8,
    "control": pl.Utf8,
    "n_libraries": pl.Int64,
    "libraries": pl.Utf8,
}


def _blank_to_null(column: str) -> pl.Expr:
    stripped = pl.col(column).cast(pl.Utf8).str.strip_chars()
    return pl.when(stripped == "").then(None).otherwise(stripped)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Collapse the library-level samplesheet into one row per sample."""
    sheet = sources["samplesheet"]
    if "sample" not in sheet.columns:
        raise ValueError(f"atacseq sample_design: samplesheet lacks 'sample' (has {sheet.columns})")

    # `control`, plus the `control_duplicated_<n>` copies the duplicated header
    # produces on the control route: the last non-empty one wins.
    control_cols = [
        c for c in sheet.columns if c == "control" or c.startswith("control_duplicated")
    ]
    control_group = (
        pl.coalesce([_blank_to_null(c) for c in reversed(control_cols)])
        if control_cols
        else pl.lit(None, dtype=pl.Utf8)
    )
    control_replicate = (
        _blank_to_null("control_replicate")
        if "control_replicate" in sheet.columns
        else pl.lit(None, dtype=pl.Utf8)
    )
    single_end = (
        _blank_to_null("single_end") if "single_end" in sheet.columns else pl.lit(None, pl.Utf8)
    )

    libraries = (
        sheet.select(
            _blank_to_null("sample").alias("library_id"),
            single_end.alias("single_end"),
            pl.when(control_group.is_not_null() & control_replicate.is_not_null())
            .then(control_group + pl.lit("_REP") + control_replicate)
            .otherwise(control_group)
            .alias("control"),
        )
        .filter(pl.col("library_id").is_not_null())
        .with_columns(pl.col("library_id").str.replace(_TECHNICAL_SUFFIX, "").alias("sample"))
    )

    samples = (
        libraries.group_by("sample")
        .agg(
            pl.len().cast(pl.Int64).alias("n_libraries"),
            pl.col("library_id").sort().str.join(",").alias("libraries"),
            pl.col("single_end").drop_nulls().unique().alias("_single_end"),
            pl.col("control").drop_nulls().first().alias("control"),
        )
        .with_columns(
            (pl.col("sample") + pl.lit(MERGE_SUFFIX)).alias("merged_library"),
            pl.col("sample").str.extract(_SAMPLE_PATTERN, 1).alias("group"),
            pl.col("sample").str.extract(_SAMPLE_PATTERN, 2).cast(pl.Int64).alias("replicate"),
            pl.when(pl.col("_single_end").list.len() > 1)
            .then(pl.lit("mixed"))
            .when(pl.col("_single_end").list.first() == "1")
            .then(pl.lit("single-end"))
            .when(pl.col("_single_end").list.first() == "0")
            .then(pl.lit("paired-end"))
            .otherwise(pl.lit(None, dtype=pl.Utf8))
            .alias("read_type"),
        )
        # A samplesheet that does not follow the <group>_REP<n> convention still
        # yields a usable hub: the sample is its own group, the replicate unknown.
        .with_columns(
            pl.col("group").fill_null(pl.col("sample")),
            pl.format("REP{}", pl.col("replicate")).alias("replicate_label"),
        )
    )

    control_groups = (
        samples.select(pl.col("control").str.replace(r"_REP\d+$", ""))
        .drop_nulls()
        .to_series()
        .unique()
        .to_list()
    )
    samples = samples.with_columns(
        pl.when(pl.col("group").is_in(control_groups))
        .then(pl.lit("control"))
        .otherwise(pl.lit("sample"))
        .alias("role"),
        pl.col("control").cast(pl.Utf8),
        pl.col("read_type").cast(pl.Utf8),
    )
    return samples.select(list(OUTPUT_SCHEMA)).sort("sample")
