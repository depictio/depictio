"""Sample PCA of a merged Salmon TPM matrix, plus the per-sample library summary.

One row per sample: the first principal components of the log2(TPM + 1) matrix
restricted to the ``TOP_N`` most variable genes (the reduction exploratory
RNA-seq PCAs apply), joined to the quantification summary the same matrix
yields — how many genes the sample detects, how many it expresses above
``EXPRESSED_TPM``, and the median TPM of the genes it detects. Coordinates and
summary live in one output on purpose: the sample-overview tiles (cards, filters)
and the embedding then read one data collection and filter each other.

Sources:
    matrix       ``salmon/salmon.merged.gene_tpm.tsv`` — the layout a plain
                 salmon/tximport run writes. Repoint a pipeline that publishes
                 it elsewhere (nf-core/rnaseq: ``star_salmon/``) with
                 ``source_overrides: {matrix: {path: "star_salmon/salmon.merged.gene_tpm.tsv"}}``.
    samplesheet  optional pipeline ``--input`` sheet (CSV or TSV).

Output (canonical ``embedding`` schema + colouring and summary columns):
    sample_id : Utf8, dim_1 : Float64, dim_2 : Float64, dim_3 : Float64
    group : Utf8           the sheet's most factor-like column (fewest levels
                           >= 2); when the sheet declares none, the condition
                           read off ``<condition>_REP<n>`` sample names; else
                           ``"all"``. Bind ``color_col`` to it.
    genes_detected : Int64 genes with TPM > 0 in this sample
    genes_expressed : Int64 genes with TPM >= ``EXPRESSED_TPM``
    median_tpm : Float64   median TPM over the genes the sample detects
    <sheet columns>        every other sheet column, names sanitised
                           (``Sample condition`` -> ``Sample_condition``) so any
                           of them can be picked as colour / hover.
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.dimreduction import run_pca

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
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "group": pl.Utf8,
    "genes_detected": pl.Int64,
    "genes_expressed": pl.Int64,
    "median_tpm": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "dim_3": pl.Float64,
}

TOP_N = 500
EXPRESSED_TPM = 1.0
MAX_LEVELS = 12

_REPLICATE_SUFFIX = re.compile(r"[._-](?:rep|r)?\d+$", re.IGNORECASE)
_RESERVED = ("sample_id", "dim_1", "dim_2", "dim_3", "group")
_SUMMARY = ("genes_detected", "genes_expressed", "median_tpm")


# --- samplesheet helpers (duplicated in the sibling recipes: recipes may not
# import each other) -----------------------------------------------------------


def sanitise_column(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


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


def annotation_columns(sheet: pl.DataFrame, id_col: str) -> list[str]:
    """Sheet columns worth carrying over: everything but a second identifier.

    A column with one distinct value per sample (a FASTQ path, a run accession)
    can neither colour nor group anything; it only widens the table. Kept when
    the sheet is too small for the test to mean anything.
    """
    n = sheet.height
    cols = [c for c in sheet.columns if c != id_col]
    if n <= 2:
        return cols
    return [c for c in cols if sheet[c].cast(pl.Utf8).n_unique() < n]


def groups_from_sample_names(sample_names: list[str]) -> list[str] | None:
    """Conditions read off ``<condition>_REP<n>`` style names, else ``None``."""
    stripped = [_REPLICATE_SUFFIX.sub("", s) or s for s in sample_names]
    levels = set(stripped)
    if 2 <= len(levels) < len(sample_names):
        return stripped
    return None


# --- matrix helpers -----------------------------------------------------------


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
    if len(sample_cols) < 2:
        raise ValueError("salmon sample_pca: need at least two sample columns")
    return id_col, name_col, sample_cols


def library_summary(matrix: pl.DataFrame, sample_cols: list[str]) -> pl.DataFrame:
    """Detected / expressed gene counts and median detected TPM, per sample."""
    rows = []
    for col in sample_cols:
        tpm = matrix[col].cast(pl.Float64)
        detected = tpm.filter(tpm > 0)
        rows.append(
            {
                "sample_id": col,
                "genes_detected": int(detected.len()),
                "genes_expressed": int(tpm.filter(tpm >= EXPRESSED_TPM).len()),
                "median_tpm": float(detected.median()) if detected.len() else 0.0,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "sample_id": pl.Utf8,
            "genes_detected": pl.Int64,
            "genes_expressed": pl.Int64,
            "median_tpm": pl.Float64,
        },
    )


def samples_by_genes(matrix: pl.DataFrame, sample_cols: list[str]) -> pl.DataFrame:
    """Transpose the top-``TOP_N`` variance genes into a samples x genes matrix."""
    logged = matrix.select(
        [(pl.col(c).cast(pl.Float64) + 1.0).log(2).alias(c) for c in sample_cols]
    )
    logged = logged.with_columns(
        pl.concat_list([pl.col(c) for c in sample_cols]).list.var().alias("_variance")
    )
    top = (
        logged.filter(pl.col("_variance").is_not_null())
        .sort("_variance", descending=True)
        .head(TOP_N)
        .drop("_variance")
    )
    arr = top.to_numpy().T  # samples x genes
    return pl.DataFrame(
        {
            "sample_id": sample_cols,
            **{f"gene_{i}": arr[:, i].tolist() for i in range(arr.shape[1])},
        }
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """PCA coordinates + library summary per sample, joined to the sample sheet."""
    matrix = sources["matrix"]
    _id_col, _name_col, sample_cols = split_matrix(matrix)

    coords = run_pca(
        samples_by_genes(matrix, sample_cols),
        n_components=3 if len(sample_cols) >= 4 else 2,
        scale=False,
    )
    coords = coords.join(library_summary(matrix, sample_cols), on="sample_id", how="left")

    sheet = sources.get("samplesheet")
    meta: pl.DataFrame | None = None
    group_col: str | None = None
    if sheet is not None:
        sheet = fix_delimiter(sheet)
        id_col = sample_id_column(sheet, coords["sample_id"].to_list())
        factors = factor_columns(sheet, id_col)
        renamed: dict[str, str] = {id_col: "sample_id"}
        for col in annotation_columns(sheet, id_col):
            new = sanitise_column(col)
            if new in _RESERVED or new in _SUMMARY or new in renamed.values():
                new = f"{new}_sheet"
            renamed[col] = new
        meta = (
            sheet.with_columns(pl.col(id_col).cast(pl.Utf8))
            .unique(subset=[id_col], keep="first")
            .select(list(renamed))
            .rename(renamed)
        )
        meta = meta.with_columns(
            [pl.col(c).cast(pl.Utf8) for c in meta.columns if c != "sample_id"]
        )
        group_col = renamed.get(factors[0]) if factors else None

    result = coords if meta is None else coords.join(meta, on="sample_id", how="left")
    if group_col is not None:
        result = result.with_columns(pl.col(group_col).alias("group"))
    else:
        derived = groups_from_sample_names(result["sample_id"].to_list())
        result = result.with_columns(
            pl.Series("group", derived, dtype=pl.Utf8)
            if derived is not None
            else pl.lit("all").alias("group")
        )
    result = result.with_columns(pl.col("group").fill_null("unknown"))

    ordered = ["sample_id", "dim_1", "dim_2"] + (["dim_3"] if "dim_3" in result.columns else [])
    ordered += ["group", *_SUMMARY]
    ordered += [c for c in result.columns if c not in ordered]
    return result.select(ordered)
