"""Top variable genes of a merged Salmon TPM matrix, for ComplexHeatmap.

``salmon``/``tximport`` merges the per-sample ``quant.sf`` files into one
gene-level matrix, ``salmon.merged.gene_tpm.tsv``: ``gene_id``, ``gene_name``
and one TPM column per sample, ~58k rows on a human annotation. A clustered
heatmap of 58k rows is neither readable nor quick to compute, so this recipe
keeps the ``TOP_N`` genes with the highest variance on the log2(TPM + 1) scale,
which is the scale expression heatmaps are read on (raw TPM variance is
dominated by a handful of very highly expressed genes).

Sources:
    matrix       ``salmon/salmon.merged.gene_tpm.tsv`` — the layout a plain
                 salmon/tximport run writes. A pipeline that publishes the
                 matrix elsewhere (nf-core/rnaseq puts the STAR + Salmon route
                 under ``star_salmon/``) repoints it with
                 ``source_overrides: {matrix: {path: "star_salmon/salmon.merged.gene_tpm.tsv"}}``.
    samplesheet  optional; the pipeline ``--input`` sheet (CSV or TSV). When
                 present, its factor-like columns (2 to 12 distinct values, not
                 one per sample) become categorical column annotations
                 serialised in ``_col_annotations_json``, the same contract
                 ``qiime2/taxonomy_heatmap.py`` and ``deseq2/vst_top_variable.py``
                 use. When the sheet carries no factor column, the sample names
                 themselves are tried: ``<condition>_REP<n>`` and its variants
                 are the near-universal naming for replicate quantification
                 runs, and the condition they encode is the annotation a
                 heatmap needs.

Output: wide matrix, ``gene_name`` (Utf8, the heatmap index; disambiguated with
the gene id when an annotation gives two genes the same symbol) + one Float64
log2(TPM + 1) column per sample, in input order, + ``_col_annotations_json``
when annotations were found. Rows sorted by decreasing variance.
"""

from __future__ import annotations

import io
import json
import re

import plotly.colors
import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="matrix",
        path="salmon/salmon.merged.gene_tpm.tsv",
        format="tsv",
        read_kwargs={"null_values": ["NA"], "infer_schema_length": 10000},
    ),
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        optional=True,
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_name": pl.Utf8,
}
# Sample columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

TOP_N = 500
MAX_ANNOTATIONS = 4
MAX_LEVELS = 12
ANNOTATIONS_COL = "_col_annotations_json"

_PALETTE = plotly.colors.qualitative.Plotly

# `<condition>_REP1`, `<condition>_rep1`, `<condition>_R1`, `<condition>-1`:
# the replicate suffix quantification pipelines append to a condition name.
_REPLICATE_SUFFIX = re.compile(r"[._-](?:rep|r)?\d+$", re.IGNORECASE)


# --- samplesheet helpers (duplicated in sample_pca.py / gene_expression_long.py:
# recipes may not import each other) -------------------------------------------


def sanitise_column(name: str) -> str:
    """``Sample condition`` -> ``Sample_condition`` (Delta-safe, hover-safe)."""
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated sheet that was read with a comma separator."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=10000)
    return df


def sample_id_column(sheet: pl.DataFrame, sample_names: list[str]) -> str:
    """The sheet column whose values name the matrix samples (else the first)."""
    wanted = set(sample_names)
    best, best_hits = sheet.columns[0], -1
    for col in sheet.columns:
        hits = len(wanted & set(sheet[col].cast(pl.Utf8).to_list()))
        if hits > best_hits:
            best, best_hits = col, hits
    return best


def factor_columns(sheet: pl.DataFrame, id_col: str) -> list[str]:
    """Columns that behave like experimental factors, fewest levels first."""
    n = sheet.height
    upper = max(2, min(MAX_LEVELS, n - 1))
    scored = []
    for idx, col in enumerate(sheet.columns):
        if col == id_col:
            continue
        k = sheet[col].cast(pl.Utf8).drop_nulls().n_unique()
        if 2 <= k <= upper:
            scored.append((k, idx, col))
    return [col for _, _, col in sorted(scored)]


