"""Top variable miRNAs x samples, log2(CPM + 1), for ComplexHeatmap.

Keeps the ``TOP_N`` miRNAs with the highest variance of log2(CPM + 1) across
samples among those with a mean CPM of at least ``MIN_MEAN_CPM``, one row per
miRNA and one column per sample, rows sorted by decreasing variance. Clustered
and row-scaled, this is where samples that share a design group should form
blocks, and where a sample that does not is visible at once.

When the counts carry design columns (a design table was given), the ones that
behave like factors (2 to ``MAX_LEVELS`` levels, no blanks) become categorical
column annotations, serialised in ``_col_annotations_json`` (the contract
``salmon/top_variable_genes.py`` and ``qiime2/taxonomy_heatmap.py`` use).

Source: the ``mirtop_mirna_counts`` collection (``mirtop/mirna_counts.py``).

Output: ``mirna`` (Utf8, the heatmap index) + one Float64 column per sample +
``_col_annotations_json`` when annotations were found.
"""

from __future__ import annotations

import json

import plotly.colors
import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="counts", dc_ref="mirtop_mirna_counts"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "mirna": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

TOP_N = 100
MIN_MEAN_CPM = 10.0
MAX_ANNOTATIONS = 4
MAX_LEVELS = 12
ANNOTATIONS_COL = "_col_annotations_json"

_MEASURES = ("mirna", "reads", "cpm", "log2_cpm", "isomirs", "reference_pct")
_PALETTE = plotly.colors.qualitative.Plotly


def _annotations(counts: pl.DataFrame, samples: list[str]) -> str | None:
    design = [c for c in counts.columns if c not in _MEASURES and c != "sample"]
    if not design:
        return None
    lookup = counts.select("sample", *design).unique(subset="sample")
    upper = max(2, min(MAX_LEVELS, len(samples) - 1))
    scored = []
    for idx, col in enumerate(design):
        mapping = dict(zip(lookup["sample"].to_list(), lookup[col].to_list()))
        values = [mapping.get(s) for s in samples]
        if any(v is None or v == "" for v in values):
            continue
        k = len(set(values))
        if 2 <= k <= upper:
            scored.append((k, idx, col, values))
    annotations = {}
    for _, _, col, values in sorted(scored)[:MAX_ANNOTATIONS]:
        levels = sorted(set(values))
        annotations[col] = {
            "values": values,
            "type": "categorical",
            "colors": {v: _PALETTE[i % len(_PALETTE)] for i, v in enumerate(levels)},
        }
    return json.dumps(annotations) if annotations else None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Top-variance slice of the log2 CPM matrix, miRNAs as rows."""
    counts = sources["counts"]
    stats = counts.group_by("mirna").agg(
        pl.col("cpm").mean().alias("_mean"), pl.col("log2_cpm").var().alias("_var")
    )
    ranked = stats.filter((pl.col("_mean") >= MIN_MEAN_CPM) & pl.col("_var").is_not_null())
    if ranked.is_empty():
        ranked = stats.filter(pl.col("_var").is_not_null())
    top = ranked.sort(["_var", "mirna"], descending=[True, False]).head(TOP_N)
    samples = sorted(counts["sample"].unique().to_list())
    wide = (
        counts.filter(pl.col("mirna").is_in(top["mirna"].to_list()))
        .pivot(on="sample", index="mirna", values="log2_cpm")
        .fill_null(0.0)
    )
    wide = (
        top.select("mirna")
        .join(wide, on="mirna", how="left", maintain_order="left")
        .select("mirna", *[pl.col(s).cast(pl.Float64) for s in samples if s in wide.columns])
    )
    annotations = _annotations(counts, [s for s in samples if s in wide.columns])
    if annotations:
        wide = wide.with_columns(pl.lit(annotations).alias(ANNOTATIONS_COL))
    return wide
