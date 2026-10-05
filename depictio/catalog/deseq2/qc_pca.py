"""The DESeq2 QC PCA the pipeline already computed, read rather than recomputed.

Three nf-core pipelines run the same ``deseq2_qc.r`` over their count matrix and
publish its principal components as a small text file next to the plots:

* rnaseq    ``star_salmon/deseq2_qc/deseq2.pca.vals.txt`` (quoted TSV)
* chipseq   ``.../consensus/<antibody>/deseq2/<prefix>.pca.vals.txt``
* atacseq   ``.../consensus/deseq2/<prefix>.pca.vals.txt``

so the glob keys on the suffix, never on a pipeline directory. The ``_mqc``
variant beside it is the same table wrapped as MultiQC custom content, under a
``#`` comment header the reader has to skip. Both spellings parse here, and the
`_mqc` one is declared as `path_glob_alt`. chipseq 1.2.0 and atacseq 1.2.2
publish ONLY the ``_mqc`` flavour, so those templates repoint the source::

    source_overrides: {pca: {glob_pattern: "**/*pca.vals_mqc.tsv"}}

When a repointed glob matches both flavours of one table (same directory, same
prefix), only one is kept, so a run never places the same samples twice.

One PCA per matrix. A pipeline that runs DESeq2 once per count matrix (chipseq
writes one per antibody, atacseq one per merged library and one per merged
replicate, an rnaseq run keeps one per aligner route) matches several files. Each
file spells the variance it explains into its own header (``"PC1: 63% variance"``
against ``"PC1: 91% variance"``), so the loader's diagonal concatenation spreads
the matrices over different columns. The components are therefore resolved per
FILE, through the source's ``source_path`` column, never by position on the
concatenated frame. Inside one file (or a frame stacked without a path column)
they are resolved per MATRIX: rows are partitioned by which component columns
they fill, and each part takes its own first two components and their own
header percentages. Each row carries ``pca_set``, the part of its file path
that tells the matrices apart (the antibody, the aligner route, the merge
level). Two sets never share a pair of axes: a tile colours or filters by it.

The file's own header carries the variance each component explains. That number
is the whole point of a DESeq2 PCA (two samples far apart on a component
explaining 3 percent are not far apart), so it is parsed out of the header and
published as a column, per set, rather than dropped.

Output (canonical ``embedding`` schema):
    sample_id : Utf8, dim_1 : Float64, dim_2 : Float64
    dim_1_percent, dim_2_percent : Float64   variance explained, per component
    pca_set : Utf8                           which matrix the components come from
    dim_3, dim_3_percent : Float64           when every file has a third component

This is deliberately NOT ``vst_pca``: that recipe recomputes a PCA from
``all.vst.tsv`` with depictio's own top-N and centring choices. This one is the
pipeline's own figure, so a reader comparing the dashboard against the MultiQC
report sees the same points.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

_PATH_COL = "_pca_source_path"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="pca",
        glob_pattern="**/*pca.vals.txt",
        format="tsv",
        # The `_mqc` variant opens with `#id`/`#section_name` custom-content
        # lines; the plain one is quoted. Reading everything as text and casting
        # below keeps one code path for both.
        read_kwargs={"infer_schema_length": 0, "comment_prefix": "#", "quote_char": '"'},
        source_path=_PATH_COL,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "dim_1_percent": pl.Float64,
    "dim_2_percent": pl.Float64,
    "pca_set": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "dim_3": pl.Float64,
    "dim_3_percent": pl.Float64,
}

# `PC1: 43% variance`, `PC1 (43%)`, `PC1`
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# `<prefix>.pca.vals.txt`, `<prefix>.pca.vals_mqc.tsv`
_SUFFIX = re.compile(r"\.?pca\.vals(?:_mqc)?\.(?:txt|tsv)$")
_MAX_DIMS = 3
_FALLBACK_SET = "deseq2"


def _percent(header: str) -> float | None:
    match = _PERCENT.search(header)
    return float(match.group(1)) if match else None


def _table_key(path: str) -> str:
    """The file path without its flavour suffix: both flavours of one table share it."""
    return _SUFFIX.sub("", path)


def _set_labels(keys: list[str]) -> dict[str, str]:
    """Name each matrix by the first path segment that differs between them.

    One matrix: its file prefix (``deseq2``, ``consensus_peaks.mLb.clN``).
    Several: the first segment the paths do not share, which is the antibody
    for chipseq, the merge level for atacseq, the aligner route for rnaseq.
    """
    parts = {key: PurePosixPath(key).parts for key in keys}
    if len(keys) == 1:
        (key,) = keys
        return {key: (parts[key][-1] if parts[key] else "") or _FALLBACK_SET}
    depth = min(len(p) for p in parts.values())
    for i in range(depth):
        segments = {p[i] for p in parts.values()}
        if len(segments) == len(keys):
            return {key: parts[key][i] for key in keys}
    return {key: key or _FALLBACK_SET for key in keys}


def _is_numeric(column: pl.Series) -> bool:
    """True when every non-null cell casts to a float (``NA`` already reads as null)."""
    values = column.drop_nulls().cast(pl.Utf8).str.strip_chars('"')
    values = values.filter(values != "NA")
    return values.cast(pl.Float64, strict=False).null_count() == 0


def _matrices(block: pl.DataFrame) -> list[tuple[str, list[str], pl.DataFrame]]:
    """Split one file's rows into its matrices: ``(sample column, components, rows)``.

    A file (or a frame the loader stacked without a path column) can hold several
    matrices, each with its own ``"PCn: x% variance"`` headers, so each matrix
    fills its own columns and leaves the others null. Two component columns
    belong to the same matrix when some row fills both; union-find over that
    relation groups them, and a row goes to the matrix of its first filled
    component. An ``NA`` cell only empties that cell: its row still shares its
    other components with the rest of its matrix.
    """
    filled = [c for c in block.columns if block.get_column(c).null_count() < block.height]
    if not filled:
        return []
    sample_cols = [filled[0]] + [c for c in filled[1:] if not _is_numeric(block.get_column(c))]
    component_cols = [c for c in filled if c not in sample_cols]

    parent = {c: c for c in component_cols}

    def root(col: str) -> str:
        while parent[col] != col:
            parent[col] = parent[parent[col]]
            col = parent[col]
        return col

    mask = block.select(pl.col(c).is_not_null() for c in component_cols)
    for row in mask.iter_rows():
        present = [c for c, ok in zip(component_cols, row, strict=True) if ok]
        for col in present[1:]:
            parent[root(col)] = root(present[0])

    groups: dict[str, list[str]] = {}
    for col in component_cols:
        groups.setdefault(root(col), []).append(col)
    order = list(groups)
    row_group = [
        next((order.index(root(c)) for c, ok in zip(component_cols, row, strict=True) if ok), 0)
        for row in mask.iter_rows()
    ]
    indexed = block.with_columns(pl.Series("_pca_group", row_group, dtype=pl.Int64))

    out = []
    for i, key in enumerate(order):
        rows = indexed.filter(pl.col("_pca_group") == i).drop("_pca_group")
        sample_col = next(
            (c for c in sample_cols if rows.get_column(c).null_count() < rows.height),
            sample_cols[0],
        )
        out.append((sample_col, groups[key], rows))
    return out


def _one_matrix(
    rows: pl.DataFrame, sample_col: str, component_cols: list[str], pca_set: str
) -> pl.DataFrame:
    """Map one matrix's own columns onto the embedding roles."""
    if len(component_cols) < 2:
        raise ValueError(
            f"deseq2 qc_pca: the PCA table of set {pca_set!r} needs a sample column "
            f"and two components, found {[sample_col, *component_cols]}"
        )
    component_cols = component_cols[:_MAX_DIMS]
    return rows.select(
        pl.col(sample_col).cast(pl.Utf8).str.strip_chars('"').alias("sample_id"),
        *[
            pl.col(col).cast(pl.Float64, strict=False).alias(f"dim_{i}")
            for i, col in enumerate(component_cols, start=1)
        ],
        *[
            pl.lit(_percent(col), dtype=pl.Float64).alias(f"dim_{i}_percent")
            for i, col in enumerate(component_cols, start=1)
        ],
        pl.lit(pca_set, dtype=pl.Utf8).alias("pca_set"),
    )


