"""LILAC's HLA class I and II typing, one row per tumor and called allele.

LILAC (hmftools) types the HLA genes from the germline reads and then looks at
each called allele in the tumor: ``<tumor>.lilac.tsv`` has one row per allele
(two per gene) with the fragments supporting it in the reference, the tumor and
the RNA (total, unique, shared, wildcard), its copy number in the tumor, and
the somatic variants the tumor carries in it by coding effect.

``lost_in_tumor`` flags an allele whose tumor copy number is below 0.5, the
HLA loss of heterozygosity that lets a tumor hide neoantigens that allele would
present. ``somatic_mutations`` sums the per-effect counts except synonymous.
The tumor id is the file name before ``.lilac.tsv``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="alleles",
        glob_pattern="**/*.lilac.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "allele_id": pl.Utf8,
    "sample": pl.Utf8,
    "gene": pl.Utf8,
    "allele": pl.Utf8,
    "ref_fragments": pl.Int64,
    "ref_unique_fragments": pl.Int64,
    "tumor_fragments": pl.Int64,
    "rna_fragments": pl.Int64,
    "tumor_copy_number": pl.Float64,
    "lost_in_tumor": pl.Boolean,
    "somatic_missense": pl.Float64,
    "somatic_nonsense_or_frameshift": pl.Float64,
    "somatic_splice": pl.Float64,
    "somatic_inframe_indel": pl.Float64,
    "somatic_synonymous": pl.Float64,
    "somatic_mutations": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.lilac\.tsv$"
LOSS_CN = 0.5

_INT_COLUMNS = {
    "RefTotal": "ref_fragments",
    "RefUnique": "ref_unique_fragments",
    "TumorTotal": "tumor_fragments",
    "RnaTotal": "rna_fragments",
}
_SOMATIC = {
    "SomaticMissense": "somatic_missense",
    "SomaticNonsenseOrFrameshift": "somatic_nonsense_or_frameshift",
    "SomaticSplice": "somatic_splice",
    "SomaticInframeIndel": "somatic_inframe_indel",
    "SomaticSynonymous": "somatic_synonymous",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["alleles"]
    for raw in [*_INT_COLUMNS, *_SOMATIC, "TumorCopyNumber"]:
        if raw not in df.columns:
            df = df.with_columns(pl.lit(None, pl.Utf8).alias(raw))
    cn = pl.col("TumorCopyNumber").cast(pl.Float64, strict=False)
    out = df.with_row_index("_row").select(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"),
        pl.col("Genes").str.replace(r"^HLA_", "HLA-").alias("gene"),
        pl.col("Allele").alias("allele"),
        pl.col("_row"),
        *[pl.col(raw).cast(pl.Int64, strict=False).alias(out) for raw, out in _INT_COLUMNS.items()],
        cn.alias("tumor_copy_number"),
        (cn < LOSS_CN).alias("lost_in_tumor"),
        *[pl.col(raw).cast(pl.Float64, strict=False).alias(out) for raw, out in _SOMATIC.items()],
    )
    # A homozygous gene lists the same allele twice: number the copies.
    copy = pl.col("_row").rank("ordinal").over(["sample", "allele"]).cast(pl.Utf8)
    return (
        out.with_columns(
            pl.format("{}|{}|{}", pl.col("sample"), pl.col("allele"), copy).alias("allele_id"),
            pl.sum_horizontal(
                [pl.col(c).fill_null(0.0) for c in _SOMATIC.values() if c != "somatic_synonymous"]
            ).alias("somatic_mutations"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "gene", "allele"])
    )
