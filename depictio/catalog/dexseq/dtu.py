"""DEXSeq differential transcript usage (DTU), one row per contrast and transcript.

nf-core/rnasplice's ``dexseq_dtu`` route hands DEXSeq the Salmon transcript
counts (tximport, ``dtuScaledTPM`` by default) with transcripts as the
"features" of each gene, so the test is whether a transcript's share of its
gene changes between the conditions. Per contrast it writes:

* ``DEXSeqResults.<contrast>.tsv``: one row per transcript (``groupID`` the
  gene, ``featureID`` the transcript), p-value, BH adjustment and a
  ``log2fold_<A>_<B>`` column named after the two conditions;
* ``perGeneQValue.<contrast>.tsv``: the gene-level q-value.

The exon route writes the same names as ``.csv``, which is how the two are told
apart. The fold is oriented treatment over control like
``dexseq/exon_genes.py`` (flipped when the contrast reads ``<B>-<A>``).

Sources:
    transcripts  every ``DEXSeqResults.*.tsv`` under the run root.
    genes        every ``perGeneQValue.*.tsv``.

Params:
    fdr          significance cut-off on the q-values (default 0.05).
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="transcripts",
        glob_pattern="**/DEXSeqResults.*.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", "NaN", ""]},
        source_path="source_path",
    ),
    RecipeSource(
        ref="genes",
        glob_pattern="**/perGeneQValue.*.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", "NaN", ""]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "gene_id": pl.Utf8,
    "transcript_id": pl.Utf8,
    "base_mean": pl.Float64,
    "log2fc": pl.Float64,
    "pvalue": pl.Float64,
    "padj": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "gene_padj": pl.Float64,
    "significant": pl.Boolean,
    "gene_significant": pl.Boolean,
    "direction": pl.Utf8,
}

DEFAULT_FDR = 0.05
PADJ_ZERO_NEG_LOG10 = 300.0
_CONTRAST = r"(?:DEXSeqResults|perGeneQValue)\.(.+)\.[ct]sv$"
_FOLD = re.compile(r"^log2fold_(.+)_(.+)$")


def fdr_cutoff(params: dict[str, str] | None) -> float:
    raw = str((params or {}).get("fdr") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_FDR
    return value if 0 < value < 1 else DEFAULT_FDR


def oriented_fold(df: pl.DataFrame) -> pl.Expr:
    """Treatment-over-control ``log2fc`` from the ``log2fold_<A>_<B>`` columns."""
    exprs = []
    for col in df.columns:
        m = _FOLD.match(col)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        value = pl.col(col).cast(pl.Float64, strict=False)
        exprs.append(pl.when(pl.col("contrast") == f"{b}-{a}").then(-value).otherwise(value))
    if not exprs:
        raise ValueError(f"dexseq dtu: no log2fold_* column in {df.columns}")
    return pl.coalesce(exprs)


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Transcript rows with the gene q-value and the significance calls."""
    fdr = fdr_cutoff(params)
    tx = sources["transcripts"].with_columns(
        pl.col("source_path").str.extract(_CONTRAST, 1).alias("contrast")
    )
    tx = tx.select(
        pl.col("contrast"),
        pl.col("groupID").cast(pl.Utf8).alias("gene_id"),
        pl.col("featureID").cast(pl.Utf8).alias("transcript_id"),
        pl.col("exonBaseMean").cast(pl.Float64, strict=False).alias("base_mean"),
        oriented_fold(tx).alias("log2fc"),
        pl.col("pvalue").cast(pl.Float64, strict=False),
        pl.col("padj").cast(pl.Float64, strict=False),
    ).filter(pl.col("padj").is_not_null() & pl.col("log2fc").is_not_null())

    genes = sources["genes"].select(
        pl.col("source_path").str.extract(_CONTRAST, 1).alias("contrast"),
        pl.col("groupID").cast(pl.Utf8).alias("gene_id"),
        pl.col("padj").cast(pl.Float64, strict=False).alias("gene_padj"),
    )
    out = tx.join(genes, on=["contrast", "gene_id"], how="left")
    out = out.with_columns(
        pl.when(pl.col("padj") > 0)
        .then(-pl.col("padj").log10())
        .when(pl.col("padj") == 0)
        .then(pl.lit(PADJ_ZERO_NEG_LOG10))
        .otherwise(None)
        .alias("neg_log10_padj"),
        (pl.col("padj") < fdr).fill_null(False).alias("significant"),
        (pl.col("gene_padj") < fdr).fill_null(False).alias("gene_significant"),
    ).with_columns(
        pl.when(~pl.col("significant"))
        .then(pl.lit("not significant"))
        .when(pl.col("log2fc") > 0)
        .then(pl.lit("up"))
        .otherwise(pl.lit("down"))
        .alias("direction")
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["contrast", "padj"], nulls_last=True)
