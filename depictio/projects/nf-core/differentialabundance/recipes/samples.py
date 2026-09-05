"""Sample hub for nf-core/differentialabundance: the sample sheet plus DESeq2 size factors.

The pipeline's ``--input`` sheet is free-form (``observations_id_col`` names
the sample column, any other column is a covariate), so a dashboard cannot
know the id column in advance. This recipe normalises it to a stable
``sample_id`` and a stable ``group`` (the most factor-like column: fewest
distinct values >= 2, so a two-level condition wins over a batch column),
keeps every other column under a sanitised name, and joins the per-sample
DESeq2 size factor (``other/deseq2/*.deseq2.sizefactors.tsv``, identical
across contrasts, so the mean over contrasts is taken).

Sources:
    samplesheet  ``input/samplesheet.tsv`` by default; the template repoints it
                 at ``{SAMPLESHEET_FILE}`` (TSV or CSV; a CSV read with a tab
                 separator is re-split).
    sizefactors  ``other/deseq2/**/*.deseq2.sizefactors.tsv`` (columns ``sample``,
                 ``sizeFactor``).

Output:
    sample_id : Utf8, group : Utf8, size_factor : Float64, <sanitised sheet columns> : Utf8
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
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

MAX_LEVELS = 12


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

    result = samples.join(sizes, on="sample_id", how="left")
    ordered = ["sample_id", "group", "size_factor"]
    ordered += [c for c in result.columns if c not in ordered]
    return result.select(ordered).sort("sample_id")
