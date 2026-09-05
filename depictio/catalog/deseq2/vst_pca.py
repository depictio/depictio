"""Sample PCA on the DESeq2 variance-stabilised matrix (embedding schema).

Reproduces the pipeline's exploratory PCA: the ``TOP_N`` most variable genes
of ``all.vst.tsv`` (``exploratory_n_features``, default 500), samples as
observations, no per-gene scaling (DESeq2 ``plotPCA`` convention), via
``depictio.recipes.lib.dimreduction.run_pca``.

Sources:
    vst          ``**/all.vst.tsv`` at any depth
    samplesheet  optional pipeline ``--input`` sheet (TSV or CSV; repoint it
                 with ``source_overrides: {samplesheet: {path: "{SAMPLESHEET_FILE}"}}``).

Output (canonical ``embedding`` schema + colouring columns):
    sample_id : Utf8, dim_1 : Float64, dim_2 : Float64, dim_3 : Float64
    group : Utf8      the sheet's most factor-like column (fewest levels >= 2),
                      ``"all"`` when no sheet was found. Bind ``color_col`` to it.
    <sheet columns>   every other sheet column, names sanitised
                      (``Condition genotype`` -> ``Condition_genotype``) so any of
                      them can be picked as colour / hover in the viz controls.
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.dimreduction import run_pca

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="vst",
        glob_pattern="**/all.vst.tsv",
        format="tsv",
        read_kwargs={"null_values": ["NA"], "infer_schema_length": 10000},
    ),
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.tsv",
        format="tsv",
        optional=True,
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "group": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "dim_3": pl.Float64,
}

TOP_N = 500
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


def _samples_by_genes(vst: pl.DataFrame, n: int = TOP_N) -> pl.DataFrame:
    """Transpose the top-``n`` variance genes into a samples x genes matrix."""
    id_col = next((c for c in vst.columns if c.lower() in ("gene_id", "feature_id", "id")), None)
    if id_col is None:
        id_col = vst.columns[0]
    sample_cols = [c for c in vst.columns if c != id_col and vst[c].dtype.is_numeric()]
    if len(sample_cols) < 2:
        raise ValueError("deseq2 vst_pca: need at least two sample columns")
    numeric = vst.select(sample_cols).with_columns(
        [pl.col(c).cast(pl.Float64) for c in sample_cols]
    )
    numeric = numeric.with_columns(
        pl.concat_list([pl.col(c) for c in sample_cols]).list.var().alias("_variance")
    )
    top = numeric.filter(pl.col("_variance").is_not_null()).sort("_variance", descending=True)
    top = top.head(n).drop("_variance")
    arr = top.to_numpy().T  # samples x genes
    return pl.DataFrame(
        {
            "sample_id": sample_cols,
            **{f"gene_{i}": arr[:, i].tolist() for i in range(arr.shape[1])},
        }
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """PCA coordinates per sample, joined to the sample sheet when available."""
    matrix = _samples_by_genes(sources["vst"])
    n_components = 3 if matrix.height >= 4 else 2
    coords = run_pca(matrix, n_components=n_components, scale=False)

    sheet = sources.get("samplesheet")
    if sheet is None:
        return coords.with_columns(pl.lit("all").alias("group"))

    sheet = fix_delimiter(sheet)
    id_col = sample_id_column(sheet, coords["sample_id"].to_list())
    factors = factor_columns(sheet, id_col)
    group_col = factors[0] if factors else None

    renamed: dict[str, str] = {id_col: "sample_id"}
    for col in sheet.columns:
        if col == id_col:
            continue
        new = sanitise_column(col)
        if new in ("sample_id", "dim_1", "dim_2", "dim_3", "group") or new in renamed.values():
            new = f"{new}_sheet"
        renamed[col] = new
    meta = (
        sheet.with_columns(pl.col(id_col).cast(pl.Utf8))
        .unique(subset=[id_col], keep="first")
        .rename(renamed)
    )
    meta = meta.with_columns([pl.col(c).cast(pl.Utf8) for c in meta.columns if c != "sample_id"])
    if group_col is not None:
        meta = meta.with_columns(pl.col(renamed[group_col]).alias("group"))
    else:
        meta = meta.with_columns(pl.lit("all").alias("group"))

    result = coords.join(meta, on="sample_id", how="left").with_columns(
        pl.col("group").fill_null("unknown")
    )
    ordered = ["sample_id", "dim_1", "dim_2"] + (["dim_3"] if "dim_3" in result.columns else [])
    ordered += ["group"] + [c for c in result.columns if c not in ordered and c != "group"]
    return result.select(ordered)
