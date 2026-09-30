"""Assembly statistics of each genome from assembly-scan's JSON report.

assembly-scan summarises a FASTA assembly in one flat JSON object: contig count,
total, min, max, mean, median and N50 length, L50, base composition in percent,
and how many contigs exceed 1 kb, 10 kb, 100 kb and 1 Mb. The report names the
FASTA file it read, not the sample, so the genome id comes from the report's
file name (``assemblyscan/<genome>.json``).

The JSON is pretty-printed one key per line, so the recipe reads it as lines
and parses each ``"key": value`` pair; it needs no JSON reader and tolerates a
report that lacks a key (the column is null). GC content is the sum of the C
and G percentages.

Output columns:
    genome, contigs, total_length, max_contig_length, mean_contig_length,
    median_contig_length, min_contig_length, n50, l50, gc_pct, n_pct,
    contigs_over_1kb, contigs_over_10kb, contigs_over_100kb, contigs_over_1mb,
    contigs_over_1mb_pct
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_SOURCE_PATH = "_source_path"
_SUFFIX = ".json"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="report",
        glob_pattern="assemblyscan/*.json",
        format="CSV",
        source_path=_SOURCE_PATH,
        read_kwargs={
            "separator": "\x1f",
            "has_header": False,
            "new_columns": ["raw"],
            "quote_char": None,
            "infer_schema_length": 0,
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "contigs": pl.Int64,
    "total_length": pl.Int64,
    "max_contig_length": pl.Int64,
    "mean_contig_length": pl.Int64,
    "median_contig_length": pl.Int64,
    "min_contig_length": pl.Int64,
    "n50": pl.Int64,
    "l50": pl.Int64,
    "gc_pct": pl.Float64,
    "n_pct": pl.Float64,
    "contigs_over_1kb": pl.Int64,
    "contigs_over_10kb": pl.Int64,
    "contigs_over_100kb": pl.Int64,
    "contigs_over_1mb": pl.Int64,
    "contigs_over_1mb_pct": pl.Float64,
}

_INT_KEYS = {
    "total_contig": "contigs",
    "total_contig_length": "total_length",
    "max_contig_length": "max_contig_length",
    "mean_contig_length": "mean_contig_length",
    "median_contig_length": "median_contig_length",
    "min_contig_length": "min_contig_length",
    "n50_contig_length": "n50",
    "l50_contig_count": "l50",
    "contigs_greater_1k": "contigs_over_1kb",
    "contigs_greater_10k": "contigs_over_10kb",
    "contigs_greater_100k": "contigs_over_100kb",
    "contigs_greater_1m": "contigs_over_1mb",
}
_FLOAT_KEYS = {
    "contig_percent_c": "_c",
    "contig_percent_g": "_g",
    "contig_percent_n": "n_pct",
    "percent_contigs_greater_1m": "contigs_over_1mb_pct",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["report"]
    kv = (
        df.filter(pl.col("raw").is_not_null())
        .with_columns(
            pl.col("raw").str.extract(r'^\s*"([^"]+)"\s*:', 1).alias("key"),
            pl.col("raw")
            .str.extract(r":\s*\"?([^\",]*)\"?\s*,?\s*$", 1)
            .str.strip_chars()
            .alias("value"),
        )
        .filter(pl.col("key").is_in(list(_INT_KEYS) + list(_FLOAT_KEYS)))
        .with_columns(
            pl.col(_SOURCE_PATH)
            .str.split("/")
            .list.last()
            .str.strip_suffix(_SUFFIX)
            .alias("genome")
        )
    )
    wide = kv.pivot(on="key", index="genome", values="value", aggregate_function="first")
    for key in [*_INT_KEYS, *_FLOAT_KEYS]:
        if key not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Utf8).alias(key))
    out = wide.select(
        "genome",
        *[
            pl.col(k).cast(pl.Float64, strict=False).round(0).cast(pl.Int64).alias(v)
            for k, v in _INT_KEYS.items()
        ],
        *[pl.col(k).cast(pl.Float64, strict=False).alias(v) for k, v in _FLOAT_KEYS.items()],
    )
    out = out.with_columns((pl.col("_c") + pl.col("_g")).round(2).alias("gc_pct"))
    return out.select(list(EXPECTED_SCHEMA)).sort("genome")
