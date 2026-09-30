"""One row per domain hit of an ``hmmsearch --domtblout`` table.

Consumes the raw ``hmmer_domtbl_raw`` scan: one data line per row in
``raw_line`` (the ``#`` header lines are dropped by the scan), plus
``source_path``. The domtbl is space-aligned with 22 fixed fields and a free
text description last, so each line is split on runs of spaces into at most 23
parts.

In an hmmsearch table the target is the sequence and the query is the HMM, so
``entity`` is the target name and ``label`` the family. The database is the
directory the file sits in (``<db>/<sample>.domtbl.gz``, the nf-core layout),
and the sample is the file name without its ``.domtbl(.gz)`` suffix.

``start`` / ``end`` are the ENVELOPE coordinates on the sequence (the span the
domain is annotated over, as Pfam reports it); the alignment span is kept in
``ali_from`` / ``ali_to``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "hmmer_domtbl_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "source": pl.Utf8,
    "label": pl.Utf8,
    "accession": pl.Utf8,
    "description": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "protein_length": pl.Int64,
    "hmm_length": pl.Int64,
    "domain_index": pl.Int64,
    "domain_count": pl.Int64,
    "seq_evalue": pl.Float64,
    "seq_score": pl.Float64,
    "c_evalue": pl.Float64,
    "i_evalue": pl.Float64,
    "dom_score": pl.Float64,
    "dom_bias": pl.Float64,
    "hmm_from": pl.Int64,
    "hmm_to": pl.Int64,
    "ali_from": pl.Int64,
    "ali_to": pl.Int64,
    "acc": pl.Float64,
    "hmm_coverage": pl.Float64,
    "neg_log10_evalue": pl.Float64,
}

# domtbl field order (0-based) after splitting a line on runs of spaces.
_FIELDS = {
    "entity": 0,
    "protein_length": 2,
    "label": 3,
    "accession": 4,
    "hmm_length": 5,
    "seq_evalue": 6,
    "seq_score": 7,
    "domain_index": 9,
    "domain_count": 10,
    "c_evalue": 11,
    "i_evalue": 12,
    "dom_score": 13,
    "dom_bias": 14,
    "hmm_from": 15,
    "hmm_to": 16,
    "ali_from": 17,
    "ali_to": 18,
    "start": 19,
    "end": 20,
    "acc": 21,
    "description": 22,
}


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=EXPECTED_SCHEMA)


def _field(name: str) -> pl.Expr:
    return pl.col("_parts").struct.field(f"field_{_FIELDS[name]}")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split every domtbl line into its typed fields."""
    raw = sources["raw"]
    if raw is None or "raw_line" not in raw.columns:
        return _empty()
    path = (
        pl.col("source_path").cast(pl.Utf8)
        if "source_path" in raw.columns
        else pl.lit(None, dtype=pl.Utf8)
    )
    lines = raw.select(pl.col("raw_line").cast(pl.Utf8).str.strip_chars(), path.alias("_path"))
    lines = lines.filter(
        pl.col("raw_line").is_not_null()
        & (pl.col("raw_line") != "")
        & ~pl.col("raw_line").str.starts_with("#")
    )
    if lines.is_empty():
        return _empty()
    parts = lines.with_columns(
        pl.col("raw_line").str.replace_all(r"\s+", " ").str.splitn(" ", 23).alias("_parts")
    )
    ints = ["protein_length", "hmm_length", "domain_index", "domain_count", "hmm_from", "hmm_to"]
    ints += ["ali_from", "ali_to", "start", "end"]
    floats = ["seq_evalue", "seq_score", "c_evalue", "i_evalue", "dom_score", "dom_bias", "acc"]
    file_name = pl.col("_path").str.extract(r"([^/\\]+)$", 1)
    out = parts.select(
        _field("entity").alias("entity"),
        file_name.str.replace(r"\.domtbl(?:\.txt)?(?:\.gz)?$", "").alias("sample"),
        pl.col("_path").str.extract(r"([^/\\]+)[/\\][^/\\]+$", 1).alias("source"),
        _field("label").alias("label"),
        pl.when(_field("accession") == "-")
        .then(None)
        .otherwise(_field("accession"))
        .alias("accession"),
        pl.when(_field("description").is_in(["-", ""]))
        .then(None)
        .otherwise(_field("description"))
        .alias("description"),
        *[_field(c).cast(pl.Int64, strict=False).alias(c) for c in ints],
        *[_field(c).cast(pl.Float64, strict=False).alias(c) for c in floats],
    )
    out = out.with_columns(
        pl.coalesce(pl.col("sample"), pl.lit("run")).alias("sample"),
        pl.coalesce(pl.col("source"), pl.lit("hmmsearch")).alias("source"),
        pl.when(pl.col("hmm_length") > 0)
        .then((pl.col("hmm_to") - pl.col("hmm_from") + 1) / pl.col("hmm_length"))
        .otherwise(None)
        .alias("hmm_coverage"),
        (-pl.col("i_evalue").clip(lower_bound=1e-300).log10()).alias("neg_log10_evalue"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "entity", "source", "start"])
