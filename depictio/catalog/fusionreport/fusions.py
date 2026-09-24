"""Turn the fusion-report consensus CSV into one tidy row per fusion.

fusion-report reads every caller a run executed and writes ``<sample>.fusions.csv``:
one row per fusion, the knowledge bases that already know it, the Fusion Indication
Index (FII, the 0-1 score fusion-report ranks by), the arithmetic behind that score
and one free-text column per caller holding that caller's evidence for the fusion
(empty when the caller did not report it).

This recipe keeps the scalar half of that file and turns the per-caller columns
into 0/1 membership flags, which is what a set-intersection view of the callers
needs. The evidence strings themselves are parsed by ``caller_evidence.py``.

The CSV carries no sample column, so the source declares ``source_path`` and the
sample is read off the file name (``fusionreport/<sample>/<sample>.fusions.csv``).
One row is one fusion in one sample, and the rank is fusion-report's order
WITHIN that sample.

The caller columns are not a fixed list: every column of the file that is not
one of fusion-report's own (fusion, databases, FII, explained FII) is a caller
the run executed, so a run with ``--tools`` narrowed or widened gets exactly its
callers, each as a 0/1 flag named after the tool.

Output columns: sample, fusion, gene_5p, gene_3p, databases, n_databases, fii,
explained_fii, <one 0/1 column per caller>, n_tools, tool_support, rank
"""

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# The sample exists only in the file NAME: the source hands every row the path
# of its file, and the sample is the basename minus the suffix.
_SOURCE_PATH = "_source_path"
_SAMPLE_SUFFIX = ".fusions.csv"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusions",
        source_path=_SOURCE_PATH,
        glob_pattern="fusionreport/*/*.fusions.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "fusion": pl.Utf8,
    "gene_5p": pl.Utf8,
    "gene_3p": pl.Utf8,
    "databases": pl.Utf8,
    "n_databases": pl.Int64,
    "fii": pl.Float64,
    "explained_fii": pl.Utf8,
    "n_tools": pl.Int64,
    "tool_support": pl.Utf8,
    "rank": pl.Int64,
}
# The callers nf-core/rnafusion runs by default, type-checked when present. Any
# other caller column the file carries is published the same way.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "arriba": pl.Int64,
    "fusioncatcher": pl.Int64,
    "starfusion": pl.Int64,
}

# fusion-report's own columns; every other column is one caller's evidence.
_REPORT_COLUMNS = frozenset(
    {
        "fusion",
        "databases",
        "fusion indication index (fii)",
        "fii",
        "score",
        "explained fii",
        "explained score",
        _SOURCE_PATH,
    }
)


def caller_columns(df: pl.DataFrame) -> dict[str, str]:
    """``{source column: caller flag name}`` for every caller column of the file."""
    return {
        col: re.sub(r"[^0-9a-z]+", "_", col.strip().lower()).strip("_")
        for col in df.columns
        if col.strip().lower() not in _REPORT_COLUMNS
    }


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
        pl.col(_SOURCE_PATH)
        .str.split("/")
        .list.last()
        .str.strip_suffix(_SAMPLE_SUFFIX)
        .alias("sample")
        if _SOURCE_PATH in df.columns
        else pl.lit("", dtype=pl.Utf8).alias("sample"),
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
    callers = caller_columns(df)
    if not callers:
        raise ValueError(f"fusions: no caller column beside fusion-report's own in {df.columns}")
    for col, caller in callers.items():
        called = pl.col(col).cast(pl.Utf8).fill_null("").str.strip_chars().str.len_chars() > 0
        exprs.append(called.cast(pl.Int64).alias(caller))

    out = df.select(exprs)

    n_tools = pl.sum_horizontal([pl.col(c) for c in callers.values()]).cast(pl.Int64)
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

    # Rank mirrors fusion-report's own ordering, per sample: the FII first, the
    # number of agreeing callers as the tie-break, the name last so it is stable.
    out = out.sort(
        ["sample", "fii", "n_tools", "fusion"],
        descending=[False, True, True, False],
        nulls_last=True,
    ).with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int64).over("sample").alias("rank"))

    fixed = [c for c in EXPECTED_SCHEMA if c not in ("n_tools", "tool_support", "rank")]
    return out.select([*fixed, *callers.values(), "n_tools", "tool_support", "rank"])
