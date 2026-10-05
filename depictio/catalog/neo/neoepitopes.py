"""Neo's scored neoepitopes, one row per tumor and candidate neoepitope.

Neo (hmftools) derives candidate neoepitopes from the tumor's point mutations,
indels and LINX fusions, then scores them against the tumor's LILAC alleles and
its RNA. ``<tumor>.neo.neoepitope.tsv`` has one row per neoepitope: the event
type (``MISSENSE``, ``FRAMESHIFT``, ``INFRAME_FUSION``, ...), the variant, the
gene, the up-stream, novel and down-stream amino acids, the number of peptides
it yields, its RNA support and expected / effective expression (TPM), and the
copy number of the variant behind it. The tumor id is the file name before
``.neo.neoepitope.tsv``; ``neoepitope_id`` (tumor, Neo id) is the record key.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="neo",
        glob_pattern="**/*.neo.neoepitope.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

_COLUMNS: dict[str, tuple[str, type[pl.DataType]]] = {
    "VariantType": ("variant_type", pl.Utf8),
    "VariantInfo": ("variant", pl.Utf8),
    "GeneName": ("gene", pl.Utf8),
    "UpAminoAcids": ("up_amino_acids", pl.Utf8),
    "NovelAminoAcids": ("novel_amino_acids", pl.Utf8),
    "DownAminoAcids": ("down_amino_acids", pl.Utf8),
    "PeptideCount": ("peptides", pl.Int64),
    "RnaFrags": ("rna_fragments", pl.Int64),
    "RnaDepth": ("rna_depth", pl.Int64),
    "ExpectedTpm": ("expected_tpm", pl.Float64),
    "EffectiveTpm": ("effective_tpm", pl.Float64),
    "VariantCopyNumber": ("variant_copy_number", pl.Float64),
    "CopyNumber": ("copy_number", pl.Float64),
    "SubclonalLikelihood": ("subclonal_likelihood", pl.Float64),
}

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "neoepitope_id": pl.Utf8,
    "sample": pl.Utf8,
    **{out: dtype for out, dtype in _COLUMNS.values()},
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.neo\.neoepitope\.tsv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["neo"]
    for raw in _COLUMNS:
        if raw not in df.columns:
            df = df.with_columns(pl.lit(None, pl.Utf8).alias(raw))
    sample = pl.col("source_path").str.extract(_SAMPLE_RE, 1)
    return (
        df.select(
            pl.format("{}|{}", sample, pl.col("NeId")).alias("neoepitope_id"),
            sample.alias("sample"),
            *[
                pl.col(raw).cast(pl.Float64, strict=False).round(0).cast(pl.Int64).alias(out)
                if dtype == pl.Int64
                else (
                    pl.col(raw).cast(pl.Float64, strict=False)
                    if dtype == pl.Float64
                    else pl.when(pl.col(raw).str.strip_chars() == "")
                    .then(None)
                    .otherwise(pl.col(raw))
                ).alias(out)
                for raw, (out, dtype) in _COLUMNS.items()
            ],
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "gene", "neoepitope_id"])
    )
