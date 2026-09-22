"""The DESeq2 QC PCA the pipeline already computed, read rather than recomputed.

Three nf-core pipelines run the same ``deseq2_qc.r`` over their count matrix and
publish its principal components as a small text file next to the plots:

* rnaseq    ``star_salmon/deseq2_qc/deseq2.pca.vals.txt`` (quoted TSV)
* chipseq   ``.../consensus/<antibody>/deseq2/<prefix>.pca.vals.txt``
* atacseq   ``.../consensus/deseq2/<prefix>.pca.vals.txt``

so the glob keys on the suffix, never on a pipeline directory. The ``_mqc``
variant beside it is the same table wrapped as MultiQC custom content, under a
``#`` comment header the reader has to skip. Both spellings parse here, and the
`_mqc` one is declared as `path_glob_alt`, but the recipe's own glob deliberately
matches only the plain ``.txt``: a run that writes both would otherwise read the
same samples twice. chipseq 1.2.0 and atacseq 1.2.2 publish ONLY the ``_mqc``
flavour, so those templates repoint the source::

    source_overrides: {pca: {glob_pattern: "**/*pca.vals_mqc.tsv"}}

A pipeline that runs DESeq2 once per contrast (chipseq, one consensus dir per
antibody) matches several files, and the resolver concatenates them, so such a
template must narrow the glob to one contrast rather than bind this output as is.

The file's own header carries the variance each component explains, as
``"PC1: 43% variance"``. That number is the whole point of a DESeq2 PCA (two
samples far apart on a component explaining 3 percent are not far apart), so it
is parsed out of the header and published as a column rather than dropped.

Output (canonical ``embedding`` schema):
    sample_id : Utf8, dim_1 : Float64, dim_2 : Float64
    dim_1_percent, dim_2_percent : Float64   variance explained, per component
    dim_3, dim_3_percent : Float64           when the file has a third component

This is deliberately NOT ``vst_pca``: that recipe recomputes a PCA from
``all.vst.tsv`` with depictio's own top-N and centring choices. This one is the
pipeline's own figure, so a reader comparing the dashboard against the MultiQC
report sees the same points.
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="pca",
        glob_pattern="**/*pca.vals.txt",
        format="tsv",
        # The `_mqc` variant opens with `#id`/`#section_name` custom-content
        # lines; the plain one is quoted. Reading everything as text and casting
        # below keeps one code path for both.
        read_kwargs={"infer_schema_length": 0, "comment_prefix": "#", "quote_char": '"'},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "dim_1_percent": pl.Float64,
    "dim_2_percent": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "dim_3": pl.Float64,
    "dim_3_percent": pl.Float64,
}

# `PC1: 43% variance`, `PC1 (43%)`, `PC1`
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_MAX_DIMS = 3


def _percent(header: str) -> float | None:
    match = _PERCENT.search(header)
    return float(match.group(1)) if match else None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename the component columns to the embedding roles, keeping the variance."""
    df = sources["pca"]
    columns = [c.strip().strip('"') for c in df.columns]
    df = df.rename(dict(zip(df.columns, columns, strict=True)))
    sample_col = columns[0]
    component_cols = columns[1 : 1 + _MAX_DIMS]

    out = df.select(
        pl.col(sample_col).cast(pl.Utf8).str.strip_chars('"').alias("sample_id"),
        *[
            pl.col(col).cast(pl.Float64, strict=False).alias(f"dim_{i}")
            for i, col in enumerate(component_cols, start=1)
        ],
    )
    percents = {f"dim_{i}_percent": _percent(col) for i, col in enumerate(component_cols, start=1)}
    return out.with_columns(
        [pl.lit(value, dtype=pl.Float64).alias(name) for name, value in percents.items()]
    )
