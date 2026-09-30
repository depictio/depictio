"""One row per InterProScan signature match, from the headerless TSV output.

Consumes the raw ``interproscan_tsv_raw`` scan (one full TSV line per row in
``raw_line``, plus ``source_path``). The TSV has 11 fixed columns and up to 4
optional ones (InterPro entry, its description, GO terms, pathways); a column
InterProScan leaves empty is written as ``-``, read here as null. A sequence
with no match writes no line, and a sample with no match at all writes an empty
file, which the scan reads as no rows.

The sample is the file name without ``.tsv`` (nf-core writes
``interproscan/<sample>/<sample>.tsv``). Output spans follow the domain table
convention: ``entity``, ``start``, ``end``, ``label`` (the signature accession)
and ``source`` (the member database).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "interproscan_tsv_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "source": pl.Utf8,
    "label": pl.Utf8,
    "description": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "evalue": pl.Float64,
    "protein_length": pl.Int64,
    "interpro_accession": pl.Utf8,
    "interpro_description": pl.Utf8,
    "go_terms": pl.Utf8,
    "pathways": pl.Utf8,
}

_N_FIELDS = 15


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=EXPECTED_SCHEMA)


def _field(index: int) -> pl.Expr:
    value = pl.col("_parts").struct.field(f"field_{index}").str.strip_chars()
    return pl.when(value.is_in(["-", ""])).then(None).otherwise(value)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split every match line into the domain-table columns."""
    raw = sources["raw"]
    if raw is None or "raw_line" not in raw.columns:
        return _empty()
    path = (
        pl.col("source_path").cast(pl.Utf8)
        if "source_path" in raw.columns
        else pl.lit(None, dtype=pl.Utf8)
    )
    lines = raw.select(pl.col("raw_line").cast(pl.Utf8), path.alias("_path")).filter(
        pl.col("raw_line").is_not_null() & (pl.col("raw_line").str.strip_chars() != "")
    )
    if lines.is_empty():
        return _empty()
    parts = lines.with_columns(pl.col("raw_line").str.splitn("\t", _N_FIELDS).alias("_parts"))
    out = parts.select(
        _field(0).alias("entity"),
        pl.col("_path")
        .str.extract(r"([^/\\]+)$", 1)
        .str.replace(r"\.tsv$", "")
        .fill_null("run")
        .alias("sample"),
        _field(3).alias("source"),
        _field(4).alias("label"),
        _field(5).alias("description"),
        _field(6).cast(pl.Int64, strict=False).alias("start"),
        _field(7).cast(pl.Int64, strict=False).alias("end"),
        _field(8).cast(pl.Float64, strict=False).alias("evalue"),
        _field(2).cast(pl.Int64, strict=False).alias("protein_length"),
        _field(11).alias("interpro_accession"),
        _field(12).alias("interpro_description"),
        _field(13).alias("go_terms"),
        _field(14).alias("pathways"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "entity", "start"])
