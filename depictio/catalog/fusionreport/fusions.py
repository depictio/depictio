"""Turn the fusion-report consensus CSV into one tidy row per fusion.

fusion-report reads every caller a run executed and writes ``<sample>.fusions.csv``:
one row per fusion, the knowledge bases that already know it, the Fusion Indication
Index (FII, the 0-1 score fusion-report ranks by), the arithmetic behind that score
and one free-text column per caller holding that caller's evidence for the fusion
(empty when the caller did not report it).

This recipe keeps the scalar half of that file and turns the per-caller columns
into 0/1 membership flags, which is what a set-intersection view of the callers
needs. The evidence strings themselves are parsed by ``caller_evidence.py``.

The recipe harness concatenates the globbed per-sample files without their path and
the CSV carries no sample column, so no ``sample`` column can be derived: the
FUSION is the unit of analysis here, and cross-collection links are keyed on it.

Output columns: fusion, gene_5p, gene_3p, databases, n_databases, fii,
explained_fii, arriba, fusioncatcher, starfusion, n_tools, tool_support, rank
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusions",
        glob_pattern="fusionreport/*/*.fusions.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "fusion": pl.Utf8,
    "gene_5p": pl.Utf8,
    "gene_3p": pl.Utf8,
    "databases": pl.Utf8,
    "n_databases": pl.Int64,
    "fii": pl.Float64,
    "explained_fii": pl.Utf8,
    "arriba": pl.Int64,
    "fusioncatcher": pl.Int64,
    "starfusion": pl.Int64,
    "n_tools": pl.Int64,
    "tool_support": pl.Utf8,
    "rank": pl.Int64,
}

# Every caller fusion-report knows about. A run only writes the columns for the
# callers it executed, so the missing ones are filled with 0 rather than dropped:
# the UpSet set columns must stay stable across runs.
CALLERS = ("arriba", "fusioncatcher", "starfusion")


def _column(df: pl.DataFrame, *candidates: str) -> str | None:
    """First of ``candidates`` present in ``df``, case-insensitively."""
    lowered = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        hit = lowered.get(candidate.lower())
        if hit is not None:
            return hit
    return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Flatten the consensus table and flag which callers found each fusion."""
    df = sources["fusions"]

    fusion_col = _column(df, "Fusion", "fusion")
    if fusion_col is None:
        raise ValueError(f"fusions: no 'Fusion' column in {df.columns}")
    fii_col = _column(df, "Fusion Indication Index (FII)", "FII", "Score")
    if fii_col is None:
        raise ValueError(f"fusions: no FII column in {df.columns}")
    explained_col = _column(df, "Explained FII", "Explained score")
    databases_col = _column(df, "Databases")

    partners = pl.col(fusion_col).cast(pl.Utf8).str.splitn("--", 2)
    exprs: list[pl.Expr] = [
        pl.col(fusion_col).cast(pl.Utf8).alias("fusion"),
        partners.struct.field("field_0").fill_null("").alias("gene_5p"),
        partners.struct.field("field_1").fill_null("").alias("gene_3p"),
        pl.col(fii_col).cast(pl.Float64, strict=False).alias("fii"),
    ]
    exprs.append(
        pl.col(explained_col).cast(pl.Utf8).fill_null("").alias("explained_fii")
        if explained_col
        else pl.lit("", dtype=pl.Utf8).alias("explained_fii")
    )
    exprs.append(
        pl.col(databases_col).cast(pl.Utf8).fill_null("").str.strip_chars().alias("databases")
        if databases_col
        else pl.lit("", dtype=pl.Utf8).alias("databases")
    )
    for caller in CALLERS:
        col = _column(df, caller)
        if col is None:
            exprs.append(pl.lit(0, dtype=pl.Int64).alias(caller))
            continue
        called = pl.col(col).cast(pl.Utf8).fill_null("").str.strip_chars().str.len_chars() > 0
        exprs.append(called.cast(pl.Int64).alias(caller))

    out = df.select(exprs)

    n_tools = pl.sum_horizontal([pl.col(c) for c in CALLERS]).cast(pl.Int64)
    out = out.with_columns(
        pl.when(pl.col("databases").str.len_chars() == 0)
        .then(pl.lit(0, dtype=pl.Int64))
        .otherwise(pl.col("databases").str.split(",").list.len().cast(pl.Int64))
        .alias("n_databases"),
        n_tools.alias("n_tools"),
    ).with_columns(
        pl.when(pl.col("n_tools") == 1)
        .then(pl.lit("1 caller"))
        .otherwise(pl.col("n_tools").cast(pl.Utf8) + pl.lit(" callers"))
        .alias("tool_support"),
    )

    # Rank mirrors fusion-report's own ordering: the FII first, the number of
    # agreeing callers as the tie-break, the name last so the rank is stable.
    out = out.sort(
        ["fii", "n_tools", "fusion"], descending=[True, True, False], nulls_last=True
    ).with_row_index(name="rank", offset=1)

    return out.select(list(EXPECTED_SCHEMA)).with_columns(pl.col("rank").cast(pl.Int64))
