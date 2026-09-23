"""V by J gene pairing matrix per subject, from the AIRR rearrangement table.

Reads the repertoire table enchantR's repertoire analysis starts from
(``*__repertoire-pass.tsv``) and counts productive sequences per V gene and J
gene pair. Calls are reduced to the first gene of the call at gene resolution
(``IGHV3-23*01,IGHV3-23D*01`` becomes ``IGHV3-23``), the same resolution the
V gene usage matrix uses.

Rows are ``<subject> <V gene>`` and columns J genes, each cell the share of the
subject's sequences using that pair, so the heatmap reads as the classic V by J
usage grid with ``subject_id`` riding along as a row annotation. Pairing is
reported per subject rather than per sample because clones are defined per
subject: two sections of one donor share their clones, and splitting them
would count one expanded clone twice.

Only the seven columns this needs are read (``read_kwargs.columns``).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_COLUMNS = ["sequence_id", "sample_id", "subject_id", "locus", "productive", "v_call", "j_call"]

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="rearrangements",
        glob_pattern="**/*__repertoire-pass.tsv",
        format="TSV",
        read_kwargs={"columns": _COLUMNS, "infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "row_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "locus": pl.Utf8,
    "v_gene": pl.Utf8,
}
# Plus one Float64 column per J gene; the gene set is discovered from the data.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_TRUE = ("T", "TRUE", "True", "true", "1")


def _gene(col: str) -> pl.Expr:
    """First call of an AIRR gene call, without its allele."""
    return pl.col(col).cast(pl.Utf8).str.split(",").list.first().str.split("*").list.first()


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot productive V-J pair counts to a wide subject and V gene by J gene matrix."""
    df = sources["rearrangements"].unique(subset=["sample_id", "sequence_id"])
    df = df.filter(pl.col("productive").is_in(_TRUE)).select(
        pl.col("subject_id").cast(pl.Utf8),
        pl.col("locus").cast(pl.Utf8),
        _gene("v_call").alias("v_gene"),
        _gene("j_call").alias("j_gene"),
    )
    df = df.drop_nulls(["v_gene", "j_gene"]).filter(
        (pl.col("v_gene") != "") & (pl.col("j_gene") != "")
    )

    keys = ["subject_id", "locus"]
    pairs = df.group_by([*keys, "v_gene", "j_gene"]).agg(pl.len().alias("n"))
    pairs = pairs.with_columns(
        (pl.col("n") / pl.col("n").sum().over(keys)).cast(pl.Float64).alias("fraction")
    )
    pairs = pairs.with_columns(
        pl.concat_str([pl.col("subject_id"), pl.lit(" "), pl.col("v_gene")]).alias("row_id")
    )

    index = ["row_id", "subject_id", "locus", "v_gene"]
    j_genes = sorted(pairs.get_column("j_gene").unique().to_list())
    wide = pairs.pivot(values="fraction", index=index, on="j_gene", aggregate_function="sum")
    wide = wide.with_columns([pl.col(j).cast(pl.Float64).fill_null(0.0) for j in j_genes])
    return wide.select([*index, *j_genes]).sort("row_id")
