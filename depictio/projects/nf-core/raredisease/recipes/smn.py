"""nf-core/raredisease SMN copy numbers: one row per sample, from SMNCopyNumberCaller.

SMNCopyNumberCaller calls the copy number of SMN1 and SMN2 (the paralogous genes at
5q13 that decide spinal muscular atrophy) from the alignment of each sample and
writes a family table, ``smncopynumbercaller/out/<family>_smncopynumbercaller.tsv``.
A sample the caller could not reach (no coverage at the locus, or an alignment on
another reference) has ``None`` or ``nan`` in every column; those become nulls and the
sample's ``smn_status`` is ``No call``. A called sample is ``SMA`` when the caller says so,
``Carrier`` when it flags a carrier and ``Not a carrier`` otherwise.

Sources:
    table  ``smncopynumbercaller/out/*_smncopynumbercaller.tsv``

Output schema (a value the caller did not write is null):
    sample : Utf8
    smn_status : Utf8         SMA / Carrier / Not a carrier / No call
    smn1_cn : Int64           SMN1 copy number
    smn2_cn : Int64           SMN2 copy number
    smn2_delta78_cn : Int64   SMN2 copies lacking exons 7 and 8
    total_cn_raw : Float64    raw SMN1 + SMN2 copy number estimate
    full_length_cn_raw : Float64   raw full-length SMN copy number estimate
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="table",
        glob_pattern="smncopynumbercaller/out/*_smncopynumbercaller.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        input_schema={
            "Sample": pl.Utf8,
            "isSMA": pl.Utf8,
            "isCarrier": pl.Utf8,
            "SMN1_CN": pl.Utf8,
            "SMN2_CN": pl.Utf8,
            "SMN2delta7-8_CN": pl.Utf8,
            "Total_CN_raw": pl.Utf8,
            "Full_length_CN_raw": pl.Utf8,
        },
        # A run that skipped SMN calling publishes none of it.
        optional=True,
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "smn_status": pl.Utf8,
    "smn1_cn": pl.Int64,
    "smn2_cn": pl.Int64,
    "smn2_delta78_cn": pl.Int64,
    "total_cn_raw": pl.Float64,
    "full_length_cn_raw": pl.Float64,
}

_NULLS = ["None", "none", "nan", "NaN", "NA", ""]


def _flag(column: str) -> pl.Expr:
    """``True`` / ``False`` text -> Boolean; ``None``, ``nan`` and empty -> null."""
    text = pl.col(column).str.to_lowercase()
    return pl.when(text == "true").then(True).when(text == "false").then(False).otherwise(None)


def _count(column: str) -> pl.Expr:
    value = pl.col(column).replace(_NULLS, None).cast(pl.Float64, strict=False)
    return value.round(0).cast(pl.Int64)


def _real(column: str) -> pl.Expr:
    return pl.col(column).replace(_NULLS, None).cast(pl.Float64, strict=False)


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per sample of the caller's table."""
    table = sources.get("table")
    if table is None:
        raise ValueError("raredisease smn: no smncopynumbercaller/out/*_smncopynumbercaller.tsv")
    sma, carrier = _flag("isSMA"), _flag("isCarrier")
    return (
        table.filter(pl.col("Sample").is_not_null())
        .select(
            pl.col("Sample").alias("sample"),
            pl.when(sma)
            .then(pl.lit("SMA"))
            .when(carrier)
            .then(pl.lit("Carrier"))
            .when(sma.is_not_null() | carrier.is_not_null())
            .then(pl.lit("Not a carrier"))
            .otherwise(pl.lit("No call"))
            .alias("smn_status"),
            _count("SMN1_CN").alias("smn1_cn"),
            _count("SMN2_CN").alias("smn2_cn"),
            _count("SMN2delta7-8_CN").alias("smn2_delta78_cn"),
            _real("Total_CN_raw").alias("total_cn_raw"),
            _real("Full_length_CN_raw").alias("full_length_cn_raw"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort("sample")
    )
