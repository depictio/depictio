"""Candidate peptides made from variants, nf-core/epitopeprediction.

For VCF input the pipeline annotates the variants with Ensembl VEP and cuts, with
pVACseq, every peptide of each requested length that overlaps the mutation:
the mutated residue of a missense change, the junction of an in-frame indel or
the new sequence of a frameshift. ``variant_peptides/<sample>_length_<k>.tsv``
lists them, one file per sample and length, with the gene, transcript,
consequence, protein change (HGVSp), genomic anchor (``chr:pos:ref:alt``) and
UniProt accession behind each peptide, plus the wild-type peptides added by
``--wild_type``. This recipe stacks them, one row per sample and peptide, with
the sample and the length read from the file name.

Protein and peptide input write no such files.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.epitope_predictions import consequence_label, origin_label

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variant_peptides",
        input_schema={"source_path": pl.Utf8, "sequence": pl.Utf8},
        glob_pattern="variant_peptides/*_length_*.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "quote_char": None},
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "peptide_key": pl.Utf8,
    "sample": pl.Utf8,
    "sequence": pl.Utf8,
    "length": pl.Int64,
    "length_class": pl.Utf8,
    "origin": pl.Utf8,
    "gene": pl.Utf8,
    "transcript": pl.Utf8,
    "consequence": pl.Utf8,
    "HGVSp": pl.Utf8,
    "genomic_anchor": pl.Utf8,
    "uniprot": pl.Utf8,
    "protein_ids": pl.Utf8,
    "source_records": pl.Int64,
    "wildtype": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_FILE_RE = r"([^/]+)_length_(\d+)\.tsv$"
_TEXT_COLUMNS = (
    "gene",
    "transcript",
    "consequence",
    "HGVSp",
    "genomic_anchor",
    "uniprot",
    "protein_ids",
    "counts",
    "peptide_origin",
    "wildtype",
)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["variant_peptides"]
    for column in _TEXT_COLUMNS:
        if column not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
    df = df.with_columns(
        [
            pl.when(pl.col(c).str.strip_chars().is_in(["", "NA"]))
            .then(None)
            .otherwise(pl.col(c).str.strip_chars())
            .alias(c)
            for c in (*_TEXT_COLUMNS, "sequence")
        ]
    ).filter(pl.col("sequence").is_not_null())
    consequences = {
        c: consequence_label(c)
        for c in df.get_column("consequence").unique().drop_nulls().to_list()
    }
    out = df.with_columns(
        pl.col("source_path").str.extract(_FILE_RE, 1).alias("sample"),
        pl.col("sequence").str.len_chars().cast(pl.Int64).alias("length"),
        origin_label(pl.col("peptide_origin")),
        pl.col("consequence").replace_strict(consequences, default=None, return_dtype=pl.Utf8),
        pl.col("counts").cast(pl.Int64, strict=False).alias("source_records"),
    ).with_columns(
        (pl.col("length").cast(pl.Utf8) + "-mer").alias("length_class"),
        (pl.col("sample") + "|" + pl.col("sequence")).alias("peptide_key"),
    )
    return (
        out.unique(subset=["peptide_key"], keep="first", maintain_order=True)
        .select(list(OUTPUT_SCHEMA))
        .sort(["sample", "length", "sequence"])
    )