def _file_blocks(block: pl.DataFrame, label: str) -> list[pl.DataFrame]:
    """Every matrix of one file; several matrices get ``<label>_1``, ``<label>_2``, ..."""
    matrices = _matrices(block)
    if not matrices:
        raise ValueError(f"deseq2 qc_pca: the PCA table of set {label!r} is empty")
    return [
        _one_matrix(rows, sample_col, components, label if len(matrices) == 1 else f"{label}_{i}")
        for i, (sample_col, components, rows) in enumerate(matrices, start=1)
    ]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Resolve the components per source file, keeping each set's variance."""
    df = sources["pca"]
    if _PATH_COL not in df.columns:
        # Called without the loader (fixtures, direct calls): one file.
        df = df.with_columns(pl.lit("deseq2.pca.vals.txt").alias(_PATH_COL))
    df = df.rename({c: c.strip().strip('"') for c in df.columns if c != _PATH_COL})

    paths = df.get_column(_PATH_COL).unique(maintain_order=True).to_list()
    # One file per table: the plain `.txt` wins over its `_mqc` twin.
    chosen: dict[str, str] = {}
    for path in sorted(paths, key=lambda p: (_table_key(p), not p.endswith(".txt"))):
        chosen.setdefault(_table_key(path), path)
    labels = _set_labels(list(chosen))

    blocks = [
        part
        for key, path in chosen.items()
        for part in _file_blocks(df.filter(pl.col(_PATH_COL) == path).drop(_PATH_COL), labels[key])
    ]
    out = pl.concat(blocks, how="diagonal_relaxed")
    # A third component is published only when every set has one.
    optional = [
        c for c in OPTIONAL_SCHEMA if c in out.columns and out.get_column(c).null_count() == 0
    ]
    dropped = [c for c in OPTIONAL_SCHEMA if c in out.columns and c not in optional]
    return out.drop(dropped).select([*EXPECTED_SCHEMA, *optional])
