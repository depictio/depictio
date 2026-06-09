"""Canonical oncoplot DC for nf-core/sarek.

Megatest source: somatic-mode VCFs (Strelka2 / Mutect2 / Manta) annotated with
snpEff or VEP. Convert to MAF-like format using ``vcf2maf`` or a custom Polars
transform, then pivot to the long format below.

Output (canonical oncoplot schema):

    sample_id     : Utf8    (Tumor_Sample_Barcode)
    gene          : Utf8    (Hugo_Symbol)
    mutation_type : Utf8    (Variant_Classification — Missense / Nonsense / Splice / Frame_Shift)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "gene": pl.Utf8,
    "mutation_type": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/sarek megatest somatic VCFs — see module docstring."
    )
