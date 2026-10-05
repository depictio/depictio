"""DESeq2 QC principal components, one PCA matrix per antibody.

`depictio/catalog/deseq2/qc_pca.py` reads the single `*.pca.vals*` table a
pipeline with one count matrix publishes, and maps the component columns to the
embedding roles BY POSITION on the concatenated frame. chipseq publishes one
consensus peak set, one count matrix and therefore one PCA per antibody
(`EZH2.consensus_peaks.pca.vals_mqc.tsv`,
`FOXA1.consensus_peaks.pca.vals_mqc.tsv`), and each file spells the variance it
explains into its own header (`"PC1: 63% variance"` against
`"PC1: 91% variance"`). Those headers differ, so the diagonal concatenation the
glob loader performs spreads the two matrices over FOUR component columns rather
than two: the catalog recipe then reads the first antibody's PC1 and PC2 as
`dim_1` and `dim_2` and the second antibody's PC1 as `dim_3`, leaving half the
cohort null on the two axes the embedding actually plots.

This recipe keeps the catalog output's column names, so a tile binds
`use: deseq2/qc_pca_embedding` unchanged, and resolves the components per MATRIX
instead of per frame. A matrix is recognised by which component columns its rows
populate, which is exactly what the diagonal concat encodes; the source file
name is not available, because the glob loader reads with `pl.read_csv` and that
has no `include_file_paths`. The set is therefore named the way
`macs2/consensus_boolean.py` names a consensus set: the longest common prefix of
the samples in it.

A PCA is only comparable inside one matrix, so the two sets never share a pair
of axes by accident: `consensus_set` is what a tile colours by, and the antibody
filter narrows to one of them.

Output schema:
    sample_id : Utf8           library the PCA placed
    consensus_set : Utf8       which count matrix the components come from
    dim_1 : Float64            first principal component, in that matrix
    dim_2 : Float64            second principal component, in that matrix
    dim_1_percent : Float64    variance PC1 explains in that matrix
    dim_2_percent : Float64    variance PC2 explains in that matrix
"""

from __future__ import annotations

import os
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="pca",
        glob_pattern="**/*pca.vals_mqc.tsv",
        format="TSV",
        read_kwargs={
            "infer_schema_length": 0,
            "comment_prefix": "#",
            "quote_char": '"',
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "consensus_set": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "dim_1_percent": pl.Float64,
    "dim_2_percent": pl.Float64,
}

# `"PC1: 63% variance"` -> 63.0. The header is the only place the run records it.
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")

_FALLBACK_LABEL = "consensus"


def _percent(column: str) -> float | None:
    match = _PERCENT.search(column)
    return float(match.group(1)) if match else None


def _set_label(samples: list[str]) -> str:
    """Longest common prefix of the sample names, trimmed of separators."""
    return re.sub(r"[._-]+$", "", os.path.commonprefix(samples)) or _FALLBACK_LABEL


def _one_matrix(block: pl.DataFrame, sample_col: str) -> pl.DataFrame:
    """Map one matrix's own component columns onto the embedding roles."""
    components = [
        c
        for c in block.columns
        if c != sample_col and block.get_column(c).null_count() < block.height
    ]
    if len(components) < 2:
        raise ValueError(
            "chipseq deseq2_qc_pca: a PCA table needs at least two component "
            f"columns, found {components} beside {sample_col!r}"
        )
    first, second = components[0], components[1]
    samples = (
        block.get_column(sample_col).cast(pl.Utf8).str.strip_chars('"').fill_null("").to_list()
    )
    return block.select(
        pl.col(sample_col).cast(pl.Utf8).str.strip_chars('"').alias("sample_id"),
        pl.lit(_set_label(samples)).alias("consensus_set"),
        pl.col(first).cast(pl.Float64, strict=False).alias("dim_1"),
        pl.col(second).cast(pl.Float64, strict=False).alias("dim_2"),
        pl.lit(_percent(first), dtype=pl.Float64).alias("dim_1_percent"),
        pl.lit(_percent(second), dtype=pl.Float64).alias("dim_2_percent"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Resolve the components per matrix, not per concatenated frame."""
    df = sources["pca"]
    # Two spellings of one header (quoted in one file, bare in another) must
    # land in one column: a plain rename would raise on the duplicate.
    by_name: dict[str, list[str]] = {}
    for column in df.columns:
        by_name.setdefault(column.strip().strip('"'), []).append(column)
    df = df.select(
        pl.coalesce([pl.col(c) for c in columns]).alias(name) for name, columns in by_name.items()
    )
    sample_col, *components = df.columns
    if not components:
        raise ValueError("chipseq deseq2_qc_pca: the PCA table has no component columns")

    # Which component columns a row populates is which matrix it came from: the
    # diagonal concat leaves every other matrix's columns null on that row.
    signature = pl.concat_str(
        [pl.col(c).is_null().cast(pl.Int8).cast(pl.Utf8) for c in components]
    ).alias("_matrix")
    df = df.with_columns(signature)

    blocks = [
        _one_matrix(block.drop("_matrix"), sample_col)
        for block in df.partition_by("_matrix", maintain_order=True)
    ]
    out = pl.concat(blocks, how="vertical")
    return out.select(list(EXPECTED_SCHEMA)).sort(["consensus_set", "sample_id"])
