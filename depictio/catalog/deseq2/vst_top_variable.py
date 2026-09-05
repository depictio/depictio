"""Top variable genes of the DESeq2 variance-stabilised matrix, for ComplexHeatmap.

``deseq2/differential`` (``DESEQ2_NORM`` in differentialabundance) writes the
whole vst() matrix as ``all.vst.tsv``: ``gene_id`` followed by one column per
sample, 30k rows. A clustered heatmap of 30k rows is neither readable nor
quick to compute, so this recipe keeps the ``TOP_N`` genes with the highest
variance across samples, the same reduction the pipeline's own exploratory
plots apply (``exploratory_n_features``, default 500).

Sources:
    vst          ``**/all.vst.tsv`` at any depth: a plain differentialabundance
                 run writes it under tables/processed_abundance/, the megatest
                 one level deeper under a parameter-set directory.
    samplesheet  optional; the pipeline ``--input`` sheet (TSV or CSV). When
                 present, its factor-like columns (2 to 12 distinct values,
                 not one per sample) become categorical column annotations
                 serialised in ``_col_annotations_json``, the same contract
                 ``qiime2/taxonomy_heatmap.py`` uses. Point it at the run's
                 sheet with ``source_overrides: {samplesheet: {path: "{SAMPLESHEET_FILE}"}}``.

Output: wide matrix, ``gene_id`` (Utf8, the heatmap index) + one Float64 column
per sample (input order) + ``_col_annotations_json`` when a sheet was found.
Rows sorted by decreasing variance.
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
        ref="vst",
        glob_pattern="**/all.vst.tsv",
        format="tsv",
        read_kwargs={"null_values": ["NA"], "infer_schema_length": 10000},
    ),
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.tsv",
        format="tsv",
        optional=True,
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
}
# Sample columns are run-dependent, so they sit outside the declared schema
# and go unchecked: the ingest validates EXPECTED_SCHEMA only.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

TOP_N = 500
MAX_ANNOTATIONS = 4
MAX_LEVELS = 12
ANNOTATIONS_COL = "_col_annotations_json"

_PALETTE = plotly.colors.qualitative.Plotly


# --- samplesheet helpers (duplicated in vst_pca.py / vst_sample_distance.py:
# recipes may not import each other; shared helpers belong in
# depictio/recipes/lib) -------------------------------------------------------


def sanitise_column(name: str) -> str:
    """``Condition genotype`` -> ``Condition_genotype`` (Delta-safe, hover-safe)."""
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a comma-separated sheet that was read with a tab separator."""
    if df.width == 1 and "," in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), infer_schema_length=10000)
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
        values = sheet[col].cast(pl.Utf8).drop_nulls()
        k = values.n_unique()
        if 2 <= k <= upper:
            scored.append((k, idx, col))
    return [col for _, _, col in sorted(scored)]


def column_annotations_json(sheet: pl.DataFrame, sample_names: list[str]) -> str | None:
    """Categorical column-annotation strips aligned to ``sample_names``."""
    sheet = fix_delimiter(sheet)
    id_col = sample_id_column(sheet, sample_names)
    lookup = sheet.with_columns(pl.col(id_col).cast(pl.Utf8)).unique(subset=[id_col])
    annotations: dict = {}
    for col in factor_columns(sheet, id_col)[:MAX_ANNOTATIONS]:
        mapping = dict(
            zip(lookup[id_col].to_list(), lookup[col].cast(pl.Utf8).fill_null("").to_list())
        )
        values = [mapping.get(s, "") for s in sample_names]
        if any(v == "" for v in values):
            continue  # a blank level breaks the renderer's colour mapping
        levels = sorted(set(values))
        annotations[sanitise_column(col)] = {
            "values": values,
            "type": "categorical",
            "colors": {v: _PALETTE[i % len(_PALETTE)] for i, v in enumerate(levels)},
        }
    return json.dumps(annotations) if annotations else None


# --- matrix helpers -----------------------------------------------------------


def split_matrix(vst: pl.DataFrame) -> tuple[str, list[str]]:
    """(feature-id column, numeric sample columns) of a wide vst matrix."""
    id_col = next((c for c in vst.columns if c.lower() in ("gene_id", "feature_id", "id")), None)
    if id_col is None:
        id_col = vst.columns[0]
    sample_cols = [c for c in vst.columns if c != id_col and vst[c].dtype.is_numeric()]
    if not sample_cols:
        raise ValueError(f"deseq2 vst: no numeric sample columns in {vst.columns}")
    return id_col, sample_cols


def top_variable(vst: pl.DataFrame, n: int = TOP_N) -> pl.DataFrame:
    """``gene_id`` + sample columns for the ``n`` highest-variance genes."""
    id_col, sample_cols = split_matrix(vst)
    df = vst.select([pl.col(id_col).cast(pl.Utf8).alias("gene_id"), *sample_cols]).with_columns(
        [pl.col(c).cast(pl.Float64) for c in sample_cols]
    )
    df = df.with_columns(
        pl.concat_list([pl.col(c) for c in sample_cols]).list.var().alias("_variance")
    )
    return (
        df.filter(pl.col("_variance").is_not_null())
        .sort("_variance", descending=True)
        .head(n)
        .drop("_variance")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Top-variance slice of the vst matrix, with optional sample annotations."""
    result = top_variable(sources["vst"])
    sheet = sources.get("samplesheet")
    if sheet is not None:
        sample_cols = [c for c in result.columns if c != "gene_id"]
        annotations = column_annotations_json(sheet, sample_cols)
        if annotations:
            result = result.with_columns(pl.lit(annotations).alias(ANNOTATIONS_COL))
    return result
