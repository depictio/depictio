"""One row per FASTA record: id, description, length and sequence.

Consumes the raw ``seqkit_fasta_raw`` scan: one FASTA line per row in
``raw_line``, ``line_no`` (the scan's per-file row index, which keeps the
lines of a record together whatever order the rows come back in) and
``source_path``. A record is a ``>`` header and the sequence lines after it.

``entity`` is the first word of the header, the id every downstream tool
(hmmsearch, InterProScan, S4PRED) reports; the rest of the header is the
``description``. The sample is the file name without its FASTA extension.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "seqkit_fasta_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "description": pl.Utf8,
    "length": pl.Int64,
    "sequence": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Group every header with its sequence lines."""
    raw = sources["raw"]
    if raw is None or "raw_line" not in raw.columns or raw.is_empty():
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    path = (
        pl.col("source_path").cast(pl.Utf8)
        if "source_path" in raw.columns
        else pl.lit("run", dtype=pl.Utf8)
    )
    order = (
        pl.col("line_no").cast(pl.Int64)
        if "line_no" in raw.columns
        else pl.int_range(pl.len(), dtype=pl.Int64)
    )
    lines = (
        raw.select(
            pl.col("raw_line").cast(pl.Utf8).str.strip_chars(),
            path.alias("_path"),
            order.alias("_n"),
        )
        .sort(["_path", "_n"])
        .filter(pl.col("raw_line").is_not_null() & (pl.col("raw_line") != ""))
    )
    is_header = pl.col("raw_line").str.starts_with(">")
    lines = lines.with_columns(is_header.cast(pl.Int64).cum_sum().over("_path").alias("_record"))
    lines = lines.filter(pl.col("_record") > 0)
    records = lines.group_by(["_path", "_record"], maintain_order=True).agg(
        pl.col("raw_line").filter(is_header).first().str.strip_prefix(">").alias("_header"),
        pl.col("raw_line").filter(~is_header).str.join("").alias("sequence"),
    )
    header = pl.col("_header").str.strip_chars()
    out = records.select(
        header.str.extract(r"^(\S+)", 1).alias("entity"),
        pl.col("_path")
        .str.extract(r"([^/\\]+)$", 1)
        .str.replace(r"\.(?:fasta|fa|faa|fas|fna)(?:\.gz)?$", "")
        .alias("sample"),
        header.str.extract(r"^\S+\s+(.*)$", 1).str.strip_chars().alias("description"),
        pl.col("sequence").str.replace_all(r"\s|\*$", "").str.to_uppercase().alias("sequence"),
    )
    out = out.with_columns(
        pl.when(pl.col("description") == "")
        .then(None)
        .otherwise(pl.col("description"))
        .alias("description"),
        pl.col("sequence").str.len_chars().cast(pl.Int64).alias("length"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "entity"])
