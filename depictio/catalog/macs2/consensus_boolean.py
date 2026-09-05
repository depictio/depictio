"""Consensus peak x sample presence matrix from MACS2 consensus boolean tables.

The nf-core ChIP-family pipelines merge the per-sample MACS2 peaks of one
antibody into ``<set>.consensus_peaks.boolean.txt``: one row per merged interval
with ``<sample>.bool`` / ``.fc`` / ``.qval`` / ``.pval`` / ``.start`` / ``.end``
/ ``.summit`` columns per sample. This recipe keeps the interval coordinates and
turns the ``.bool`` flags into 0/1 integer set columns, which is the shape
``upset_plot`` reads (binary integer columns are the sets).

Several consensus tables can be concatenated (one per antibody). The glob loader
does not expose file names, so which table a row came from is recovered from the
sample columns that are populated on that row and labelled by the longest common
prefix of those sample names (``EZH2_IP``, ``FOXA1_IP``).

Output schema:
    peak_id : Utf8        "<consensus_set>:<interval_id>", unique across sets
    consensus_set : Utf8  which boolean table the row came from
    interval_id : Utf8    the table's own interval id (``Interval_12``)
    chr : Utf8            chromosome of the merged interval
    start : Int64         merged interval start
    end : Int64           merged interval end
    num_peaks : Int64     per-sample peaks merged into the interval
    num_samples : Int64   samples calling a peak on the interval
    <sample> : Int8       1 when the sample called a peak (run-specific names)
"""

import os
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="boolean",
        glob_pattern="**/*.consensus_peaks.boolean.txt",
        format="TSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "peak_id": pl.Utf8,
    "consensus_set": pl.Utf8,
    "interval_id": pl.Utf8,
    "chr": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "num_peaks": pl.Int64,
    "num_samples": pl.Int64,
}
# One Int8 0/1 column per sample follows; the names are run-specific.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_FIXED = ["chr", "start", "end", "interval_id", "num_peaks", "num_samples"]
_FALLBACK_LABEL = "consensus"


def sample_names(columns: list[str]) -> list[str]:
    """Sample names of a consensus table, from its ``<sample>.bool`` columns."""
    return [c[: -len(".bool")] for c in columns if c.endswith(".bool")]


def set_label(names: list[str]) -> str:
    """Longest common prefix of the sample names, trimmed of separators."""
    return re.sub(r"[._-]+$", "", os.path.commonprefix(list(names))) or _FALLBACK_LABEL


def label_consensus_sets(df: pl.DataFrame, samples: list[str]) -> pl.DataFrame:
    """Add ``consensus_set``: which table each row came from, named by its samples.

    Rows carry values only for the samples of their own table (the diagonal
    concat leaves the other tables' columns null), so the populated ``.bool``
    columns identify the table. Two tables with the same prefix get a numeric
    suffix so their intervals stay distinguishable.
    """
    signature = pl.concat_str(
        [
            pl.when(pl.col(f"{s}.bool").is_not_null()).then(pl.lit(f"{s};")).otherwise(pl.lit(""))
            for s in samples
        ]
    ).alias("_signature")
    df = df.with_columns(signature)
    labels: dict[str, str] = {}
    seen: dict[str, int] = {}
    for sig in df.get_column("_signature").unique().sort().to_list():
        label = set_label([s for s in sig.split(";") if s])
        seen[label] = seen.get(label, 0) + 1
        labels[sig] = label if seen[label] == 1 else f"{label}_{seen[label]}"
    return df.with_columns(
        pl.col("_signature").replace_strict(labels, return_dtype=pl.Utf8).alias("consensus_set")
    ).drop("_signature")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Type the coordinates and reduce the per-sample blocks to 0/1 set columns."""
    df = sources["boolean"]
    missing = [c for c in _FIXED if c not in df.columns]
    if missing:
        raise ValueError(f"macs2_consensus_boolean: input lacks columns {missing}")
    samples = sample_names(df.columns)
    if not samples:
        raise ValueError("macs2_consensus_boolean: no `<sample>.bool` column found")

    df = label_consensus_sets(df, samples)
    typed = df.with_columns(
        pl.col("chr").cast(pl.Utf8),
        pl.col("interval_id").cast(pl.Utf8),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        pl.col("num_peaks").cast(pl.Int64, strict=False),
        pl.col("num_samples").cast(pl.Int64, strict=False),
        pl.concat_str([pl.col("consensus_set"), pl.lit(":"), pl.col("interval_id")]).alias(
            "peak_id"
        ),
        *[
            (pl.col(f"{s}.bool").cast(pl.Utf8).str.to_uppercase() == "TRUE")
            .fill_null(False)
            .cast(pl.Int8)
            .alias(s)
            for s in samples
        ],
    )
    return typed.select(list(EXPECTED_SCHEMA) + samples).sort(["consensus_set", "chr", "start"])
