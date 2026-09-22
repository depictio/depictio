"""The DESeq2 QC sample-distance matrix the pipeline already computed.

Companion of ``qc_pca.py``: the same ``deseq2_qc.r`` writes the square
sample-by-sample Euclidean distance matrix it clusters the QC dendrogram on.

* rnaseq    ``star_salmon/deseq2_qc/deseq2.sample.dists.txt``
* chipseq   ``.../consensus/<antibody>/deseq2/<prefix>.sample.dists.txt``
* atacseq   ``.../consensus/deseq2/<prefix>.sample.dists.txt``

Same rules as ``qc_pca.py``: the glob keys on the suffix, both spellings parse,
the recipe matches the plain ``.txt`` so a run publishing both is not read twice,
and a template whose run has only the ``_mqc`` flavour repoints the source::

    source_overrides: {dists: {glob_pattern: "**/*sample.dists_mqc.tsv"}}

Output: ``sample`` (Utf8, the heatmap index) plus one Float64 column per sample.
The matrix is symmetric with a zero diagonal, which is what the distance
clustering expects, so it is published as written rather than normalised.

This is NOT ``sample_distance`` (``vst_sample_distance.py``): that one computes
distances from ``all.vst.tsv`` with depictio's own top-N choice. This one is the
pipeline's own matrix.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="dists",
        glob_pattern="**/*sample.dists.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "comment_prefix": "#", "quote_char": '"'},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Name the index column `sample` and cast every distance column to float."""
    df = sources["dists"]
    columns = [c.strip().strip('"') for c in df.columns]
    df = df.rename(dict(zip(df.columns, columns, strict=True)))
    index_col, *value_cols = columns
    return df.select(
        pl.col(index_col).cast(pl.Utf8).str.strip_chars('"').alias("sample"),
        *[pl.col(col).cast(pl.Float64, strict=False) for col in value_cols],
    )
