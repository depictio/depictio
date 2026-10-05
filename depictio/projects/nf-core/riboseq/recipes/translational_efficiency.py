"""Baseline translational efficiency per gene, pooled over the run's libraries.

nf-core/riboseq writes ``quantification/inframe_psite/gene_counts.tsv``, the
count matrix anota2seq is handed: one column per library, Salmon counts for the
RNA-seq libraries and in-frame P-site counts for the Ribo-seq ones. This recipe
normalises every library to counts per million, averages the RNA-seq and the
Ribo-seq libraries separately and takes their ratio, the translational
efficiency (TE) of the gene across the whole run. It answers "which genes are
translated more or less than their mRNA level predicts", independent of any
contrast; anota2seq answers how that changes between conditions.

Sources:
    counts       the in-frame P-site count matrix (gene_id, gene_name, one
                 column per library).
    samplesheet  the run's ``--input`` sheet, for the ``type`` of each library
                 (``rnaseq`` or ``riboseq``). The template repoints it at
                 ``{SAMPLESHEET_FILE}``.

Output: one row per gene with at least ``MIN_CPM`` mean CPM in either assay.
    gene_id, gene_name : Utf8
    rna_cpm, ribo_cpm : Float64         mean CPM over the RNA-seq / Ribo-seq libraries
    log2_rna_cpm, log2_ribo_cpm : Float64   log2(CPM + 1)
    log2_te : Float64                   log2((ribo_cpm + 1) / (rna_cpm + 1))
    rna_libraries, ribo_libraries : Int64   libraries with a non-zero count
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="counts",
        path="quantification/inframe_psite/gene_counts.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA"]},
    ),
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "rna_cpm": pl.Float64,
    "ribo_cpm": pl.Float64,
    "log2_rna_cpm": pl.Float64,
    "log2_ribo_cpm": pl.Float64,
    "log2_te": pl.Float64,
    "rna_libraries": pl.Int64,
    "ribo_libraries": pl.Int64,
}

MIN_CPM = 1.0
RNA_TYPES = ("rnaseq",)
RIBO_TYPES = ("riboseq",)


def _libraries(sheet: pl.DataFrame, columns: list[str], types: tuple[str, ...]) -> list[str]:
    sample_col = next(
        (c for c in sheet.columns if c.lower() in ("sample", "sample_id", "sampleid")),
        sheet.columns[0],
    )
    type_col = next((c for c in sheet.columns if c.lower() == "type"), None)
    if type_col is None:
        return []
    ids = (
        sheet.filter(pl.col(type_col).str.to_lowercase().is_in(list(types)))[sample_col]
        .cast(pl.Utf8)
        .to_list()
    )
    return [c for c in columns if c in ids]


def _mean_cpm(counts: pl.DataFrame, libs: list[str], name: str) -> list[pl.Expr]:
    if not libs:
        return [
            pl.lit(0.0).alias(f"{name}_cpm"),
            pl.lit(0, dtype=pl.Int64).alias(f"{name}_libraries"),
        ]
    totals = {c: float(counts[c].sum() or 0.0) for c in libs}
    cpm = [
        (pl.col(c).cast(pl.Float64).fill_null(0) * 1e6 / totals[c])
        if totals[c] > 0
        else pl.lit(0.0)
        for c in libs
    ]
    return [
        pl.mean_horizontal(cpm).alias(f"{name}_cpm"),
        pl.sum_horizontal([(pl.col(c).fill_null(0) > 0).cast(pl.Int64) for c in libs]).alias(
            f"{name}_libraries"
        ),
    ]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Mean CPM per assay and their log2 ratio, per gene."""
    counts = sources["counts"]
    sheet = sources["samplesheet"]
    id_col = "gene_id" if "gene_id" in counts.columns else counts.columns[0]
    name_col = "gene_name" if "gene_name" in counts.columns else id_col
    lib_cols = [c for c in counts.columns if c not in (id_col, name_col)]
    rna = _libraries(sheet, lib_cols, RNA_TYPES)
    ribo = _libraries(sheet, lib_cols, RIBO_TYPES)
    out = counts.select(
        pl.col(id_col).cast(pl.Utf8).alias("gene_id"),
        pl.col(name_col).cast(pl.Utf8).alias("gene_name"),
        *_mean_cpm(counts, rna, "rna"),
        *_mean_cpm(counts, ribo, "ribo"),
    )
    out = out.filter((pl.col("rna_cpm") >= MIN_CPM) | (pl.col("ribo_cpm") >= MIN_CPM))
    return (
        out.with_columns(
            pl.col("gene_name").fill_null(pl.col("gene_id")),
            (pl.col("rna_cpm") + 1).log(2).alias("log2_rna_cpm"),
            (pl.col("ribo_cpm") + 1).log(2).alias("log2_ribo_cpm"),
            ((pl.col("ribo_cpm") + 1) / (pl.col("rna_cpm") + 1)).log(2).alias("log2_te"),
        )
        .with_columns([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()])
        .sort("gene_id")
        .select(list(EXPECTED_SCHEMA))
    )
