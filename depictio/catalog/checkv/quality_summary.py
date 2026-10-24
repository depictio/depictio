"""One row per viral sequence from CheckV's ``quality_summary.tsv``.

``checkv end_to_end`` writes ``quality_summary.tsv`` into one output folder per
input FASTA: the length of each sequence, whether it is a provirus, how many
viral and host genes it carries, its estimated completeness and contamination,
and the MIUViG quality tier those give (Complete, High-quality,
Medium-quality, Low-quality, Not-determined). Completeness is null when the
database holds no close enough genome (``Not-determined``, common on the
minimal test database).

The output folder names the input: nf-core/viralmetagenome writes
``consensus/quality_control/checkv/<sample>/[<prefix>-]<sample>_<reference>/``,
other layouts ``checkv/<sample>/``. ``sample`` is the sample folder (the
grandparent when the parent is a per-input folder) and ``checkv_run`` the
folder itself, both without the run's ``--global_prefix``.

Output schema:
    sample : Utf8               sample id, from the folder layout
    checkv_run : Utf8           CheckV output folder, one per input FASTA
    contig_id : Utf8            sequence id
    contig_length : Int64       sequence length, bp
    provirus : Utf8             Yes when CheckV found a host region around the virus
    proviral_length : Int64     length of the viral region of a provirus, bp
    gene_count : Int64          genes predicted
    viral_genes : Int64         genes hitting a viral protein family
    host_genes : Int64          genes hitting a microbial protein family
    checkv_quality : Utf8       Complete, High-quality, Medium-quality, Low-quality or Not-determined
    miuvig_quality : Utf8       MIUViG tier: High-quality, Genome-fragment...
    completeness : Float64      estimated completeness, percent
    completeness_method : Utf8  how completeness was estimated (AAI, HMM)
    contamination : Float64     estimated host contamination, percent
    kmer_freq : Float64         how often the genome's k-mers repeat (above 1 suggests a concatemer)
    warnings : Utf8             CheckV warnings, semicolon-separated
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import num, strip_global_prefix, text

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        glob_pattern="**/checkv/**/quality_summary.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
        input_schema={
            "contig_id": pl.Utf8,
            "contig_length": pl.Utf8,
            "checkv_quality": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "checkv_run": pl.Utf8,
    "contig_id": pl.Utf8,
    "contig_length": pl.Int64,
    "provirus": pl.Utf8,
    "proviral_length": pl.Int64,
    "gene_count": pl.Int64,
    "viral_genes": pl.Int64,
    "host_genes": pl.Int64,
    "checkv_quality": pl.Utf8,
    "miuvig_quality": pl.Utf8,
    "completeness": pl.Float64,
    "completeness_method": pl.Utf8,
    "contamination": pl.Float64,
    "kmer_freq": pl.Float64,
    "warnings": pl.Utf8,
}


def _ids(path: str) -> list[str]:
    """``[sample, checkv_run]`` read off the folders above ``quality_summary.tsv``."""
    parent = PurePosixPath(path).parent
    run = strip_global_prefix(parent.name)
    grand = parent.parent.name
    if grand and grand.lower() != "checkv":
        return [strip_global_prefix(grand), run]
    return [run, run]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["summary"]
    ids = df["source_path"].map_elements(_ids, return_dtype=pl.List(pl.Utf8))
    out = df.select(
        ids.list.get(0).alias("sample"),
        ids.list.get(1).alias("checkv_run"),
        text(df, "contig_id").alias("contig_id"),
        num(df, "contig_length", pl.Int64).alias("contig_length"),
        text(df, "provirus").alias("provirus"),
        num(df, "proviral_length", pl.Int64).alias("proviral_length"),
        num(df, "gene_count", pl.Int64).alias("gene_count"),
        num(df, "viral_genes", pl.Int64).alias("viral_genes"),
        num(df, "host_genes", pl.Int64).alias("host_genes"),
        text(df, "checkv_quality").alias("checkv_quality"),
        text(df, "miuvig_quality").alias("miuvig_quality"),
        num(df, "completeness").alias("completeness"),
        text(df, "completeness_method").alias("completeness_method"),
        num(df, "contamination").alias("contamination"),
        num(df, "kmer_freq").alias("kmer_freq"),
        text(df, "warnings").alias("warnings"),
    )
    return (
        out.filter(pl.col("contig_id").is_not_null())
        .unique(subset=["sample", "checkv_run", "contig_id"], keep="first")
        .sort(["sample", "checkv_run", "contig_id"])
    )
