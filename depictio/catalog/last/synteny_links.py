"""Synteny links between the target and each query genome, from the PSL export of the one-to-one alignment.

nf-core/pairgenomealign keeps its one-to-one alignment as MAF, which carries the
aligned sequences and runs to gigabytes per genome pair. With
``--export_aln_to psl`` it also writes ``<target>___<query>.psl.gz``: one line
per alignment with the coordinates on both genomes and the match counts, and no
sequence. That is the shape a synteny view needs, so this recipe reads the PSL
export and ignores the MAF.

Each alignment becomes one link between a target locus and a query locus, placed
at the midpoint of the aligned interval on each side, with the matching bases as
its weight and its orientation as its category (``same strand`` or
``inverted``). Query sequence names get a ``q:`` prefix: two assemblies of
related species often share names such as ``chr1``, and a ring that merged them
would draw a self-link where there is a cross-genome one.

A genome pair holds tens of thousands of alignments, most of them short, and a
chord ring stays readable with a few thousand. The recipe keeps the
``MAX_LINKS_PER_PAIR`` alignments with the most matching bases per pair, which
are the long collinear blocks that make the synteny picture; the ``rank`` column
records the order so a tile can be narrowed further.

Output columns:
    pair, target, query, label, chrom_a, start_a, end_a, pos_a, chrom_b, start_b,
    end_b, pos_b, weight, aligned_bp, identity_pct, category, rank
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.genome_pairs import pair_from_path, split_pair

MAX_LINKS_PER_PAIR = 2000
QUERY_PREFIX = "q:"
_SOURCE_PATH = "_source_path"
_SUFFIX = ".psl.gz"

# The 21 PSL columns, in order (the format has no header). Polars reads them as
# column_1..column_21; they are renamed after the read so an empty export (no
# columns at all) still reads as an empty frame.
_PSL_COLUMNS = [
    "matches",
    "mismatches",
    "rep_matches",
    "n_count",
    "q_num_insert",
    "q_base_insert",
    "t_num_insert",
    "t_base_insert",
    "strand",
    "q_name",
    "q_size",
    "q_start",
    "q_end",
    "t_name",
    "t_size",
    "t_start",
    "t_end",
    "block_count",
    "block_sizes",
    "q_starts",
    "t_starts",
]

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="psl",
        glob_pattern="alignment/*.psl.gz",
        format="TSV",
        source_path=_SOURCE_PATH,
        read_kwargs={
            "has_header": False,
            "infer_schema_length": 0,
            "quote_char": None,
            "raise_if_empty": False,
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "pair": pl.Utf8,
    "target": pl.Utf8,
    "query": pl.Utf8,
    "label": pl.Utf8,
    "chrom_a": pl.Utf8,
    "start_a": pl.Int64,
    "end_a": pl.Int64,
    "pos_a": pl.Int64,
    "chrom_b": pl.Utf8,
    "start_b": pl.Int64,
    "end_b": pl.Int64,
    "pos_b": pl.Int64,
    "weight": pl.Int64,
    "aligned_bp": pl.Int64,
    "identity_pct": pl.Float64,
    "category": pl.Utf8,
    "rank": pl.Int64,
}

_INT_COLS = ("matches", "mismatches", "q_start", "q_end", "t_start", "t_end")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["psl"]
    if df is None or df.is_empty():
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    df = df.rename(
        {
            f"column_{i}": name
            for i, name in enumerate(_PSL_COLUMNS, 1)
            if f"column_{i}" in df.columns
        }
    )
    df = df.with_columns(pl.col(c).cast(pl.Int64, strict=False) for c in _INT_COLS).filter(
        pl.all_horizontal(pl.col(c).is_not_null() for c in _INT_COLS)
        & pl.col("t_name").is_not_null()
        & pl.col("q_name").is_not_null()
    )
    df = df.with_columns(*split_pair(pair_from_path(_SOURCE_PATH, _SUFFIX)))
    aligned = pl.col("matches") + pl.col("mismatches")
    df = df.with_columns(
        pl.col("matches").rank(method="ordinal", descending=True).over("pair").alias("rank")
    ).filter(pl.col("rank") <= MAX_LINKS_PER_PAIR)
    out = df.select(
        "pair",
        "target",
        "query",
        pl.concat_str(
            pl.col("t_name"), pl.lit(":"), pl.col("t_start") + 1, pl.lit("-"), pl.col("t_end")
        ).alias("label"),
        pl.col("t_name").alias("chrom_a"),
        pl.col("t_start").alias("start_a"),
        pl.col("t_end").alias("end_a"),
        ((pl.col("t_start") + pl.col("t_end")) // 2).alias("pos_a"),
        (pl.lit(QUERY_PREFIX) + pl.col("q_name")).alias("chrom_b"),
        pl.col("q_start").alias("start_b"),
        pl.col("q_end").alias("end_b"),
        ((pl.col("q_start") + pl.col("q_end")) // 2).alias("pos_b"),
        pl.col("matches").alias("weight"),
        (pl.col("t_end") - pl.col("t_start")).alias("aligned_bp"),
        pl.when(aligned > 0)
        .then(pl.col("matches") / aligned * 100.0)
        .otherwise(None)
        .round(3)
        .alias("identity_pct"),
        # "-" for DNA; two letters (query, target) in translated PSL.
        pl.when(pl.col("strand").is_in(["-", "+-", "-+"]))
        .then(pl.lit("inverted"))
        .otherwise(pl.lit("same strand"))
        .alias("category"),
        pl.col("rank").cast(pl.Int64),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["query", "rank"])