def groups_from_sample_names(sample_names: list[str]) -> list[str] | None:
    """Conditions read off ``<condition>_REP<n>`` style names, else ``None``.

    Only accepted when it actually groups: at least two levels and fewer levels
    than samples. A sheet that declares real factor columns is always preferred.
    """
    stripped = [_REPLICATE_SUFFIX.sub("", s) or s for s in sample_names]
    levels = set(stripped)
    if 2 <= len(levels) < len(sample_names):
        return stripped
    return None


def column_annotations_json(sheet: pl.DataFrame | None, sample_names: list[str]) -> str | None:
    """Categorical column-annotation strips aligned to ``sample_names``."""
    annotations: dict = {}
    if sheet is not None:
        sheet = fix_delimiter(sheet)
        id_col = sample_id_column(sheet, sample_names)
        lookup = sheet.with_columns(pl.col(id_col).cast(pl.Utf8)).unique(subset=[id_col])
        for col in factor_columns(sheet, id_col)[:MAX_ANNOTATIONS]:
            mapping = dict(
                zip(lookup[id_col].to_list(), lookup[col].cast(pl.Utf8).fill_null("").to_list())
            )
            values = [mapping.get(s, "") for s in sample_names]
            if any(v == "" for v in values):
                continue  # a blank level breaks the renderer's colour mapping
            annotations[sanitise_column(col)] = _strip(values)
    if not annotations:
        derived = groups_from_sample_names(sample_names)
        if derived is not None:
            annotations["condition"] = _strip(derived)
    return json.dumps(annotations) if annotations else None


def _strip(values: list[str]) -> dict:
    levels = sorted(set(values))
    return {
        "values": values,
        "type": "categorical",
        "colors": {v: _PALETTE[i % len(_PALETTE)] for i, v in enumerate(levels)},
    }


# --- matrix helpers -----------------------------------------------------------


def split_matrix(matrix: pl.DataFrame) -> tuple[str, str | None, list[str]]:
    """(feature-id column, gene-symbol column or None, numeric sample columns)."""
    id_col = next(
        (c for c in matrix.columns if c.lower() in ("gene_id", "feature_id", "id")),
        matrix.columns[0],
    )
    name_col = next((c for c in matrix.columns if c.lower() in ("gene_name", "symbol")), None)
    sample_cols = [
        c for c in matrix.columns if c not in (id_col, name_col) and matrix[c].dtype.is_numeric()
    ]
    if not sample_cols:
        raise ValueError(f"salmon: no numeric sample columns in {matrix.columns}")
    return id_col, name_col, sample_cols


def unique_labels(labels: list[str], ids: list[str]) -> list[str]:
    """``labels``, with the gene id appended to every value that repeats."""
    seen: dict[str, int] = {}
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
    return [
        (f"{label} ({gid})" if seen[label] > 1 else label) if label else gid
        for label, gid in zip(labels, ids)
    ]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Top-variance slice of the log2(TPM + 1) matrix, with sample annotations."""
    matrix = sources["matrix"]
    id_col, name_col, sample_cols = split_matrix(matrix)

    logged = matrix.select(
        [
            pl.col(id_col).cast(pl.Utf8).alias("_gene_id"),
            pl.col(name_col).cast(pl.Utf8).alias("_gene_name")
            if name_col
            else pl.col(id_col).cast(pl.Utf8).alias("_gene_name"),
            *[(pl.col(c).cast(pl.Float64) + 1.0).log(2).alias(c) for c in sample_cols],
        ]
    )
    logged = logged.with_columns(
        pl.concat_list([pl.col(c) for c in sample_cols]).list.var().alias("_variance")
    )
    top = (
        logged.filter(pl.col("_variance").is_not_null())
        .sort("_variance", descending=True)
        .head(TOP_N)
        .drop("_variance")
    )

    labels = unique_labels(top["_gene_name"].fill_null("").to_list(), top["_gene_id"].to_list())
    result = top.drop(["_gene_id", "_gene_name"]).insert_column(
        0, pl.Series("gene_name", labels, dtype=pl.Utf8)
    )

    annotations = column_annotations_json(sources.get("samplesheet"), sample_cols)
    if annotations:
        result = result.with_columns(pl.lit(annotations).alias(ANNOTATIONS_COL))
    return result
