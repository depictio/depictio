"""One row per variant from the raw iVar ``variants`` table, one file per mapping.

``ivar variants`` writes a tab-separated table per BAM before any VCF
conversion: the position, the reference and alternative alleles (an insertion
is ``+<bases>``, a deletion ``-<bases>``), the depth and quality of each allele,
the allele frequency, Fisher's p-value, iVar's ``PASS`` verdict and, when a GFF
was given, the codon and amino acid change of every feature the variant falls
in (one row per feature).

Where the file sits says what was mapped:

* nf-core/viralmetagenome writes
  ``variants/ivar/<sample>/[<prefix>-]<sample>_<reference>[...].tsv``, one table
  per sample and reference (a constraint reference or a de novo cluster); the
  sample is the folder, the reference the rest of the name
  (``depictio.recipes.lib.viralmetagenome.split_mapping_name``);
* nf-core/viralrecon writes ``variants/ivar/<sample>.tsv``; the reference is
  then null and the genome id is the sample.

Rows repeated for each overlapping GFF feature collapse to one variant per
feature; ``variant_key`` (``<chrom>:<pos><ref>><alt>``) names the variant.

Output schema:
    sample : Utf8          sample id
    reference : Utf8       reference the reads were mapped to, null on a one-reference layout
    route : Utf8           constraint or de novo, null on a one-reference layout
    genome_id : Utf8       <sample>_<reference>, the key the consensus collections join on
    chrom : Utf8           reference sequence the variant is on
    pos : Int64            1-based position
    ref : Utf8             reference allele
    alt : Utf8             alternative allele as iVar writes it (+ins, -del)
    variant_type : Utf8    SNV, Insertion or Deletion
    variant_key : Utf8     <chrom>:<pos><ref>><alt>
    ref_dp : Int64         reads supporting the reference allele
    alt_dp : Int64         reads supporting the alternative allele
    total_dp : Int64       reads at the position
    af : Float64           alternative allele frequency, 0 to 1
    frequency_class : Utf8 Fixed (AF at least 0.9), Major (0.5 to 0.9) or Minor (under 0.5)
    alt_qual : Float64     mean base quality of the alternative allele
    pval : Float64         Fisher's exact test p-value
    filter : Utf8          PASS when iVar kept the call, else Filtered
    gff_feature : Utf8     GFF feature the variant falls in, null without a GFF
    aa_change : Utf8       <ref aa><codon position><alt aa>, null outside a feature
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import (
    genome_id,
    num,
    sample_from_path,
    split_mapping_name,
    strip_global_prefix,
    text,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants",
        glob_pattern="variants/ivar/**/*.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "quote_char": None},
        source_path="source_path",
        input_schema={
            "REGION": pl.Utf8,
            "POS": pl.Utf8,
            "REF": pl.Utf8,
            "ALT": pl.Utf8,
            "ALT_FREQ": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "reference": pl.Utf8,
    "route": pl.Utf8,
    "genome_id": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_type": pl.Utf8,
    "variant_key": pl.Utf8,
    "ref_dp": pl.Int64,
    "alt_dp": pl.Int64,
    "total_dp": pl.Int64,
    "af": pl.Float64,
    "frequency_class": pl.Utf8,
    "alt_qual": pl.Float64,
    "pval": pl.Float64,
    "filter": pl.Utf8,
    "gff_feature": pl.Utf8,
    "aa_change": pl.Utf8,
}

# Folders that hold the tables of every sample rather than one sample's.
_TOOL_DIRS = ("ivar", "variants", "intermediate")


def _ids(path: str) -> list[str | None]:
    """``[sample, reference, route, genome_id]`` read off the file's place."""
    stem = PurePosixPath(path).name.removesuffix(".tsv")
    sample = sample_from_path(f"{PurePosixPath(path).parent}/{stem}", _TOOL_DIRS)
    if sample == stem:
        sample = strip_global_prefix(stem)
        return [sample, None, None, sample]
    reference, route, _step = split_mapping_name(stem, sample)
    return [sample, reference, route, genome_id(sample, reference)]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["variants"]
    ids = df["source_path"].map_elements(_ids, return_dtype=pl.List(pl.Utf8))
    alt = text(df, "ALT")
    out = df.select(
        ids.list.get(0).alias("sample"),
        ids.list.get(1).alias("reference"),
        ids.list.get(2).alias("route"),
        ids.list.get(3).alias("genome_id"),
        text(df, "REGION").alias("chrom"),
        num(df, "POS", pl.Int64).alias("pos"),
        text(df, "REF").alias("ref"),
        alt.alias("alt"),
        pl.when(alt.str.starts_with("+"))
        .then(pl.lit("Insertion"))
        .when(alt.str.starts_with("-"))
        .then(pl.lit("Deletion"))
        .otherwise(pl.lit("SNV"))
        .alias("variant_type"),
        num(df, "REF_DP", pl.Int64).alias("ref_dp"),
        num(df, "ALT_DP", pl.Int64).alias("alt_dp"),
        num(df, "TOTAL_DP", pl.Int64).alias("total_dp"),
        num(df, "ALT_FREQ").alias("af"),
        num(df, "ALT_QUAL").alias("alt_qual"),
        num(df, "PVAL").alias("pval"),
        pl.when(text(df, "PASS").str.to_uppercase() == "TRUE")
        .then(pl.lit("PASS"))
        .otherwise(pl.lit("Filtered"))
        .alias("filter"),
        text(df, "GFF_FEATURE").alias("gff_feature"),
        pl.when(text(df, "REF_AA").is_not_null() & text(df, "ALT_AA").is_not_null())
        .then(text(df, "REF_AA") + text(df, "POS_AA").fill_null("") + text(df, "ALT_AA"))
        .otherwise(None)
        .alias("aa_change"),
    ).filter(pl.col("pos").is_not_null())
    out = out.with_columns(
        (
            pl.col("chrom")
            + ":"
            + pl.col("pos").cast(pl.Utf8)
            + pl.col("ref")
            + ">"
            + pl.col("alt")
        ).alias("variant_key"),
        pl.when(pl.col("af") >= 0.9)
        .then(pl.lit("Fixed"))
        .when(pl.col("af") >= 0.5)
        .then(pl.lit("Major"))
        .otherwise(pl.lit("Minor"))
        .alias("frequency_class"),
    )
    return (
        out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .unique(subset=["genome_id", "chrom", "pos", "ref", "alt", "gff_feature"], keep="first")
        .sort(["sample", "genome_id", "pos", "alt"])
    )
