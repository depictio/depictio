"""Taxon x (sample, profiler) relative-abundance matrix for the clustered heatmap.

Reads the long ``taxpasta_profiles`` collection and pivots it into the wide shape the
ComplexHeatmap renderer expects: one row per taxon, one column per profiling run
(``<sample>__<profiler>__<database>``; Delta Lake rejects spaces in column names).
Relative abundance is used rather than raw counts so profilers with wildly different
library depths stay comparable in one matrix.

Only the ``_TOP_TAXA`` most abundant taxa (summed over every run) are kept: a full
matrix is thousands of rows deep and clusters into an unreadable band.

``rank`` rides along as a row annotation, and the per-column profiler / platform
annotations are serialised into ``_col_annotations_json``, the same contract the
ampliseq and deseq2 heatmap recipes use.

Output: taxon, rank, one Float64 column per profiling run, _col_annotations_json.
"""

import json

import plotly.colors
import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="profiles", dc_ref="taxpasta_profiles"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "taxon": pl.Utf8,
    "rank": pl.Utf8,
}

# One column per profiling run; the names are run-dependent, so they are not declared.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_TOP_TAXA = 60
_ANNOTATIONS_COL = "_col_annotations_json"
_PLOTLY_QUALITATIVE = plotly.colors.qualitative.Plotly


def _column_annotations(runs: pl.DataFrame, columns: list[str]) -> str | None:
    """Serialise the per-column profiler / platform strips for the heatmap."""
    lookup = {r["run"]: r for r in runs.iter_rows(named=True)}
    annotations: dict[str, dict] = {}
    for field in ("profiler", "platform"):
        values = [str(lookup.get(c, {}).get(field) or "") for c in columns]
        if any(v == "" for v in values):
            continue
        unique = sorted(set(values))
        annotations[field] = {
            "values": values,
            "type": "categorical",
            "colors": {
                v: _PLOTLY_QUALITATIVE[i % len(_PLOTLY_QUALITATIVE)] for i, v in enumerate(unique)
            },
        }
    return json.dumps(annotations) if annotations else None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot the long profiles into a taxon x run matrix of relative abundances."""
    long = sources["profiles"]
    missing = {"name", "rank", "sample", "profiler", "database", "rel_abundance"} - set(
        long.columns
    )
    if missing:
        raise ValueError(f"taxpasta matrix: profiles is missing {sorted(missing)}")

    tagged = long.with_columns(
        pl.format("{}__{}__{}", pl.col("sample"), pl.col("profiler"), pl.col("database")).alias(
            "run"
        ),
        pl.col("name").alias("taxon"),
    )

    keep = (
        tagged.group_by("taxon")
        .agg(pl.col("rel_abundance").sum().alias("total"))
        .sort("total", descending=True)
        .head(_TOP_TAXA)
        .get_column("taxon")
    )

    ranks = (
        tagged.filter(pl.col("taxon").is_in(keep))
        .group_by("taxon")
        .agg(pl.col("rank").first().alias("rank"))
    )

    matrix = (
        tagged.filter(pl.col("taxon").is_in(keep))
        .group_by(["taxon", "run"])
        .agg(pl.col("rel_abundance").sum().alias("rel_abundance"))
        .pivot(values="rel_abundance", index="taxon", on="run", aggregate_function="sum")
        .fill_null(0.0)
    )

    run_cols = sorted(c for c in matrix.columns if c != "taxon")
    runs = tagged.select("run", "profiler", "database", "platform").unique(subset=["run"])

    result = (
        matrix.join(ranks, on="taxon", how="left")
        .with_columns(pl.col("rank").fill_null("unknown"))
        .select(["taxon", "rank", *run_cols])
        .with_columns(pl.col(c).cast(pl.Float64) for c in run_cols)
        .sort("taxon")
    )

    annotations = _column_annotations(runs, run_cols)
    if annotations is not None:
        result = result.with_columns(pl.lit(annotations).alias(_ANNOTATIONS_COL))
    return result
