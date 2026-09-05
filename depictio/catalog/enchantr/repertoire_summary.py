"""One row per sample: clone counts, clone sizes and the three Hill numbers.

Joins the two per-sample tables of the enchantR repertoire analysis report:

* ``num_clones_table.tsv``: sequences that entered clonal assignment, the
  number of clones they collapsed into, and the smallest / median / largest
  clone as a sequence count.
* ``clonal_diversity.tsv``: alakazam's bootstrapped Hill profile, sliced at
  q = 0 (richness), q = 1 (exponential Shannon) and q = 2 (inverse Simpson),
  each with its confidence bounds, plus the evenness at q = 1.

The result is the tool's per-sample hub: the shape cards, a summary table and a
sequences-versus-clones scatter all read. ``sequences_per_clone`` is the mean
clone size, the plain-language version of the same signal.

The report's ``clone_size_freq_*`` columns are dropped: enchantR rounds them to
two decimals, which collapses every deep sample to 0.00.

Samples enchantR could not compute a diversity profile for (too few sequences)
keep their clone counts and carry null Hill numbers.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

_TABLES = "clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="num_clones", path=f"{_TABLES}/num_clones_table.tsv", format="TSV"),
    RecipeSource(
        ref="diversity", path=f"{_TABLES}/clonal_diversity.tsv", format="TSV", optional=True
    ),
]

# Diversity order -> output prefix. 0 = richness, 1 = exp(Shannon), 2 = 1/Simpson.
_ORDERS: dict[float, str] = {0.0: "richness", 1.0: "shannon", 2.0: "simpson"}
_DIVERSITY_COLS: list[str] = [
    *(f"{name}{suffix}" for name in _ORDERS.values() for suffix in ("", "_lower", "_upper")),
    "evenness",
    "evenness_lower",
    "evenness_upper",
]
_SIZE_COLS = ["clone_size_count_min", "clone_size_count_median", "clone_size_count_max"]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "sequences": pl.Int64,
    "number_of_clones": pl.Int64,
    "sequences_per_clone": pl.Float64,
    **{c: pl.Float64 for c in _SIZE_COLS},
    **{c: pl.Float64 for c in _DIVERSITY_COLS},
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def _subject(df: pl.DataFrame) -> pl.Expr:
    """The clone-definition group. A report without one gets a single group."""
    if "subject_id" in df.columns:
        return pl.col("subject_id").cast(pl.Utf8)
    return pl.lit("all", dtype=pl.Utf8).alias("subject_id")


def _diversity_slice(df: pl.DataFrame) -> pl.DataFrame:
    """Pivot the q in {0, 1, 2} rows of the Hill profile into one row per sample."""
    df = df.with_columns(
        pl.col("sample_id").cast(pl.Utf8),
        pl.col("q").cast(pl.Float64),
        *[
            pl.col(c).cast(pl.Float64)
            for c in ("d", "d_lower", "d_upper", "e", "e_lower", "e_upper")
        ],
    )
    out = df.select("sample_id").unique()
    for q, name in _ORDERS.items():
        out = out.join(
            df.filter(pl.col("q") == q).select(
                "sample_id",
                pl.col("d").alias(name),
                pl.col("d_lower").alias(f"{name}_lower"),
                pl.col("d_upper").alias(f"{name}_upper"),
            ),
            on="sample_id",
            how="left",
        )
    return out.join(
        df.filter(pl.col("q") == 1.0).select(
            "sample_id",
            pl.col("e").alias("evenness"),
            pl.col("e_lower").alias("evenness_lower"),
            pl.col("e_upper").alias("evenness_upper"),
        ),
        on="sample_id",
        how="left",
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join clone counts with the sliced Hill profile, one row per sample."""
    clones = sources["num_clones"]
    out = clones.select(
        pl.col("sample_id").cast(pl.Utf8),
        _subject(clones),
        pl.col("sequences").cast(pl.Int64),
        pl.col("number_of_clones").cast(pl.Int64),
        *[pl.col(c).cast(pl.Float64) for c in _SIZE_COLS if c in clones.columns],
    ).with_columns(
        (pl.col("sequences") / pl.col("number_of_clones"))
        .cast(pl.Float64)
        .alias("sequences_per_clone")
    )

    diversity = sources.get("diversity")
    if diversity is not None:
        out = out.join(_diversity_slice(diversity), on="sample_id", how="left")
    # Keep the schema stable whether or not the profile was written.
    missing = [c for c in _DIVERSITY_COLS if c not in out.columns]
    if missing:
        out = out.with_columns([pl.lit(None, dtype=pl.Float64).alias(c) for c in missing])

    ordered = [
        "sample_id",
        "subject_id",
        "sequences",
        "number_of_clones",
        "sequences_per_clone",
        *_SIZE_COLS,
        *_DIVERSITY_COLS,
    ]
    return out.select([c for c in ordered if c in out.columns]).sort("sample_id")
