"""Fold-enrichment matrix of the strongest MACS2 consensus peaks.

Reads the same ``<set>.consensus_peaks.boolean.txt`` tables as
``consensus_boolean`` and keeps, per consensus set, the ``TOP_N`` intervals
with the largest summed MACS2 fold enrichment across the set's samples. One
Float64 column per sample holds that sample's fold enrichment (0.0 where the
sample called no peak on the interval), which is the wide numeric shape
``complex_heatmap`` clusters. ``consensus_set`` and ``support`` (how many
samples carry the peak, kept as text) are categorical row annotations, so they
are never mistaken for value columns.

Output schema:
    peak_id : Utf8        "<consensus_set>:<interval_id>", unique across sets
    consensus_set : Utf8  which boolean table the row came from
    interval_id : Utf8    the table's own interval id (``Interval_12``)
    chr : Utf8            chromosome of the merged interval
    region : Utf8         "chr:start-end", the heatmap row label
    support : Utf8        number of samples calling the peak, as a category
    <sample> : Float64    one column per sample of the set (run-specific names)
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
    "region": pl.Utf8,
    "support": pl.Utf8,
}
# One Float64 fold-enrichment column per sample follows; names are run-specific.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# Rows kept per consensus set. Server-side clustering is quadratic in rows, so
# the matrix stays a few hundred intervals tall even for a 100k-peak set.
TOP_N = 250

_FIXED = ["chr", "start", "end", "interval_id", "num_samples"]
_FALLBACK_LABEL = "consensus"


def sample_names(columns: list[str]) -> list[str]:
    """Sample names of a consensus table, from its ``<sample>.fc`` columns."""
    return [c[: -len(".fc")] for c in columns if c.endswith(".fc")]


def set_label(names: list[str]) -> str:
    """Longest common prefix of the sample names, trimmed of separators."""
    return re.sub(r"[._-]+$", "", os.path.commonprefix(list(names))) or _FALLBACK_LABEL


def label_consensus_sets(df: pl.DataFrame, samples: list[str]) -> pl.DataFrame:
    """Add ``consensus_set``: which table each row came from, named by its samples.

    Rows carry values only for the samples of their own table (the diagonal
    concat leaves the other tables' columns null), so the populated ``.fc``
    columns identify the table. Two tables with the same prefix get a numeric
    suffix so their intervals stay distinguishable.
    """
    signature = pl.concat_str(
        [
            pl.when(pl.col(f"{s}.fc").is_not_null()).then(pl.lit(f"{s};")).otherwise(pl.lit(""))
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
    """Rank intervals by summed fold enrichment and keep the top rows per set."""
    df = sources["boolean"]
    missing = [c for c in _FIXED if c not in df.columns]
    if missing:
        raise ValueError(f"macs2_consensus_fc: input lacks columns {missing}")
    samples = sample_names(df.columns)
    if not samples:
        raise ValueError("macs2_consensus_fc: no `<sample>.fc` column found")

    # A `.fc` cell is NA where the sample called no peak: a 0 fold enrichment.
    # Rows from another table are NA on these columns too, so the set label is
    # derived first, on the raw nulls.
    df = label_consensus_sets(df, samples)
    df = df.with_columns(
        pl.col("chr").cast(pl.Utf8),
        pl.col("interval_id").cast(pl.Utf8),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        pl.col("num_samples").cast(pl.Int64, strict=False).cast(pl.Utf8).alias("support"),
        *[
            pl.col(f"{s}.fc").cast(pl.Float64, strict=False).fill_null(0.0).alias(s)
            for s in samples
        ],
    ).with_columns(
        pl.concat_str([pl.col("consensus_set"), pl.lit(":"), pl.col("interval_id")]).alias(
            "peak_id"
        ),
        pl.concat_str(
            [pl.col("chr"), pl.lit(":"), pl.col("start"), pl.lit("-"), pl.col("end")]
        ).alias("region"),
        pl.sum_horizontal([pl.col(s) for s in samples]).alias("_total_fc"),
    )
    top = df.filter(
        pl.col("_total_fc").rank("ordinal", descending=True).over("consensus_set") <= TOP_N
    ).sort(["consensus_set", "chr", "start"])
    return top.select(list(EXPECTED_SCHEMA) + samples)
