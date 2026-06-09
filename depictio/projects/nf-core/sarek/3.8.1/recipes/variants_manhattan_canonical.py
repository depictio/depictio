"""Canonical Manhattan-track DC for nf-core/sarek.

Megatest source: per-sample joint-call VCF (e.g. ``variant_calling/haplotypecaller/<sample>/<sample>.vcf.gz``)
or the snpEff/VEP-annotated VCF. Use ``cyvcf2`` or ``pyvariantkit`` to stream records.

Output (canonical Manhattan schema, see schemas.py):

    chr      : Utf8
    pos      : Int64       (POS)
    score    : Float64     (e.g. -log10(p) derived from QUAL, or VAF)
    feature  : Utf8        (optional — variant ID / dbSNP)
    effect   : Float64     (optional — signed effect / impact score)
    sample   : Utf8        (carried through for per-sample faceting)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chr": pl.Utf8,
    "pos": pl.Int64,
    "score": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature": pl.Utf8,
    "effect": pl.Float64,
    "sample": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against nf-core/sarek megatest VCFs — see module docstring.")
