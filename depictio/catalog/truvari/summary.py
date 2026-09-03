"""Normalize a Truvari structural-variant benchmark summary into a tidy table.

OPTIONAL — the public megatest does not run the SV profile, so this recipe is not exercised
by the bundled test data. It targets the pipeline-aggregated
``sv/summary/tables/truvari/truvari.summary.csv`` (collated from per-sample Truvari
``summary.json`` by the reporting subworkflow). Column matching is case/format tolerant
because the exact aggregated header is not pinned against real data yet — adjust once an SV
run is available.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="truvari_summary",
        path="sv/summary/tables/truvari/truvari.summary.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "label": pl.Utf8,
    "precision": pl.Float64,
    "recall": pl.Float64,
    "f1": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "tp_base": pl.Int64,
    "tp_comp": pl.Int64,
    "fp": pl.Int64,
    "fn": pl.Int64,
}


def _find(df: pl.DataFrame, *candidates: str) -> str | None:
    norm = {c.lower().replace("-", "").replace("_", "").replace(".", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().replace("-", "").replace("_", "").replace(".", "")
        if key in norm:
            return norm[key]
    return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Resolve Truvari metric columns tolerantly and standardize names."""
    df = sources["truvari_summary"]

    label_col = _find(df, "Tool", "sample", "label", "File")
    df = (
        df.with_columns(pl.col(label_col).cast(pl.Utf8).alias("label"))
        if label_col
        else (df.with_columns(pl.lit("truvari").alias("label")))
    )

    float_map = {"precision": ("precision",), "recall": ("recall",), "f1": ("f1", "f1_score")}
    for out, cands in float_map.items():
        col = _find(df, *cands)
        if col is None:
            raise ValueError(f"truvari_summary: cannot locate '{out}' column in {df.columns}")
        df = df.with_columns(pl.col(col).cast(pl.Float64, strict=False).alias(out))

    int_map = {
        "tp_base": ("TP-base", "TPbase", "tp_base"),
        "tp_comp": ("TP-comp", "TPcomp", "tp_comp"),
        "fp": ("FP",),
        "fn": ("FN",),
    }
    for out, cands in int_map.items():
        col = _find(df, *cands)
        if col is not None:
            df = df.with_columns(pl.col(col).cast(pl.Int64, strict=False).alias(out))

    keep = ["label", "precision", "recall", "f1", "tp_base", "tp_comp", "fp", "fn"]
    return df.select([c for c in keep if c in df.columns])
