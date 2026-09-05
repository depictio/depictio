"""Gene by tool membership matrix for an UpSet plot of dbCAN tool agreement.

One row per CAZyme gene from the run_dbCAN overview files; ``hmmer``,
``dbcan_sub`` and ``diamond`` are 1 when that annotation tool reported a
family for the gene. The sample is read from the gene id prefix, as in
``dbcan/overview.py``.

Output columns:
    gene_id, sample, hmmer, dbcan_sub, diamond
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="overview",
        glob_pattern="cazyme/dbcan/cazyme_annotation/*/*_overview.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "sample": pl.Utf8,
    "hmmer": pl.Int64,
    "dbcan_sub": pl.Int64,
    "diamond": pl.Int64,
}


def _present(name: str) -> pl.Expr:
    col = pl.col(name).cast(pl.Utf8)
    return (col.is_not_null() & (col != "-")).cast(pl.Int64)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Binary presence per annotation tool."""
    df = sources["overview"]
    gene_id = pl.col("Gene ID").cast(pl.Utf8)
    contig = gene_id.str.replace(r"_\d+$", "")
    return df.select(
        gene_id.alias("gene_id"),
        pl.when(contig.str.contains(r"^[^.]+\..+"))
        .then(contig.str.extract(r"^([^.]+)\.", 1))
        .otherwise(pl.lit("run"))
        .alias("sample"),
        _present("dbCAN_hmm").alias("hmmer"),
        _present("dbCAN_sub").alias("dbcan_sub"),
        _present("DIAMOND").alias("diamond"),
    ).sort("sample", "gene_id")
