"""Merged Salmon TPMs as one long row per gene and sample, for a gene explorer.

The merged matrix is wide (one column per sample), which no per-gene view can
filter or group on. This recipe unpivots it into the long form a gene explorer
needs: pick genes, compare their expression across samples, split by condition.

Genes with less than ``MIN_TPM`` in every sample are dropped. On a human
annotation that is roughly two thirds of the rows, all of them noise: they make
the table and its gene picker unusable without adding a single readable point.

Sources:
    matrix       ``salmon/salmon.merged.gene_tpm.tsv`` — the layout a plain
                 salmon/tximport run writes. Repoint a pipeline that publishes
                 it elsewhere (nf-core/rnaseq: ``star_salmon/``) with
                 ``source_overrides: {matrix: {path: "star_salmon/salmon.merged.gene_tpm.tsv"}}``.
    samplesheet  optional pipeline ``--input`` sheet (CSV or TSV); supplies
                 ``group``.

Output (one row per kept gene x sample):
    gene_id : Utf8, gene_name : Utf8, sample : Utf8
    tpm : Float64, log2_tpm : Float64   log2(TPM + 1), the scale expression is
                                        compared on
    group : Utf8   the sheet's most factor-like column, else the condition read
                   off ``<condition>_REP<n>`` sample names, else ``"all"``
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="matrix",
        path="salmon/salmon.merged.gene_tpm.tsv",
        format="tsv",
        read_kwargs={"null_values": ["NA"], "infer_schema_length": 10000},
    ),
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        optional=True,
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "sample": pl.Utf8,
    "tpm": pl.Float64,
    "log2_tpm": pl.Float64,
    "group": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

MIN_TPM = 1.0
MAX_LEVELS = 12

_REPLICATE_SUFFIX = re.compile(r"[._-](?:rep|r)?\d+$", re.IGNORECASE)


# --- samplesheet helpers (duplicated in the sibling recipes: recipes may not
# import each other) -----------------------------------------------------------


def fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=10000)
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


def groups_from_sample_names(sample_names: list[str]) -> list[str] | None:
    """Conditions read off ``<condition>_REP<n>`` style names, else ``None``."""
    stripped = [_REPLICATE_SUFFIX.sub("", s) or s for s in sample_names]
    levels = set(stripped)
    if 2 <= len(levels) < len(sample_names):
        return stripped
    return None


def split_matrix(matrix: pl.DataFrame) -> tuple[str, str | None, list[str]]:
    """(feature-id column, gene-symbol column or None, numeric sample columns)."""
    id_col = next(
        (c for c in matrix.columns if c.lower() in ("gene_id", "feature_id", "id")),
        matrix.columns[0],
    )
    name_col = next((c for c in matrix.columns if c.lower() in ("gene_name", "symbol")), None)
    sample_cols = [
        c for c in matrix.columns if c not in (id_col, name_col) and matrix[c].dtype.is_numeric()
    ]
    if not sample_cols:
        raise ValueError(f"salmon: no numeric sample columns in {matrix.columns}")
    return id_col, name_col, sample_cols


def group_map(sheet: pl.DataFrame | None, sample_cols: list[str]) -> dict[str, str]:
    """sample -> condition, from the sheet's factor column or the sample names."""
    if sheet is not None:
        sheet = fix_delimiter(sheet)
        id_col = sample_id_column(sheet, sample_cols)
        factors = factor_columns(sheet, id_col)
        if factors:
            lookup = sheet.with_columns(pl.col(id_col).cast(pl.Utf8)).unique(
                subset=[id_col], keep="first"
            )
            mapping = dict(
                zip(
                    lookup[id_col].to_list(),
                    lookup[factors[0]].cast(pl.Utf8).fill_null("unknown").to_list(),
                )
            )
            return {s: mapping.get(s, "unknown") for s in sample_cols}
    derived = groups_from_sample_names(sample_cols)
    if derived is not None:
        return dict(zip(sample_cols, derived))
    return {s: "all" for s in sample_cols}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Long gene x sample TPMs for the genes expressed in at least one sample."""
    matrix = sources["matrix"]
    id_col, name_col, sample_cols = split_matrix(matrix)

    wide = matrix.select(
        [
            pl.col(id_col).cast(pl.Utf8).alias("gene_id"),
            pl.col(name_col).cast(pl.Utf8).alias("gene_name")
            if name_col
            else pl.col(id_col).cast(pl.Utf8).alias("gene_name"),
            *[pl.col(c).cast(pl.Float64) for c in sample_cols],
        ]
    ).filter(pl.max_horizontal([pl.col(c) for c in sample_cols]) >= MIN_TPM)

    groups = group_map(sources.get("samplesheet"), sample_cols)
    long = wide.unpivot(
        index=["gene_id", "gene_name"],
        on=sample_cols,
        variable_name="sample",
        value_name="tpm",
    )
    return long.with_columns(
        [
            pl.col("gene_name").fill_null(pl.col("gene_id")),
            (pl.col("tpm") + 1.0).log(2).alias("log2_tpm"),
            pl.col("sample").replace_strict(groups, default="all").alias("group"),
        ]
    ).select(["gene_id", "gene_name", "sample", "tpm", "log2_tpm", "group"])
