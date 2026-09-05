"""One row per ATAC sample, derived from the design sheet the run wrote.

nf-core/atacseq 1.2.x is a DSL1 pipeline: it takes a ``group,replicate,fastq_1,
fastq_2`` design and re-publishes it as ``pipeline_info/design_reads.csv`` with
one row per sequencing library, whose ``sample_id`` it builds as
``<group>_R<replicate>_T<technical replicate>``. Everything downstream is named
off that: the merged, filtered library is ``<group>_R<replicate>.mLb.clN``, and
MACS2 stamps exactly that string into every peak name.

This recipe collapses the library rows into the sample table the dashboard uses
as its hub, and carries BOTH spellings of the sample so the project links can
reach either family of collections:

* ``sample`` (``GM12878_FAST_R1``) is what the peak-QC summary, the ataqv
  reports and the MultiQC panels call the library;
* ``merged_library`` (``GM12878_FAST_R1.mLb.clN``) is what the peak calls, the
  HOMER annotation and the consensus matrix call it.

``group`` is the level the DESeq2 contrasts are built on, which is why it is the
second filter in the dashboard's left rail.

Output schema:
    sample : Utf8           <group>_R<replicate>, the canonical sample name
    merged_library : Utf8   <sample>.mLb.clN, the merged filtered library
    group : Utf8            design group; the DESeq2 contrast level
    replicate : Int64       biological replicate number inside the group
    n_libraries : Int64     sequencing libraries merged into the sample
    libraries : Utf8        those library ids, comma separated
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Suffix atacseq 1.2.x gives the merged, filtered library BAM, and therefore
#: every MACS2 peak name and consensus column derived from it.
MERGE_SUFFIX = ".mLb.clN"

#: ``<sample>_T<technical replicate>`` -> ``<sample>``.
_TECHNICAL_SUFFIX = r"_T\d+$"
#: ``<group>_R<replicate>`` -> the two parts.
_SAMPLE_PATTERN = r"^(?<group>.+)_R(?<replicate>\d+)$"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="design",
        glob_pattern="**/design_reads.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "merged_library": pl.Utf8,
    "group": pl.Utf8,
    "replicate": pl.Int64,
    "n_libraries": pl.Int64,
    "libraries": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Collapse the library-level design sheet into one row per sample."""
    design = sources["design"]
    if "sample_id" not in design.columns:
        raise ValueError(
            f"atacseq sample_design: design sheet lacks 'sample_id' (has {design.columns})"
        )

    libraries = design.select(
        pl.col("sample_id").cast(pl.Utf8).str.strip_chars().alias("library_id")
    ).filter(pl.col("library_id").is_not_null() & (pl.col("library_id") != ""))

    libraries = libraries.with_columns(
        pl.col("library_id").str.replace(_TECHNICAL_SUFFIX, "").alias("sample")
    )

    samples = (
        libraries.group_by("sample")
        .agg(
            pl.len().cast(pl.Int64).alias("n_libraries"),
            pl.col("library_id").sort().str.join(",").alias("libraries"),
        )
        .with_columns(
            (pl.col("sample") + pl.lit(MERGE_SUFFIX)).alias("merged_library"),
            pl.col("sample").str.extract(_SAMPLE_PATTERN, 1).alias("group"),
            pl.col("sample").str.extract(_SAMPLE_PATTERN, 2).cast(pl.Int64).alias("replicate"),
        )
    )
    # A design that does not follow the <group>_R<n> convention still yields a
    # usable hub: the sample is its own group and the replicate is unknown.
    samples = samples.with_columns(
        pl.col("group").fill_null(pl.col("sample")),
    )
    return samples.select(list(EXPECTED_SCHEMA)).sort("sample")
