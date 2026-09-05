"""taxonomy_id -> (name, rank) harvested from the profilers' own report files.

taxprofiler runs taxpasta with ``--add-name false`` by default, so the standardised
tables identify taxa by NCBI id only. Every kraken-style report the pipeline also
writes carries the name and the rank next to that id, so this recipe reads them back
and publishes one lookup the taxpasta DCs join against.

One glob covers the three report families the pipeline emits under
``<profiler>/<database>/*.report.txt``; they disagree on layout, so the files are read
as raw lines and each line is classified on its own:

    kraken2      6 fields   pct, clade_reads, taxon_reads, rank_code, taxid, name
    krakenuniq   9 fields   %, reads, taxReads, kmers, dup, cov, taxID, rank, taxName
    centrifuge   7 fields   name, taxID, taxRank, genomeSize, numReads, numUnique, abundance

Header and comment lines fail the "the id field is numeric" test and drop out, so no
per-file header handling is needed. A run with none of those three profilers yields no
rows; the DC is optional and the taxpasta profiles then fall back to ``taxid <id>``.

Output: taxonomy_id, name, rank (one row per id).
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reports",
        glob_pattern="*/*/*.report.txt",
        format="csv",
        # One column per line: \x1f never occurs in a kraken-style report, so the
        # reader cannot split the row and the recipe owns the tab handling.
        read_kwargs={
            "has_header": False,
            "separator": "\x1f",
            "quote_char": None,
            "new_columns": ["line"],
            "truncate_ragged_lines": True,
            "infer_schema_length": 0,
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "taxonomy_id": pl.Utf8,
    "name": pl.Utf8,
    "rank": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# kraken report rank codes. A trailing digit marks an intermediate level
# (``D1`` = sub-domain), which collapses onto its parent rank here.
_RANK_CODES = {
    "U": "unclassified",
    "R": "root",
    "D": "domain",
    "K": "kingdom",
    "P": "phylum",
    "C": "class",
    "O": "order",
    "F": "family",
    "G": "genus",
    "S": "species",
}

_RANK_ORDER = [
    "species",
    "genus",
    "family",
    "order",
    "class",
    "phylum",
    "kingdom",
    "domain",
    "superkingdom",
    "root",
    "unclassified",
]


def _field(parts: pl.Expr, i: int) -> pl.Expr:
    return parts.list.get(i, null_on_oob=True).str.strip_chars()


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Classify each report line and collect the id -> (name, rank) pairs."""
    lines = sources["reports"]
    if "line" not in lines.columns:
        raise ValueError("taxon_names: the report reader did not produce a `line` column")

    parts = pl.col("line").str.split("\t")
    n = parts.list.len()
    numeric = r"^\d+$"

    is_kraken2 = (n == 6) & _field(parts, 4).str.contains(numeric)
    is_krakenuniq = (n == 9) & _field(parts, 6).str.contains(numeric)
    is_centrifuge = (n == 7) & _field(parts, 1).str.contains(numeric)

    rank_code = _field(parts, 3).str.replace_all(r"\d", "")

    harvested = (
        lines.filter(pl.col("line").is_not_null() & (pl.col("line").str.strip_chars() != ""))
        .with_columns(
            pl.when(is_kraken2)
            .then(_field(parts, 4))
            .when(is_krakenuniq)
            .then(_field(parts, 6))
            .when(is_centrifuge)
            .then(_field(parts, 1))
            .otherwise(None)
            .alias("taxonomy_id"),
            pl.when(is_kraken2)
            .then(_field(parts, 5))
            .when(is_krakenuniq)
            .then(_field(parts, 8))
            .when(is_centrifuge)
            .then(_field(parts, 0))
            .otherwise(None)
            .alias("name"),
            pl.when(is_kraken2)
            .then(rank_code.replace_strict(_RANK_CODES, default="unknown"))
            .when(is_krakenuniq)
            .then(_field(parts, 7).str.to_lowercase())
            .when(is_centrifuge)
            .then(_field(parts, 2).str.to_lowercase())
            .otherwise(None)
            .alias("rank"),
        )
        .drop_nulls("taxonomy_id")
        .filter(pl.col("name").is_not_null() & (pl.col("name") != ""))
        .select("taxonomy_id", "name", "rank")
    )

    if harvested.is_empty():
        raise ValueError(
            "taxon_names: no kraken2 / krakenuniq / centrifuge report line could be parsed"
        )

    # One row per id, preferring the most specific rank the reports agree on.
    order = {rank: i for i, rank in enumerate(_RANK_ORDER)}
    return (
        harvested.with_columns(
            pl.col("rank").fill_null("unknown"),
            pl.col("rank").replace_strict(order, default=len(_RANK_ORDER)).alias("_rank_order"),
        )
        .sort(["taxonomy_id", "_rank_order"])
        .unique(subset=["taxonomy_id"], keep="first", maintain_order=True)
        .drop("_rank_order")
        .sort("taxonomy_id")
    )
