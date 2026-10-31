"""One row per sample from the viralmetagenome samples overview table.

``overview-tables/[<prefix>-]samples_overview.tsv`` is the pipeline's merge of
the MultiQC general statistics of every sample: FastQC before trimming, after
trimming and after host removal, fastp, the Kraken2 host-removal report, QUAST
on the de novo assembly per assembler, the contig clustering summary, the
consensus count and the sample metadata given through ``--metadata``. Its
headers are MultiQC labels (``FastQC (Raw). Seqs (R1,R2)``); this recipe gives
them stable names and units:

* read counts are read pairs (FastQC counts one mate file) except
  ``trimmed_reads``, fastp's count of both mates;
* fastp writes its Q30 and GC rates as fractions, read here as percentages;
* ``host_pct`` is the share of read pairs Kraken2 classified against the host
  database, ``100 - Unclassified``;
* ``retained_pct`` is the share of raw read pairs left after trimming and host
  removal, the reads the assembly and the mappings start from;
* the assembly length and N50 are the longest across the assemblers the run
  used (one ``Quast (<assembler>)`` block each).

A step the run skipped leaves its columns null. The metadata block
(``Sample metadata. <column>``) is passed through as ``meta_<column>``.

Output schema:
    sample : Utf8                   sample id
    raw_read_pairs : Int64          read pairs before trimming (FastQC)
    raw_gc_pct : Float64            GC content before trimming, percent
    raw_dup_pct : Float64           FastQC duplicate share before trimming, percent
    trimmed_reads : Int64           reads (both mates) fastp kept
    q30_pct : Float64               bases at Q30 or better after fastp, percent
    fastp_dup_pct : Float64         fastp duplication estimate, percent
    adapter_pct : Float64           reads with adapter trimmed, percent
    trimmed_read_pairs : Int64      read pairs after trimming (FastQC)
    host_pct : Float64              read pairs classified as host, percent
    host_filtered_read_pairs : Int64  read pairs after host removal (FastQC)
    retained_pct : Float64          host_filtered over raw read pairs, percent
    assembly_length : Int64         de novo assembly length, bp
    assembly_n50 : Int64            de novo assembly N50, bp
    clusters : Int64                contig clusters kept
    removed_clusters : Int64        contig clusters removed (too few reads or too short)
    mean_cluster_size : Float64     contigs per cluster
    singletons : Int64              clusters of one contig
    denovo_consensus : Int64        de novo consensus genomes the sample ended with
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import as_percent, num, sanitise, text

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="overview",
        # The file carries the run prefix, so the glob matches on the suffix.
        glob_pattern="overview-tables/*samples_overview.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "quote_char": '"'},
        input_schema={"sample": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "raw_read_pairs": pl.Int64,
    "raw_gc_pct": pl.Float64,
    "raw_dup_pct": pl.Float64,
    "trimmed_reads": pl.Int64,
    "q30_pct": pl.Float64,
    "fastp_dup_pct": pl.Float64,
    "adapter_pct": pl.Float64,
    "trimmed_read_pairs": pl.Int64,
    "host_pct": pl.Float64,
    "host_filtered_read_pairs": pl.Int64,
    "retained_pct": pl.Float64,
    "assembly_length": pl.Int64,
    "assembly_n50": pl.Int64,
    "clusters": pl.Int64,
    "removed_clusters": pl.Int64,
    "mean_cluster_size": pl.Float64,
    "singletons": pl.Int64,
    "denovo_consensus": pl.Int64,
}

META_PREFIX = "Sample metadata. "
_QUAST_LENGTH = re.compile(r"^Quast \((?P<asm>[^)]+)\)\. Assembly Length")
_QUAST_N50 = re.compile(r"^Quast \((?P<asm>[^)]+)\)\. N50")


def _max_of(df: pl.DataFrame, pattern: re.Pattern[str]) -> pl.Expr:
    cols = [c for c in df.columns if pattern.match(c)]
    if not cols:
        return pl.lit(None, dtype=pl.Int64)
    return pl.max_horizontal([num(df, c, pl.Int64) for c in cols])


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["overview"]
    unclassified = num(df, "Kraken2 (Host-removal). Unclassified")
    out = df.select(
        text(df, "sample").alias("sample"),
        num(df, "FastQC (Raw). Seqs (R1,R2)", pl.Int64).alias("raw_read_pairs"),
        num(df, "FastQC (Raw). GC").alias("raw_gc_pct"),
        num(df, "FastQC (Raw). Dups").round(2).alias("raw_dup_pct"),
        num(df, "fastp. Reads After Filtering (R1+R2)", pl.Int64).alias("trimmed_reads"),
        as_percent(num(df, "fastp. % > Q30")).round(2).alias("q30_pct"),
        num(df, "fastp. % Duplication").round(3).alias("fastp_dup_pct"),
        num(df, "fastp. % Adapter").round(2).alias("adapter_pct"),
        num(df, "FastQC (Post-trimming). Seqs (R1,R2)", pl.Int64).alias("trimmed_read_pairs"),
        (100.0 - unclassified).round(3).alias("host_pct"),
        num(df, "FastQC (post-Host-removal). Seqs (R1,R2)", pl.Int64).alias(
            "host_filtered_read_pairs"
        ),
        _max_of(df, _QUAST_LENGTH).alias("assembly_length"),
        _max_of(df, _QUAST_N50).alias("assembly_n50"),
        num(df, "Cluster Summary. # Clusters", pl.Int64).alias("clusters"),
        num(df, "Cluster Summary. # Removed clusters", pl.Int64).alias("removed_clusters"),
        num(df, "Cluster Summary. Average cluster size").alias("mean_cluster_size"),
        num(df, "Cluster Summary. Number of singletons", pl.Int64).alias("singletons"),
        num(df, "Consensus Count. # Final denovo clusters", pl.Int64).alias("denovo_consensus"),
        *[
            text(df, c).alias(f"meta_{sanitise(c[len(META_PREFIX) :])}")
            for c in df.columns
            if c.startswith(META_PREFIX)
        ],
    ).filter(pl.col("sample").is_not_null())
    # Reads left once trimming and host removal are done; when host removal was
    # skipped, the trimmed reads are what the assembly starts from.
    kept = pl.coalesce(["host_filtered_read_pairs", "trimmed_read_pairs"])
    out = out.with_columns(
        pl.when(pl.col("raw_read_pairs") > 0)
        .then((kept * 100.0 / pl.col("raw_read_pairs")).round(2))
        .otherwise(None)
        .alias("retained_pct"),
    )
    meta = [c for c in out.columns if c.startswith("meta_")]
    return (
        out.select([*(pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()), *meta])
        .unique(subset="sample", keep="first")
        .sort("sample")
    )
