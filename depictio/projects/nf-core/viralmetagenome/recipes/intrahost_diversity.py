"""Intra-host diversity along each genome: Shannon entropy of the alleles at a position.

A consensus keeps one base per position; the reads under it may carry more. The
Shannon entropy of the allele frequencies at a position, ``H = -sum(p ln p)``
over the reference allele and every alternative one, is 0 where every read
agrees and rises with a mixed population (ln 2, about 0.69, for two alleles at
half frequency each). Laid along the genome, it shows where a sample carries
within-host variation, or a co-infection, that the consensus hides.

It needs the calls under the consensus threshold too:

* iVar's raw table (``ivar_variants``) keeps every allele it saw at the
  position, minor ones included; it is read when present;
* bcftools' ``*.norm.vcf.gz`` (``mpileup | call --variants-only``, split into
  one allele per record by ``norm --multiallelics -any``) keeps the calls before
  the ``--allele_frequency`` filter; it is read for a run without the iVar table.

The reference allele's share is what the alternative ones leave (``1 - sum``,
floored at 0). Only positions with at least one alternative allele are listed:
a position absent from the table has entropy 0. A call on fewer than
``MIN_DEPTH`` reads is left out, a frequency read off so few reads says little.

Sources:
    ivar     ``ivar_variants``, optional
    vcf      ``variants/bcftools/*/*.norm.vcf.gz``, raw lines, optional
    genomes  ``genomes``, the genome hub, optional (virus and segment)

Output schema:
    genome_id, sample, chrom : Utf8
    pos : Int64
    virus, segment, virus_segment : Utf8
    n_alt_alleles : Int64      alternative alleles at the position
    minor_af : Float64         frequency of the second most frequent allele
    total_dp : Int64           reads at the position
    entropy : Float64          Shannon entropy, natural log
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import (
    VCF_PATH_COL,
    VCF_RAW_COL,
    VCF_RAW_READ_KWARGS,
    vcf_calls,
)

#: Calls on fewer reads than this are left out.
MIN_DEPTH = 10

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="ivar",
        dc_ref="ivar_variants",
        optional=True,
        input_schema={"genome_id": pl.Utf8, "pos": pl.Int64, "af": pl.Float64},
    ),
    RecipeSource(
        ref="vcf",
        glob_pattern="variants/bcftools/*/*.norm.vcf.gz",
        format="csv",
        optional=True,
        read_kwargs=VCF_RAW_READ_KWARGS,
        source_path=VCF_PATH_COL,
        input_schema={VCF_RAW_COL: pl.Utf8, VCF_PATH_COL: pl.Utf8},
    ),
    RecipeSource(
        ref="genomes",
        dc_ref="genomes",
        optional=True,
        input_schema={"genome_id": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome_id": pl.Utf8,
    "sample": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "virus": pl.Utf8,
    "segment": pl.Utf8,
    "virus_segment": pl.Utf8,
    "n_alt_alleles": pl.Int64,
    "minor_af": pl.Float64,
    "total_dp": pl.Int64,
    "entropy": pl.Float64,
}

_CALL_COLS = ["genome_id", "sample", "chrom", "pos", "ref", "alt", "af", "total_dp"]


def _present(frame: pl.DataFrame | None) -> bool:
    return frame is not None and not frame.is_empty()


def position_entropy(calls: pl.DataFrame) -> pl.DataFrame:
    """One row per genome position from one row per alternative allele (``af`` 0 to 1)."""
    alleles = (
        calls.filter(pl.col("af").is_not_null() & (pl.col("af") > 0))
        .with_columns(pl.col("af").clip(upper_bound=1.0))
        .unique(subset=["genome_id", "chrom", "pos", "alt"], keep="first")
    )
    per_pos = alleles.group_by("genome_id", "sample", "chrom", "pos").agg(
        pl.col("af").alias("alt_afs"),
        pl.col("total_dp").max().alias("total_dp"),
    )
    ref_af = (1.0 - pl.col("alt_afs").list.sum()).clip(lower_bound=0.0)
    freqs = pl.concat_list([pl.col("alt_afs"), ref_af])
    # Allele frequencies of several alleles can sum past 1 by rounding: renormalise.
    probs = freqs.list.eval(pl.element() / pl.element().sum())
    entropy = probs.list.eval(
        pl.when(pl.element() > 0).then(-pl.element() * pl.element().log()).otherwise(0.0)
    ).list.sum()
    minor = freqs.list.sort(descending=True).list.get(1, null_on_oob=True)
    return per_pos.with_columns(
        pl.col("alt_afs").list.len().cast(pl.Int64).alias("n_alt_alleles"),
        minor.round(4).alias("minor_af"),
        entropy.round(4).alias("entropy"),
    ).drop("alt_afs")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    ivar = sources.get("ivar")
    vcf = sources.get("vcf")
    if _present(ivar):
        calls = ivar.select([c for c in _CALL_COLS if c in ivar.columns])
    elif _present(vcf):
        calls = vcf_calls(vcf).select(_CALL_COLS)
    else:
        raise ValueError(
            "viralmetagenome intrahost_diversity: neither the iVar table nor a bcftools VCF was found"
        )
    calls = calls.filter(pl.col("total_dp").is_null() | (pl.col("total_dp") >= MIN_DEPTH))
    out = position_entropy(calls)
    if out.is_empty():
        raise ValueError("viralmetagenome intrahost_diversity: no call with an allele frequency")
    genomes = sources.get("genomes")
    hub = [
        c
        for c in ("virus", "segment", "virus_segment")
        if _present(genomes) and c in genomes.columns
    ]
    if hub:
        out = out.join(
            genomes.select("genome_id", *hub).unique(subset="genome_id"), on="genome_id", how="left"
        )
    for col, dtype in OUTPUT_SCHEMA.items():
        if col not in out.columns:
            out = out.with_columns(pl.lit(None, dtype=dtype).alias(col))
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["sample", "genome_id", "chrom", "pos"]
    )
