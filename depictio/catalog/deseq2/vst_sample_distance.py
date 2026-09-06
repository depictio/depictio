"""Sample-to-sample distance matrix on the DESeq2 variance-stabilised data.

The pipeline's exploratory ``sample_dendrogram`` clusters samples on the
Euclidean distance between their vst() profiles over the most variable genes.
This recipe publishes that distance matrix (samples x samples) so
ComplexHeatmap can draw it clustered, the classic DESeq2 QC panel for spotting
an outlier sample or a batch that dominates the biology.

Sources:
    vst          ``**/all.vst.tsv`` at any depth
    samplesheet  optional pipeline ``--input`` sheet; factor-like columns become
                 column annotations (``_col_annotations_json``), repoint with
                 ``source_overrides: {samplesheet: {path: "{SAMPLESHEET_FILE}"}}``.

Output: ``sample`` (Utf8, the heatmap index) + one Float64 column per sample
(symmetric, zero diagonal) + ``_col_annotations_json`` when a sheet was found.
"""

from __future__ import annotations

import io
import json
import re

import numpy as np
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
    "sample": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

TOP_N = 500
MAX_ANNOTATIONS = 4
MAX_LEVELS = 12
ANNOTATIONS_COL = "_col_annotations_json"

_PALETTE = plotly.colors.qualitative.Plotly


def sanitise_column(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    if df.width == 1 and "," in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), infer_schema_length=10000)
    return df


def sample_id_column(sheet: pl.DataFrame, sample_names: list[str]) -> str:
    wanted = set(sample_names)
    best, best_hits = sheet.columns[0], -1
    for col in sheet.columns:
        hits = len(wanted & set(sheet[col].cast(pl.Utf8).to_list()))
        if hits > best_hits:
            best, best_hits = col, hits
    return best


def factor_columns(sheet: pl.DataFrame, id_col: str) -> list[str]:
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


def column_annotations_json(sheet: pl.DataFrame, sample_names: list[str]) -> str | None:
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
            continue
        levels = sorted(set(values))
        annotations[sanitise_column(col)] = {
            "values": values,
            "type": "categorical",
            "colors": {v: _PALETTE[i % len(_PALETTE)] for i, v in enumerate(levels)},
        }
    return json.dumps(annotations) if annotations else None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Euclidean sample distances over the top-variance genes."""
    vst = sources["vst"]
    id_col = next((c for c in vst.columns if c.lower() in ("gene_id", "feature_id", "id")), None)
    if id_col is None:
        id_col = vst.columns[0]
    sample_cols = [c for c in vst.columns if c != id_col and vst[c].dtype.is_numeric()]
    if len(sample_cols) < 2:
        raise ValueError("deseq2 vst_sample_distance: need at least two sample columns")

    numeric = vst.select(sample_cols).with_columns(
        [pl.col(c).cast(pl.Float64) for c in sample_cols]
    )
    numeric = numeric.with_columns(
        pl.concat_list([pl.col(c) for c in sample_cols]).list.var().alias("_variance")
    )
    top = numeric.filter(pl.col("_variance").is_not_null()).sort("_variance", descending=True)
    x = top.head(TOP_N).drop("_variance").to_numpy().T  # samples x genes
    x = np.nan_to_num(x, nan=0.0)
    sq = (x * x).sum(axis=1)
    d2 = sq[:, None] + sq[None, :] - 2.0 * (x @ x.T)
    dist = np.sqrt(np.clip(d2, 0.0, None))
    np.fill_diagonal(dist, 0.0)

    result = pl.DataFrame(
        {
            "sample": sample_cols,
            **{s: dist[:, j].astype(float).tolist() for j, s in enumerate(sample_cols)},
        }
    )

    sheet = sources.get("samplesheet")
    if sheet is not None:
        annotations = column_annotations_json(sheet, sample_cols)
        if annotations:
            result = result.with_columns(pl.lit(annotations).alias(ANNOTATIONS_COL))
    return result
