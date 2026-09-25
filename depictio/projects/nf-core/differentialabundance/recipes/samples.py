"""Sample hub for nf-core/differentialabundance: the sample sheet plus DESeq2 size factors.

The pipeline's ``--input`` sheet is free-form (``observations_id_col`` names
the sample column, any other column is a covariate), so a dashboard cannot
know the id column in advance. This recipe normalises it to a stable
``sample_id`` and a stable ``group`` (the most factor-like column: fewest
distinct values >= 2, so a two-level condition wins over a batch column),
keeps every other column under a sanitised name, and joins the per-sample
DESeq2 size factor (``other/deseq2/*.deseq2.sizefactors.tsv``, identical
across contrasts, so the mean over contrasts is taken).

A study is rarely one factor. The same ranking that picks ``group`` also
publishes the next three factor-like columns as ``factor_2``, ``factor_3`` and
``factor_4``, so a shipped dashboard can put a persistent filter on each without
knowing what any run's sheet calls them. Their source column names are published
as ``factor_2_name`` and friends, which is what a panel shows a reader instead of
"factor 2". Every column also keeps its own sanitised name, so nothing is hidden
by the aliasing. The three aliases are ALWAYS published: a sheet with fewer
factors gets the missing ones as an all-null column named ``none``, so the
persistent filters bound to them never point at a missing column on any tab.

Sources:
    samplesheet  ``input/samplesheet.tsv`` by default; the template repoints it
                 at ``{SAMPLESHEET_FILE}`` (TSV or CSV; a CSV read with a tab
                 separator is re-split).
    sizefactors  ``other/deseq2/**/*.deseq2.sizefactors.tsv`` (columns ``sample``,
                 ``sizeFactor``).

Output:
    sample_id : Utf8, group : Utf8, size_factor : Float64,
    factor_2 .. factor_4 : Utf8 (null when the sheet has fewer factors),
    factor_2_name .. factor_4_name : Utf8 ("none" for a missing factor),
    <sanitised sheet columns> : Utf8
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 10000},
    ),
    RecipeSource(
        ref="sizefactors",
        glob_pattern="other/deseq2/**/*.deseq2.sizefactors.tsv",
        format="tsv",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "group": pl.Utf8,
    "size_factor": pl.Float64,
    "factor_2": pl.Utf8,
    "factor_2_name": pl.Utf8,
    "factor_3": pl.Utf8,
    "factor_3_name": pl.Utf8,
    "factor_4": pl.Utf8,
    "factor_4_name": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

MAX_LEVELS = 12
# Highest `factor_<n>` alias rank published. `group` is factor 1, so this
# publishes factor_2 to factor_4: three aliases beside the condition, which
# covers the designs this pipeline is used for (treatment, timepoint, batch)
# without turning a sheet of free-text columns into a wall of dead filters.
N_FACTOR_ALIASES = 4
# A filter is only worth a control when it has at least two levels and few
# enough to pick from; above this a column is an identifier, not a factor.
MAX_FILTER_LEVELS = 6
# `factor_<n>_name` of an alias the sheet has no factor for.
MISSING_FACTOR_NAME = "none"


def sanitise_column(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    if df.width == 1 and "," in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), infer_schema_length=10000)
    return df


def sample_id_column(sheet: pl.DataFrame, sample_names: list[str]) -> str:
    wanted = set(sample_names)
    best, best_hits = sheet.columns[0], -1
    for col in sheet.columns:
        hits = len(wanted & set(sheet[col].cast(pl.Utf8).to_list()))
        if hits > best_hits:
            best, best_hits = col, hits
    return best


def factor_columns(sheet: pl.DataFrame, id_col: str) -> list[str]:
    n = sheet.height
    upper = max(2, min(MAX_LEVELS, n - 1))
    scored = []
    for idx, col in enumerate(sheet.columns):
        if col == id_col:
            continue
        k = sheet[col].cast(pl.Utf8).drop_nulls().n_unique()
        if 2 <= k <= upper:
            scored.append((k, idx, col))
    return [col for _, _, col in sorted(scored)]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Normalised sample sheet joined to the DESeq2 size factors."""
    sheet = fix_delimiter(sources["samplesheet"])
    sizes = sources["sizefactors"]

    size_sample_col = next((c for c in sizes.columns if c.lower() in ("sample", "sample_id")), None)
    size_value_col = next(
        (c for c in sizes.columns if c.lower() in ("sizefactor", "size_factor")), None
    )
    if size_sample_col is None or size_value_col is None:
        raise ValueError(
            f"deseq2 sizefactors: expected sample/sizeFactor columns, got {sizes.columns}"
        )
    sizes = (
        sizes.select(
            pl.col(size_sample_col).cast(pl.Utf8).str.strip_chars().alias("sample_id"),
            pl.col(size_value_col).cast(pl.Float64, strict=False).alias("size_factor"),
        )
        .group_by("sample_id")
        .agg(pl.col("size_factor").mean())
    )

    id_col = sample_id_column(sheet, sizes["sample_id"].to_list())
    factors = factor_columns(sheet, id_col)

    renamed: dict[str, str] = {id_col: "sample_id"}
    for col in sheet.columns:
        if col == id_col:
            continue
        new = sanitise_column(col)
        if new in ("sample_id", "group", "size_factor") or new in renamed.values():
            new = f"{new}_sheet"
        renamed[col] = new
    samples = (
        sheet.with_columns(pl.col(id_col).cast(pl.Utf8).str.strip_chars())
        .unique(subset=[id_col], keep="first")
        .rename(renamed)
    )
    samples = samples.with_columns(
        [pl.col(c).cast(pl.Utf8) for c in samples.columns if c != "sample_id"]
    )
    if factors:
        samples = samples.with_columns(
            pl.col(renamed[factors[0]]).fill_null("unknown").alias("group")
        )
    else:
        samples = samples.with_columns(pl.lit("all").alias("group"))

    # Stable aliases for the factors after the leading one. `factor_columns`
    # is already sorted by level count, so factor_2 is the next most
    # factor-like column. Columns with more levels than a reader can pick from
    # are skipped here even though they stay in the frame under their own name.
    ordered_aliases: list[str] = []
    rank = 2
    for col in factors[1:]:
        if rank > N_FACTOR_ALIASES:
            break
        source = renamed[col]
        levels = samples.get_column(source).cast(pl.Utf8).drop_nulls().n_unique()
        if levels > MAX_FILTER_LEVELS:
            continue
        samples = samples.with_columns(
            pl.col(source).fill_null("unknown").alias(f"factor_{rank}"),
            pl.lit(col).alias(f"factor_{rank}_name"),
        )
        ordered_aliases += [f"factor_{rank}", f"factor_{rank}_name"]
        rank += 1
    # Pad to the full set so the persistent factor filters always bind.
    while rank <= N_FACTOR_ALIASES:
        samples = samples.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias(f"factor_{rank}"),
            pl.lit(MISSING_FACTOR_NAME).alias(f"factor_{rank}_name"),
        )
        ordered_aliases += [f"factor_{rank}", f"factor_{rank}_name"]
        rank += 1

    result = samples.join(sizes, on="sample_id", how="left")
    ordered = ["sample_id", "group", "size_factor", *ordered_aliases]
    ordered += [c for c in result.columns if c not in ordered]
    return result.select(ordered).sort("sample_id")
