"""Spatially variable genes of every sample, on one schema whatever the statistic.

nf-core/spatialvi's SQUIDPY_SPATIAL_AUTOCORR writes ``adata.uns["moranI"]``
(``--svg_autocorr_method moran``, the default) or ``adata.uns["gearyC"]``
(``geary``) to ``<sample>/data/<sample>_svg.csv``: the gene is the unnamed index
column, then the statistic (``I`` or ``C``), ``pval_norm``, ``var_norm`` and
``pval_norm_fdr_bh``. Permutation columns (``pval_sim``...) appear only when the
module is given ``n_perms``, and are kept when present.

The two statistics point in opposite directions: Moran's I grows with spatial
clustering (about 0 for none), Geary's C shrinks (about 1 for none). The
recipe keeps the raw ``statistic`` and adds ``spatial_score`` (I, or 1 - C), so
a higher score always means a stronger spatial pattern, and ranks genes by it
within each sample.

The sample comes from the path (the file has no sample column)::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*/data/[^/]+_svg\\.csv$'}
      dc_specific_properties:
        format: CSV
        polars_kwargs:
          include_file_paths: source_path

Gene names are the AnnData var names of the run: Ensembl gene ids on a Space
Ranger reference read by spatialdata-io, symbols only when the reference
carries them as var names.

Output schema:
    sample : Utf8             <sample>/data/<sample>_svg.csv
    gene : Utf8               var name of the gene
    gene_uid : Utf8           "<sample>:<gene>", unique over the run
    method : Utf8             moran | geary
    statistic : Float64       Moran's I or Geary's C as written
    spatial_score : Float64   I, or 1 - C: higher = more spatially structured
    pval : Float64            normal-approximation p-value (pval_norm)
    qval : Float64            Benjamini-Hochberg q-value (pval_norm_fdr_bh)
    neg_log10_qval : Float64  -log10(qval), capped at 300
    rank : Int64              1 = strongest spatial pattern of the sample
    significant : Utf8        "q below 0.05" | "not significant"
    significant_flag : Int64  1 when qval is below 0.05 (a column a sum card reads)
"""

from __future__ import annotations

import math

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "squidpy_svg_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="svg", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "gene": pl.Utf8,
    "gene_uid": pl.Utf8,
    "method": pl.Utf8,
    "statistic": pl.Float64,
    "spatial_score": pl.Float64,
    "pval": pl.Float64,
    "qval": pl.Float64,
    "neg_log10_qval": pl.Float64,
    "rank": pl.Int64,
    "significant": pl.Utf8,
    "significant_flag": pl.Int64,
}

#: Conventional false discovery rate, not a run-specific threshold.
FDR = 0.05
_Q_FLOOR = 1e-300
_SAMPLE_RE = r"(?:^|/)([^/]+)/data/[^/]+_svg\.csv$"
_FILE_SAMPLE_RE = r"(?:^|/)([^/]+)_svg\.csv$"


def _gene_column(columns: list[str]) -> str:
    for name in ("", "gene", "Unnamed: 0", "index", "column_1"):
        if name in columns:
            return name
    return columns[0]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["svg"]
    if "source_path" not in df.columns:
        raise ValueError(
            "squidpy_spatial_autocorr: input has no 'source_path' column, the raw data "
            "collection must be scanned with polars_kwargs.include_file_paths"
        )
    stat_col, method, score = (
        ("I", "moran", pl.col("I"))
        if "I" in df.columns
        else ("C", "geary", 1 - pl.col("C"))
        if "C" in df.columns
        else (None, None, None)
    )
    if stat_col is None or score is None:
        raise ValueError(
            "squidpy_spatial_autocorr: neither a Moran's I ('I') nor a Geary's C ('C') column"
        )
    qcol = "pval_norm_fdr_bh" if "pval_norm_fdr_bh" in df.columns else "pval_norm"
    path = pl.col("source_path").cast(pl.Utf8).str.replace_all(r"\\", "/")
    q = pl.col(qcol).cast(pl.Float64, strict=False)
    result = df.select(
        pl.coalesce(path.str.extract(_SAMPLE_RE, 1), path.str.extract(_FILE_SAMPLE_RE, 1)).alias(
            "sample"
        ),
        pl.col(_gene_column(df.columns)).cast(pl.Utf8).alias("gene"),
        pl.lit(method).alias("method"),
        pl.col(stat_col).cast(pl.Float64, strict=False).alias("statistic"),
        score.cast(pl.Float64, strict=False).alias("spatial_score"),
        pl.col("pval_norm").cast(pl.Float64, strict=False).alias("pval"),
        q.alias("qval"),
        (-(q.clip(lower_bound=_Q_FLOOR).log(base=10)))
        .clip(upper_bound=-math.log10(_Q_FLOOR))
        .alias("neg_log10_qval"),
    ).filter(pl.col("gene").is_not_null())
    if result.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            "squidpy_spatial_autocorr: a row's source_path does not look like "
            "'<sample>/data/<sample>_svg.csv'"
        )
    significant = pl.col("qval") < FDR
    result = result.with_columns(
        pl.concat_str([pl.col("sample"), pl.col("gene")], separator=":").alias("gene_uid"),
        pl.col("spatial_score")
        .rank(method="ordinal", descending=True)
        .over("sample")
        .cast(pl.Int64)
        .alias("rank"),
        pl.when(significant)
        .then(pl.lit("q below 0.05"))
        .otherwise(pl.lit("not significant"))
        .alias("significant"),
        significant.fill_null(False).cast(pl.Int64).alias("significant_flag"),
    )
    return result.select(list(EXPECTED_SCHEMA)).sort(["sample", "rank"])
