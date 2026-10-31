"""Mono-allelic expression calls of nf-core/drop: heterozygous SNVs, one row per sample and variant.

DROP's MAE sub-workflow counts the RNA reads that carry each allele of the
heterozygous variants of a sample's DNA genotype, then tests whether one allele
is expressed far more than the other (a binomial test against 0.5, adjusted over
the sample's variants). It writes, under ``processed_results/mae/<group>/``:

    MAE_results_all_<annotation>.tsv.gz   every tested heterozygous SNV
    MAE_results_<annotation>.tsv          the mono-allelic ones
    MAE_results_<annotation>_rare.tsv     those that pass the population frequency cut-offs

This recipe reads the full table, which holds the calls and what they are measured
against, takes the group and the annotation from the path and applies the dashboard's
thresholds (``padj``, ``min_ratio``), so the cut-offs can be tightened without a rerun.
A variant is mono-allelic when its adjusted p-value is at most ``padj`` and one allele
makes up at least ``min_ratio`` of the reads. The two smaller tables are subsets of it
and are not read: a header-only subset (a run with no call) is an empty file, which
the source reader refuses.

Sources:
    all_variants  every tested heterozygous SNV

Params:
    padj       adjusted p-value at or below which a variant is called (default 0.05)
    min_ratio  share of reads the dominant allele needs (default 0.8)

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_COLUMNS = {
    "ID": pl.Utf8,
    "contig": pl.Utf8,
    "position": pl.Utf8,
    "refCount": pl.Utf8,
    "altCount": pl.Utf8,
    "pvalue": pl.Utf8,
    "padj": pl.Utf8,
}

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="all_variants",
        glob_pattern="processed_results/mae/*/MAE_results_all_*.tsv.gz",
        format="tsv",
        input_schema=_COLUMNS,
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "call_id": pl.Utf8,
    "sample": pl.Utf8,
    "gene_name": pl.Utf8,
    "drop_group": pl.Utf8,
    "annotation": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "locus": pl.Utf8,
    "variant_id": pl.Utf8,
    "ref_allele": pl.Utf8,
    "alt_allele": pl.Utf8,
    "ref_count": pl.Int64,
    "alt_count": pl.Int64,
    "total_count": pl.Int64,
    "alt_ratio": pl.Float64,
    "p_value": pl.Float64,
    "padj": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "avg_log_count": pl.Float64,
    "log2fc": pl.Float64,
    "mono_allelic": pl.Boolean,
    "call": pl.Utf8,
    "rare": pl.Boolean,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_type": pl.Utf8,
    "allele_frequency": pl.Float64,
    "max_population_af": pl.Float64,
    "n_variants_in_gene": pl.Int64,
    "cohort_frequency": pl.Float64,
}

_MAX_LOG = 300.0
_NA = ["", "NA", "nan"]
_TRUE = ["true", "t", "1", "yes"]


def _text(df: pl.DataFrame, name: str) -> pl.Expr:
    if name not in df.columns:
        return pl.lit(None, dtype=pl.Utf8)
    text = pl.col(name).cast(pl.Utf8).str.strip_chars()
    return pl.when(text.is_in(_NA)).then(None).otherwise(text)


def _num(df: pl.DataFrame, name: str, dtype: pl.DataType = pl.Float64) -> pl.Expr:
    return _text(df, name).cast(dtype, strict=False)


def _flag(df: pl.DataFrame, name: str) -> pl.Expr:
    return _text(df, name).str.to_lowercase().is_in(_TRUE).fill_null(False)


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """One row per tested heterozygous variant, thresholds applied."""
    p = params or {}
    padj_cut = float(p.get("padj") or 0.05)
    min_ratio = float(p.get("min_ratio") or 0.8)

    raw = sources["all_variants"]

    file_name = pl.col("source_path").str.split("/").list.last()
    parts = pl.col("source_path").str.split("/")
    res = raw.select(
        _text(raw, "ID").alias("sample"),
        pl.coalesce(_text(raw, "gene_name"), pl.lit("intergenic")).alias("gene_name"),
        parts.list.get(2).alias("drop_group"),
        file_name.str.replace(r"^MAE_results_(all_)?", "")
        .str.replace(r"\.tsv(\.gz)?$", "")
        .alias("annotation"),
        _text(raw, "contig").alias("chrom"),
        _num(raw, "position", pl.Int64).alias("start"),
        _text(raw, "variantID").alias("variant_id"),
        _text(raw, "refAllele").alias("ref_allele"),
        _text(raw, "altAllele").alias("alt_allele"),
        _num(raw, "refCount", pl.Int64).alias("ref_count"),
        _num(raw, "altCount", pl.Int64).alias("alt_count"),
        _num(raw, "totalCount", pl.Int64).alias("total_count"),
        _num(raw, "altRatio").alias("alt_ratio"),
        _num(raw, "pvalue").alias("p_value"),
        _num(raw, "padj").alias("padj"),
        _num(raw, "log2FC").alias("log2fc"),
        _flag(raw, "rare").alias("rare"),
        _text(raw, "gene_type").alias("gene_type"),
        _num(raw, "AF").alias("allele_frequency"),
        _num(raw, "MAX_AF").alias("max_population_af"),
        _num(raw, "N_var", pl.Int64).alias("n_variants_in_gene"),
        _num(raw, "cohort_freq").alias("cohort_frequency"),
    ).filter(pl.col("sample").is_not_null() & pl.col("chrom").is_not_null())

    # The ratio falls back to the counts when the table lacks it.
    ratio = pl.coalesce(
        pl.col("alt_ratio"),
        (pl.col("alt_count") / pl.col("total_count")).cast(pl.Float64),
    )
    res = (
        res.with_columns(
            ratio.alias("alt_ratio"),
            (pl.col("start") + 1).alias("end"),
        )
        .with_columns(
            (
                (pl.col("padj") <= padj_cut)
                & (pl.max_horizontal(pl.col("alt_ratio"), 1 - pl.col("alt_ratio")) >= min_ratio)
            )
            .fill_null(False)
            .alias("mono_allelic"),
            pl.col("padj")
            .clip(1e-300, 1.0)
            .log10()
            .abs()
            .clip(0.0, _MAX_LOG)
            .alias("neg_log10_padj"),
            # The MA view's average abundance: log2 of the reads covering the variant.
            (pl.col("total_count").cast(pl.Float64).clip(0.0, None) + 1.0)
            .log(2.0)
            .alias("avg_log_count"),
            (pl.col("chrom") + pl.lit(":") + pl.col("start").cast(pl.Utf8)).alias("locus"),
        )
        .with_columns(
            # One row per sample, position and alternative allele: the key a table selection carries.
            (
                pl.col("sample")
                + pl.lit(":")
                + pl.col("locus")
                + pl.lit(":")
                + pl.col("alt_allele").fill_null("")
            ).alias("call_id"),
        )
        .with_columns(
            pl.when(~pl.col("mono_allelic"))
            .then(pl.lit("biallelic"))
            .when(pl.col("alt_ratio") >= 0.5)
            .then(pl.lit("alternative allele"))
            .otherwise(pl.lit("reference allele"))
            .alias("call")
        )
    )
    head = list(OUTPUT_SCHEMA)
    optional = [c for c in OPTIONAL_OUTPUT_SCHEMA if c in res.columns]
    return res.select(head + optional).sort(["padj", "sample", "start"], nulls_last=True)
