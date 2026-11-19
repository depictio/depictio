"""Variant calls of nf-core/viralmetagenome, whichever caller the run used.

The pipeline calls the final variants with ``--variant_caller`` (``ivar``, the
default, or ``bcftools``) and publishes them under ``variants/<caller>/<sample>/``:

* iVar writes its raw table (``*.tsv``, read by the catalog collection
  ``ivar_variants``: depths, p-value, codon change) and a filtered VCF;
* bcftools writes only VCFs: ``*.org.vcf.gz`` straight out of ``mpileup | call``,
  ``*.norm.vcf.gz`` after ``norm``, then ``*.filtered.vcf.gz``, the calls at
  ``FORMAT/AD[:1] / FORMAT/DP >= --allele_frequency`` that make the consensus.

A run with ``--variant_caller bcftools`` therefore has no iVar table, and a
Variants tab built on ``ivar_variants`` alone is pruned whole. This recipe
stacks both under one schema: the iVar rows when the table is there, and the
filtered VCF of every other caller. iVar's own VCF is read only when its table
is missing, so a call is never counted twice. The ``.org`` and ``.norm`` VCFs
are intermediate and left out: the filtered one is what the consensus took.

The keys come from where a file sits (``variants/<caller>/<sample>/
[<prefix>-]<sample>_<reference>...``), the way ``ivar/variants_tsv`` reads
them, so ``genome_id`` matches the genome hub. The genome's virus and segment
follow from the hub (``genomes``) when it is there.

From a VCF: the depth is ``FORMAT/DP`` (else ``INFO/DP``); the alternative depth
``FORMAT/AD[1]`` (bcftools, ``--annotate FORMAT/AD``) or ``FORMAT/ALT_DP`` (iVar);
the allele frequency iVar's ``ALT_FREQ``, else ``AD[1] / (AD[0] + AD[1])``, else
the alternative depth over the depth. Only the first ALT allele of a record is
read, which is how ``bcftools norm --multiallelics -any`` leaves every record.

Sources:
    ivar     ``ivar_variants``, the catalog iVar table, optional
    vcf      ``variants/*/*/*.filtered.vcf.gz``, raw lines, optional
    genomes  ``genomes``, the genome hub, optional
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

_RAW = VCF_RAW_COL
_PATH = VCF_PATH_COL

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
        glob_pattern="variants/*/*/*.filtered.vcf.gz",
        format="csv",
        optional=True,
        read_kwargs=VCF_RAW_READ_KWARGS,
        source_path=_PATH,
        input_schema={_RAW: pl.Utf8, _PATH: pl.Utf8},
    ),
    RecipeSource(
        ref="genomes",
        dc_ref="genomes",
        optional=True,
        input_schema={"genome_id": pl.Utf8, "virus": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome_id": pl.Utf8,
    "sample": pl.Utf8,
    "reference": pl.Utf8,
    "route": pl.Utf8,
    "caller": pl.Utf8,  # iVar or bcftools
    "virus": pl.Utf8,
    "segment": pl.Utf8,
    "virus_segment": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_type": pl.Utf8,
    "variant_key": pl.Utf8,
    "alt_dp": pl.Int64,
    "total_dp": pl.Int64,
    "af": pl.Float64,
    "frequency_class": pl.Utf8,
    "filter": pl.Utf8,
}

_CALLER_IVAR = "ivar"
_CALLER_NAMES = {"ivar": "iVar", "bcftools": "bcftools"}


def _present(frame: pl.DataFrame | None) -> bool:
    return frame is not None and not frame.is_empty()


def _ivar_calls(ivar: pl.DataFrame) -> pl.DataFrame:
    cols = [c for c in OUTPUT_SCHEMA if c in ivar.columns and c != "caller"]
    # The iVar table repeats a call once per overlapping GFF feature.
    return (
        ivar.select(cols)
        .with_columns(pl.lit(_CALLER_IVAR).alias("caller"))
        .unique(subset=["genome_id", "chrom", "pos", "ref", "alt"], keep="first")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    parts: list[pl.DataFrame] = []
    ivar = sources.get("ivar")
    if _present(ivar):
        parts.append(_ivar_calls(ivar))
    vcf = sources.get("vcf")
    if _present(vcf):
        calls = vcf_calls(vcf)
        if parts:
            calls = calls.filter(pl.col("caller") != _CALLER_IVAR)
        if not calls.is_empty():
            parts.append(calls)
    if not parts:
        raise ValueError(
            "viralmetagenome variants: neither the iVar table nor a filtered VCF was found"
        )
    out = pl.concat(
        [p.select([c for c in OUTPUT_SCHEMA if c in p.columns]) for p in parts],
        how="diagonal_relaxed",
    )

    genomes = sources.get("genomes")
    hub = ["virus", "segment", "virus_segment"]
    out = out.drop([c for c in hub if c in out.columns])
    if _present(genomes):
        have = [c for c in hub if c in genomes.columns]
        out = out.join(
            genomes.select("genome_id", *have).unique(subset="genome_id"),
            on="genome_id",
            how="left",
        )
    for col, dtype in OUTPUT_SCHEMA.items():
        if col not in out.columns:
            out = out.with_columns(pl.lit(None, dtype=dtype).alias(col))
    # The caller as its authors spell it, for the tiles that print it.
    out = out.with_columns(pl.col("caller").replace(_CALLER_NAMES).alias("caller"))
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["sample", "genome_id", "pos", "alt"]
    )
