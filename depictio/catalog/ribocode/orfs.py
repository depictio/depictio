"""RiboCode ORF calls, one row per library and ORF.

Reads the ``<library>_collapsed.txt`` tables RiboCode writes when ORF
collapsing is on: one row per ORF, already merged across the transcripts that
share its stop codon, with the ORF type (``annotated``, ``uORF``, ``dORF``,
``Overlap_uORF``, ``Overlap_dORF``, ``internal``, ``novel``), the P-sites per
frame and the combined periodicity p-value.

``orf_id`` is ``<chrom>:<strand>:<ORF_gstop>``, the genomic stop coordinate,
which is the same key the ``ribotish/orfs`` recipe builds; ``orf_class`` maps
RiboCode's types onto the classes both recipes share (Annotated CDS, Upstream
ORF, Downstream ORF, Internal ORF, Novel ORF).

Sources: every ``*_collapsed.txt`` under the run root; the library id is the
file name without ``_collapsed.txt``.

Output: see ``EXPECTED_SCHEMA``. ``aa_length`` is ``ORF_length / 3`` (RiboCode
reports the ORF length in nucleotides without the stop codon).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="orfs",
        glob_pattern="**/*_collapsed.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["None", "NA", ""]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "orf_id": pl.Utf8,
    "transcript_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "gene_type": pl.Utf8,
    "chrom": pl.Utf8,
    "strand": pl.Utf8,
    "orf_type": pl.Utf8,
    "orf_class": pl.Utf8,
    "aa_length": pl.Int64,
    "psites_frame0": pl.Int64,
    "adjusted_pvalue": pl.Float64,
}


def orf_class(orf_type: pl.Expr) -> pl.Expr:
    """RiboCode ORF_type to the class shared with the Ribo-TISH recipe."""
    t = orf_type.str.to_lowercase()
    return (
        pl.when(t == "annotated")
        .then(pl.lit("Annotated CDS"))
        .when(t.str.contains("uorf"))
        .then(pl.lit("Upstream ORF"))
        .when(t.str.contains("dorf"))
        .then(pl.lit("Downstream ORF"))
        .when(t == "internal")
        .then(pl.lit("Internal ORF"))
        .otherwise(pl.lit("Novel ORF"))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library and collapsed ORF."""
    df = sources["orfs"].with_columns(
        pl.col("source_path").str.extract(r"([^/]+)_collapsed\.txt$", 1).alias("sample")
    )
    out = df.select(
        pl.col("sample").cast(pl.Utf8),
        pl.format("{}:{}:{}", pl.col("chrom"), pl.col("strand"), pl.col("ORF_gstop")).alias(
            "orf_id"
        ),
        pl.col("transcript_id").cast(pl.Utf8),
        pl.col("gene_id").cast(pl.Utf8),
        pl.col("gene_name").cast(pl.Utf8),
        pl.col("gene_type").cast(pl.Utf8),
        pl.col("chrom").cast(pl.Utf8),
        pl.col("strand").cast(pl.Utf8),
        pl.col("ORF_type").cast(pl.Utf8).alias("orf_type"),
        orf_class(pl.col("ORF_type").cast(pl.Utf8)).alias("orf_class"),
        (pl.col("ORF_length").cast(pl.Int64) // 3).alias("aa_length"),
        pl.col("Psites_sum_frame0").cast(pl.Float64).round(0).cast(pl.Int64).alias("psites_frame0"),
        pl.col("adjusted_pval").cast(pl.Float64).alias("adjusted_pvalue"),
    )
    return (
        out.unique(subset=["sample", "orf_id"], keep="first", maintain_order=True)
        .sort("sample", "orf_id")
        .select(list(EXPECTED_SCHEMA))
    )
