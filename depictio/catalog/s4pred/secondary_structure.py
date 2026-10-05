"""One row per residue of an S4PRED ss2 file (PSIPRED VFORMAT).

Consumes the raw ``s4pred_ss2_raw`` scan (one line per row in ``raw_line``,
the ``#`` comment dropped by the scan, the blank line read as null, plus
``source_path``). Each data line is ``position residue state P(C) P(H) P(E)``.

The pipeline names every ss2 file after the sequence id, so ``entity`` is the
file name without ``.ss2``; the sample is the directory above ``ss2/``
(nf-core writes ``s4pred/<sample>/ss2/<sequence id>.ss2``), else the entity.

Residue table columns: ``category`` is the predicted state spelled out
(Helix, Strand, Coil) and ``value`` the probability of that state.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "s4pred_ss2_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "position": pl.Int64,
    "residue": pl.Utf8,
    "ss_code": pl.Utf8,
    "category": pl.Utf8,
    "value": pl.Float64,
    "p_coil": pl.Float64,
    "p_helix": pl.Float64,
    "p_strand": pl.Float64,
}

STATES = {"H": "Helix", "E": "Strand", "C": "Coil"}


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=EXPECTED_SCHEMA)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split every residue line and name the predicted state."""
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
        pl.col("raw_line").str.replace_all(r"\s+", " ").str.splitn(" ", 6).alias("_p")
    )

    def f(i: int) -> pl.Expr:
        return pl.col("_p").struct.field(f"field_{i}")

    entity = pl.col("_path").str.extract(r"([^/\\]+)$", 1).str.replace(r"\.ss2$", "")
    sample = pl.col("_path").str.extract(r"([^/\\]+)[/\\]ss2[/\\][^/\\]+$", 1)
    out = parts.select(
        entity.alias("entity"),
        pl.coalesce(sample, entity).alias("sample"),
        f(0).cast(pl.Int64, strict=False).alias("position"),
        f(1).alias("residue"),
        f(2).alias("ss_code"),
        f(3).cast(pl.Float64, strict=False).alias("p_coil"),
        f(4).cast(pl.Float64, strict=False).alias("p_helix"),
        f(5).cast(pl.Float64, strict=False).alias("p_strand"),
    ).filter(pl.col("position").is_not_null())
    out = out.with_columns(
        pl.col("ss_code").replace_strict(STATES, default=None).alias("category"),
        pl.when(pl.col("ss_code") == "H")
        .then(pl.col("p_helix"))
        .when(pl.col("ss_code") == "E")
        .then(pl.col("p_strand"))
        .otherwise(pl.col("p_coil"))
        .alias("value"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "entity", "position"])
