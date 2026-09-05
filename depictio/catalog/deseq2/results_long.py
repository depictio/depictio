"""Long DESeq2 results table, one row per (contrast, feature).

``deseq2/differential`` writes one ``<contrast>.deseq2.results.tsv`` per
contrast with the raw DESeq2 ``results()`` columns and no contrast column.
This recipe concatenates them into one tidy frame and normalises the column
vocabulary, so the volcano / MA / QQ / DA-barplot renders bind the same way
whatever pipeline (differentialabundance, chipseq, rnaseq...) produced them.

Input: the ``deseq2_results_raw`` data collection, a recursive Table scan of the
per-contrast files. The recipe reads it through ``dc_ref`` rather than a glob
because the contrast id only exists in the file NAME, and the recipe glob loader
concatenates matched files without a per-file label. A scan does carry the path,
so the DC must be declared with::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*\\.deseq2\\.results\\.(tsv|txt)$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          null_values: ["NA", "NaN", ""]
          include_file_paths: source_path   # carries the contrast id
          infer_schema_length: 0            # every column Utf8; recast here

``infer_schema_length: 0`` is not cosmetic: DESeq2 emits ``NA`` in every numeric
column and annotated twins mix ``1``/``MT``/``X`` in one column, so per-file type
inference disagrees between contrasts and the concatenation fails. Without
``include_file_paths`` the recipe falls back to a ``contrast`` column when one
exists, else labels every row ``all``.

Tolerated input variants (nf-core module versions differ):
    * ``.tsv`` or ``.txt`` (older chipseq), CRLF / CR line endings (string
      columns are stripped of stray ``\\r``, numerics re-cast leniently),
    * DESeq2 naming (``baseMean``, ``log2FoldChange``, ``lfcSE``, ``pvalue``,
      ``padj``) or snake_case (``base_mean``, ``log2fc`` / ``lfc``, ``lfc_se``,
      ``p_value``, ``p_adj`` / ``fdr``), matched case-insensitively,
    * an unnamed first column holding the feature id (R ``write.table`` row
      names), or ``gene_id`` / ``feature_id`` / ``Geneid`` / ``interval``.

Output schema:
    contrast : Utf8          contrast id derived from the file name
    gene_id : Utf8           feature identifier
    base_mean : Float64      DESeq2 baseMean (mean normalised count)
    log2fc : Float64         log2 fold change (volcano / MA effect size)
    lfc_se : Float64         standard error of log2fc
    pvalue : Float64         raw Wald p-value (QQ plot)
    padj : Float64           BH-adjusted p-value (null for independently filtered genes)
    log2_base_mean : Float64 log2(baseMean + 1), the A axis of the MA plot
    neg_log10_padj : Float64 -log10(padj), null where padj is null
    significant : Boolean    padj < 0.05 and |log2fc| >= 1 (nf-core defaults)
    direction : Utf8         "up" / "down" / "not significant"

Optional (kept when the tool wrote it):
    stat : Float64           Wald statistic
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads. A template reusing this recipe must
#: scan its per-contrast results into a DC with this tag (see module docstring).
RAW_DC_TAG = "deseq2_results_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="results", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "gene_id": pl.Utf8,
    "base_mean": pl.Float64,
    "log2fc": pl.Float64,
    "lfc_se": pl.Float64,
    "pvalue": pl.Float64,
    "padj": pl.Float64,
    "log2_base_mean": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "stat": pl.Float64,
}

# nf-core/differentialabundance defaults: differential_max_qval 0.05 and
# differential_min_fold_change 2 (i.e. |log2fc| >= 1).
PADJ_THRESHOLD = 0.05
LFC_THRESHOLD = 1.0

# DESeq2 writes a padj that underflowed to 0.0 for the very strongest features
# -log10(0) is +inf, which no plotly axis can place, so the value is clamped
# just short of the double-underflow limit (~1e-308 -> 308). The clamp has to
# apply to the computed log too, not only to an exact zero: a denormal padj such
# as 1e-320 is > 0, so it takes the first branch and would otherwise land at 320,
# above the ceiling that the gauge and the "beyond measurement" copy assume.
PADJ_ZERO_NEG_LOG10 = 300.0

# Column the scan is asked to add (polars include_file_paths).
SOURCE_PATH_COL = "source_path"

# Canonical name -> accepted spellings (compared after _norm()).
_ALIASES: dict[str, tuple[str, ...]] = {
    "gene_id": ("gene_id", "feature_id", "gene", "geneid", "feature", "interval", "id", "row"),
    "base_mean": ("basemean", "base_mean", "mean_expression", "avgexpr"),
    "log2fc": ("log2foldchange", "log2fc", "log2_fold_change", "lfc", "logfc", "log2_fc"),
    "lfc_se": ("lfcse", "lfc_se", "se", "log2fcse"),
    "stat": ("stat", "wald_stat", "statistic"),
    "pvalue": ("pvalue", "p_value", "pval", "p", "p_val"),
    "padj": ("padj", "p_adj", "padjust", "qvalue", "q_value", "fdr", "adj_p_val", "adj_pval"),
}

_RESULTS_SUFFIX_RE = re.compile(r"\.deseq2\.results.*$", re.IGNORECASE)


def _norm(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", name.strip().lower()).strip("_")


def _resolve_columns(columns: list[str]) -> dict[str, str]:
    """Map canonical names onto the columns actually present."""
    normalised = {_norm(c): c for c in columns}
    found: dict[str, str] = {}
    for canonical, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normalised and normalised[alias] not in found.values():
                found[canonical] = normalised[alias]
                break
    if "gene_id" not in found:
        # R row names arrive as an unnamed (or auto-named) first column.
        taken = set(found.values()) | {SOURCE_PATH_COL}
        first = next((c for c in columns if c not in taken), None)
        if first is not None:
            found["gene_id"] = first
    return found


def _clean_strings(df: pl.DataFrame) -> pl.DataFrame:
    """Strip stray CR / whitespace that CRLF or CR-terminated files leave behind."""
    str_cols = [c for c, dt in df.schema.items() if dt == pl.Utf8]
    if not str_cols:
        return df
    return df.with_columns([pl.col(c).str.strip_chars(" \t\r\n") for c in str_cols])


def _to_float(df: pl.DataFrame, col: str) -> pl.DataFrame:
    if df[col].dtype == pl.Float64:
        return df
    if df[col].dtype == pl.Utf8:
        return df.with_columns(
            pl.when(pl.col(col).str.to_uppercase().is_in(["NA", "NAN", ""]))
            .then(None)
            .otherwise(pl.col(col))
            .cast(pl.Float64, strict=False)
            .alias(col)
        )
    return df.with_columns(pl.col(col).cast(pl.Float64, strict=False))


def contrast_from_path(path: str) -> str:
    """``.../Condition_genotype_WT_KO_study.deseq2.results.tsv`` -> ``Condition_genotype_WT_KO_study``.

    Falls back to the parent directory name when the file stem carries nothing
    (chipseq writes ``<contrast>/<contrast>.deseq2.results.txt``, so both agree).
    """
    normalised = path.replace("\\", "/").rstrip("/")
    basename = normalised.rsplit("/", 1)[-1]
    stem = _RESULTS_SUFFIX_RE.sub("", basename).strip()
    if not stem or stem.lower() in {"deseq2", "results"}:
        parent = normalised.rsplit("/", 2)
        stem = parent[-2] if len(parent) >= 2 else stem
    return stem or "all"


def normalise_results(df: pl.DataFrame) -> pl.DataFrame:
    """Rename / cast a raw DESeq2 results frame (shared with results_annotated.py).

    Returns a frame with the canonical statistic columns plus ``contrast``; any
    other input column is kept under its original name.
    """
    df = _clean_strings(df)
    columns = _resolve_columns(df.columns)
    missing = [c for c in ("gene_id", "log2fc", "pvalue") if c not in columns]
    if missing:
        raise ValueError(f"deseq2 results: could not find columns for {missing} in {df.columns}")

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
    df = df.with_columns(pl.col("gene_id").cast(pl.Utf8))

    for col in ("base_mean", "log2fc", "lfc_se", "stat", "pvalue", "padj"):
        if col in df.columns:
            df = _to_float(df, col)
        elif col in ("base_mean", "lfc_se", "padj"):
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias(col))

    return df.filter(pl.col("gene_id").is_not_null() & (pl.col("gene_id") != ""))


def add_derived_columns(df: pl.DataFrame) -> pl.DataFrame:
    """MA x-axis, -log10(padj) and the significance call the renders read."""
    lfc = pl.col("log2fc")
    padj = pl.col("padj")
    is_sig = (padj < PADJ_THRESHOLD) & (lfc.abs() >= LFC_THRESHOLD)
    return df.with_columns(
        # Left null when base_mean is, rather than folded to log2(1) = 0. A tool
        # that writes no base_mean gets an all-null column here, and filling it
        # would put every gene on the same MA x coordinate while still passing
        # the schema check. An empty axis is the honest rendering.
        pl.when(pl.col("base_mean").is_not_null())
        .then((pl.col("base_mean") + 1.0).log(base=2))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("log2_base_mean"),
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


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Concatenated per-contrast results -> canonical long table."""
    df = normalise_results(sources["results"])
    df = add_derived_columns(df)

    ordered = list(EXPECTED_SCHEMA) + [c for c in OPTIONAL_SCHEMA if c in df.columns]
    return df.select(ordered).sort(["contrast", "padj", "pvalue"], nulls_last=True)
