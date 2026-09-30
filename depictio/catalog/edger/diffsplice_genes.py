"""edgeR ``diffSpliceDGE`` differential exon usage, one row per contrast and gene.

nf-core/rnasplice's ``edger_exon`` route fits the featureCounts exon counts with
edgeR and runs ``diffSpliceDGE`` per contrast, which tests each exon's
log-fold-change against the gene's overall one. Per contrast it writes
(``contrast_<contrast>.*.csv``):

* ``usage.gene.csv``: the gene-level F-test (does any exon differ from the
  rest of its gene?) with its FDR;
* ``usage.simes.csv``: the Simes-combined gene-level test and its FDR, the
  more sensitive call when a single exon carries the change;
* ``usage.exon.csv``: one row per exon, its relative log-fold-change and FDR.

The recipe keeps one row per contrast and gene, both gene-level FDRs, and the
exon with the smallest exon FDR (the larger shift breaking ties) as the gene's
effect size, so a gene-level volcano can be drawn. edgeR's ``logFC`` is already
treatment over control (rnasplice builds the contrast as treatment minus
control).

Sources:
    genes  every ``contrast_*.usage.gene.csv`` under the run root.
    simes  every ``contrast_*.usage.simes.csv``.
    exons  every ``contrast_*.usage.exon.csv``.

Params:
    fdr    significance cut-off on the gene F-test FDR (default 0.05).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_READ = {"infer_schema_length": 0, "null_values": ["NA", "NaN", ""]}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="genes",
        glob_pattern="**/contrast_*.usage.gene.csv",
        format="csv",
        read_kwargs=_READ,
        source_path="source_path",
    ),
    RecipeSource(
        ref="simes",
        glob_pattern="**/contrast_*.usage.simes.csv",
        format="csv",
        read_kwargs=_READ,
        source_path="source_path",
    ),
    RecipeSource(
        ref="exons",
        glob_pattern="**/contrast_*.usage.exon.csv",
        format="csv",
        read_kwargs=_READ,
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "gene_id": pl.Utf8,
    "chrom": pl.Utf8,
    "strand": pl.Utf8,
    "exons": pl.Int64,
    "exons_significant": pl.Int64,
    "top_exon": pl.Utf8,
    "log2fc": pl.Float64,
    "abs_log2fc": pl.Float64,
    "f_stat": pl.Float64,
    "fdr": pl.Float64,
    "simes_fdr": pl.Float64,
    "neg_log10_fdr": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
}

DEFAULT_FDR = 0.05
FDR_ZERO_NEG_LOG10 = 300.0
_CONTRAST = r"contrast_(.+)\.usage\.(?:gene|simes|exon)\.csv$"


def fdr_cutoff(params: dict[str, str] | None) -> float:
    raw = str((params or {}).get("fdr") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_FDR
    return value if 0 < value < 1 else DEFAULT_FDR


def _contrast() -> pl.Expr:
    return pl.col("source_path").str.extract(_CONTRAST, 1).alias("contrast")


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Gene-level F-test and Simes FDRs with the gene's most significant exon."""
    fdr = fdr_cutoff(params)
    genes = sources["genes"].select(
        _contrast(),
        pl.col("Geneid").cast(pl.Utf8).alias("gene_id"),
        pl.col("Chr").cast(pl.Utf8).alias("chrom"),
        pl.col("Strand").cast(pl.Utf8).alias("strand"),
        pl.col("NExons").cast(pl.Int64, strict=False).alias("exons"),
        pl.col("gene.F").cast(pl.Float64, strict=False).alias("f_stat"),
        pl.col("FDR").cast(pl.Float64, strict=False).alias("fdr"),
    )
    simes = sources["simes"].select(
        _contrast(),
        pl.col("Geneid").cast(pl.Utf8).alias("gene_id"),
        pl.col("FDR").cast(pl.Float64, strict=False).alias("simes_fdr"),
    )
    exons = (
        sources["exons"]
        .select(
            _contrast(),
            pl.col("Geneid").cast(pl.Utf8).alias("gene_id"),
            (
                pl.col("Chr").cast(pl.Utf8)
                + pl.lit(":")
                + pl.col("Start").cast(pl.Utf8)
                + pl.lit("-")
                + pl.col("End").cast(pl.Utf8)
            ).alias("exon"),
            pl.col("logFC").cast(pl.Float64, strict=False).alias("log2fc"),
            pl.col("FDR").cast(pl.Float64, strict=False).alias("exon_fdr"),
        )
        .filter(pl.col("log2fc").is_not_null())
    )
    per_gene = (
        exons.with_columns(pl.col("log2fc").abs().alias("_abs"))
        .sort(["contrast", "gene_id", "exon_fdr", "_abs"], descending=[False, False, False, True])
        .group_by(["contrast", "gene_id"], maintain_order=True)
        .agg(
            (pl.col("exon_fdr") < fdr).sum().cast(pl.Int64).alias("exons_significant"),
            pl.col("exon").first().alias("top_exon"),
            pl.col("log2fc").first(),
        )
    )
    out = genes.join(simes, on=["contrast", "gene_id"], how="left").join(
        per_gene, on=["contrast", "gene_id"], how="left"
    )
    out = out.with_columns(
        pl.col("exons_significant").fill_null(0),
        pl.col("log2fc").abs().alias("abs_log2fc"),
        pl.when(pl.col("fdr") > 0)
        .then(-pl.col("fdr").log10())
        .when(pl.col("fdr") == 0)
        .then(pl.lit(FDR_ZERO_NEG_LOG10))
        .otherwise(None)
        .alias("neg_log10_fdr"),
        (pl.col("fdr") < fdr).fill_null(False).alias("significant"),
    ).with_columns(
        pl.when(~pl.col("significant"))
        .then(pl.lit("not significant"))
        .when(pl.col("log2fc") > 0)
        .then(pl.lit("up"))
        .otherwise(pl.lit("down"))
        .alias("direction")
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["contrast", "fdr"], nulls_last=True)
