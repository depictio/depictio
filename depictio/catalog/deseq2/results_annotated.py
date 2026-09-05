"""Annotated DESeq2 results: statistics joined to the gene annotation.

nf-core/differentialabundance joins each contrast's DESeq2 table to the
GTF-derived feature table and publishes ``<contrast>_deseq2.annotated.tsv`` (the
statistics columns followed by ``chromosome``, ``start``, ``end``, ``gene_name``,
``gene_biotype`` and the other GTF attributes). This recipe keeps the columns the
genome-level renders need (Manhattan, lollipop, biotype bars) and drops features
the GTF did not annotate, since they have no coordinates to draw.

Input: the ``deseq2_results_annotated_raw`` data collection, a recursive Table
scan of the per-contrast files, declared exactly like ``results_long.py``'s raw
DC but matching ``.*_deseq2\\.annotated\\.tsv$``::

    dc_specific_properties:
      format: TSV
      polars_kwargs:
        separator: "\\t"
        null_values: ["NA", "NaN", ""]
        include_file_paths: source_path   # carries the contrast id
        infer_schema_length: 0            # chromosome mixes 1..19 with MT/X/Y

``infer_schema_length: 0`` is required here, not optional: polars infers
``chromosome`` as Int64 from the first rows and then fails on ``MT``. Every
column arrives as Utf8 and is recast below.

The contrast is derived from the file name exactly as in ``results_long.py``
(``Condition_genotype_WT_KO_study_deseq2.annotated.tsv`` ->
``Condition_genotype_WT_KO_study``).

Output schema:
    contrast : Utf8, gene_id : Utf8, gene_name : Utf8
    chromosome : Utf8, start : Int64, end : Int64, gene_biotype : Utf8
    base_mean, log2fc, lfc_se, pvalue, padj, neg_log10_padj : Float64
    significant : Boolean, direction : Utf8
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "deseq2_results_annotated_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="annotated", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "chromosome": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "gene_biotype": pl.Utf8,
    "base_mean": pl.Float64,
    "log2fc": pl.Float64,
    "lfc_se": pl.Float64,
    "pvalue": pl.Float64,
    "padj": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

PADJ_THRESHOLD = 0.05
LFC_THRESHOLD = 1.0
# See results_long.PADJ_ZERO_NEG_LOG10: a padj that underflowed to 0 is capped
# rather than sent to +inf (recipes may not import each other; shared helpers
# belong in depictio/recipes/lib).
PADJ_ZERO_NEG_LOG10 = 300.0
SOURCE_PATH_COL = "source_path"

_ALIASES: dict[str, tuple[str, ...]] = {
    "gene_id": ("gene_id", "feature_id", "gene", "geneid", "feature", "id"),
    "gene_name": ("gene_name", "symbol", "external_gene_name", "name"),
    "chromosome": ("chromosome", "chr", "chrom", "seqnames", "seqname", "contig"),
    "start": ("start", "gene_start", "start_position"),
    "end": ("end", "gene_end", "end_position"),
    "gene_biotype": ("gene_biotype", "biotype", "gene_type", "transcript_biotype"),
    "base_mean": ("basemean", "base_mean"),
    "log2fc": ("log2foldchange", "log2fc", "log2_fold_change", "lfc", "logfc"),
    "lfc_se": ("lfcse", "lfc_se"),
    "pvalue": ("pvalue", "p_value", "pval"),
    "padj": ("padj", "p_adj", "padjust", "qvalue", "q_value", "fdr", "adj_p_val"),
}

_ANNOTATED_SUFFIX_RE = re.compile(r"_?deseq2\.annotated.*$|\.deseq2\.results.*$", re.IGNORECASE)


def _norm(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", name.strip().lower()).strip("_")


def _resolve_columns(columns: list[str]) -> dict[str, str]:
    normalised = {_norm(c): c for c in columns}
    found: dict[str, str] = {}
    for canonical, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normalised and normalised[alias] not in found.values():
                found[canonical] = normalised[alias]
                break
    return found


def contrast_from_path(path: str) -> str:
    basename = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    stem = _ANNOTATED_SUFFIX_RE.sub("", basename).strip("_. ")
    return stem or "all"


def _to_float(df: pl.DataFrame, col: str) -> pl.DataFrame:
    if df[col].dtype == pl.Utf8:
        return df.with_columns(
            pl.when(pl.col(col).str.to_uppercase().is_in(["NA", "NAN", ""]))
            .then(None)
            .otherwise(pl.col(col))
            .cast(pl.Float64, strict=False)
            .alias(col)
        )
    return df.with_columns(pl.col(col).cast(pl.Float64, strict=False))


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Concatenated annotated tables -> genome-ready long table."""
    df = sources["annotated"]
    str_cols = [c for c, dt in df.schema.items() if dt == pl.Utf8]
    if str_cols:
        df = df.with_columns([pl.col(c).str.strip_chars(" \t\r\n") for c in str_cols])

    columns = _resolve_columns(df.columns)
    missing = [
        c for c in ("gene_id", "chromosome", "start", "log2fc", "pvalue") if c not in columns
    ]
    if missing:
        raise ValueError(
            f"deseq2 annotated results: could not find columns for {missing} in {df.columns}"
        )

    if SOURCE_PATH_COL in df.columns:
        df = df.with_columns(
            pl.col(SOURCE_PATH_COL)
            .cast(pl.Utf8)
            .map_elements(contrast_from_path, return_dtype=pl.Utf8)
            .alias("contrast")
        ).drop(SOURCE_PATH_COL)
    elif "contrast" in df.columns:
        df = df.with_columns(pl.col("contrast").cast(pl.Utf8))
    else:
        df = df.with_columns(pl.lit("all").alias("contrast"))

    rename = {src: dst for dst, src in columns.items() if src != dst and src in df.columns}
    df = df.rename(rename)

    for col in ("gene_name", "gene_biotype", "end"):
        if col not in df.columns:
            dtype = pl.Int64 if col == "end" else pl.Utf8
            df = df.with_columns(pl.lit(None, dtype=dtype).alias(col))
    for col in ("base_mean", "lfc_se", "padj"):
        if col not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias(col))
    for col in ("base_mean", "log2fc", "lfc_se", "pvalue", "padj"):
        df = _to_float(df, col)

    df = df.with_columns(
        pl.col("gene_id").cast(pl.Utf8),
        pl.col("gene_name").cast(pl.Utf8),
        pl.col("chromosome").cast(pl.Utf8),
        pl.col("gene_biotype").cast(pl.Utf8),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
    )

    # Only annotated features can be placed on the genome.
    df = df.filter(
        pl.col("gene_id").is_not_null()
        & pl.col("chromosome").is_not_null()
        & pl.col("start").is_not_null()
    )
    # A feature without a symbol keeps its id as label so hover text never blanks.
    df = df.with_columns(pl.col("gene_name").fill_null(pl.col("gene_id")))

    lfc = pl.col("log2fc")
    padj = pl.col("padj")
    is_sig = (padj < PADJ_THRESHOLD) & (lfc.abs() >= LFC_THRESHOLD)
    df = df.with_columns(
        pl.when(padj.is_not_null() & (padj > 0))
        .then(pl.min_horizontal(-padj.log10(), pl.lit(PADJ_ZERO_NEG_LOG10)))
        .when(padj == 0)
        .then(pl.lit(PADJ_ZERO_NEG_LOG10))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("neg_log10_padj"),
        is_sig.fill_null(False).alias("significant"),
        pl.when(is_sig & (lfc > 0))
        .then(pl.lit("up"))
        .when(is_sig & (lfc < 0))
        .then(pl.lit("down"))
        .otherwise(pl.lit("not significant"))
        .alias("direction"),
    )

    return df.select(list(EXPECTED_SCHEMA)).sort(["contrast", "chromosome", "start"])
