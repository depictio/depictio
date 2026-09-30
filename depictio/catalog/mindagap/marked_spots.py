"""Mindagap duplicatefinder's marked spot tables, counted per sample and gene:
how many spots each gene contributes, and how many spots were set aside as
duplicates along the tile grid lines.

``mindagap/duplicatefinder`` rewrites the input spot table (headerless TSV,
``x y z gene`` plus whatever trailing columns the instrument wrote) to
``<spot table stem>_markedDups.txt``, with the gene of every spot it finds
duplicated across a grid line replaced by ``Duplicated``. Those rows are kept
here under ``status = duplicated`` (one row per sample, ``gene = Duplicated``),
the rest under ``status = kept``.

Sample id: the file stem without ``_markedDups``. A pipeline may prefix the
stem with its own sample id (nf-core/molkart publishes
``<sample>_<spot table stem>_markedDups.txt``); when the run declares a
``samples`` hub, the stem is mapped to the longest hub id it equals or starts
with (followed by ``_``), so the output joins the hub whatever the spot table
was called. Without a hub the stem is the sample.

Output schema:
    sample : Utf8            sample id
    gene : Utf8              gene, or "Duplicated" for the duplicate row
    status : Utf8            kept | duplicated
    spots : Int64            spots of that gene (or duplicates) in the sample
    pct_of_sample : Float64  share of the sample's spots (kept + duplicated), percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="spots",
        glob_pattern="**/*_markedDups.txt",
        format="TSV",
        read_kwargs={"has_header": False, "infer_schema_length": 0, "truncate_ragged_lines": True},
        source_path="source_path",
    ),
    RecipeSource(ref="samples", dc_ref="samples", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "gene": pl.Utf8,
    "status": pl.Utf8,
    "spots": pl.Int64,
    "pct_of_sample": pl.Float64,
}

DUPLICATED = "Duplicated"
SUFFIX = "_markedDups.txt"
#: headerless column holding the gene: x, y, z, gene
GENE_COLUMN = "column_4"


def _hub_ids(samples: pl.DataFrame | None) -> list[str]:
    if samples is None or samples.is_empty():
        return []
    for col in ("sample_id", "sample"):
        if col in samples.columns:
            return [s for s in samples[col].cast(pl.Utf8).drop_nulls().unique().to_list() if s]
    return []


def _sample(path: str, hub: list[str]) -> str:
    stem = path.rsplit("/", 1)[-1].removesuffix(SUFFIX)
    matches = [h for h in hub if stem == h or stem.startswith(f"{h}_")]
    return max(matches, key=len) if matches else stem


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Marked spot tables -> spots per (sample, gene), duplicates on their own row."""
    raw = sources["spots"]
    if raw is None or GENE_COLUMN not in raw.columns:
        columns = None if raw is None else raw.columns
        raise ValueError(f"mindagap marked_spots: no gene column (4th field), got {columns}")
    hub = _hub_ids(sources.get("samples"))
    names = {p: _sample(p, hub) for p in raw["source_path"].unique().to_list()}

    gene = pl.col(GENE_COLUMN).cast(pl.Utf8).str.strip_chars()
    counts = (
        raw.select(
            pl.col("source_path").replace_strict(names, return_dtype=pl.Utf8).alias("sample"),
            gene.alias("gene"),
        )
        .filter(pl.col("gene").is_not_null() & (pl.col("gene") != ""))
        .with_columns(
            pl.when(pl.col("gene").str.contains(DUPLICATED, literal=True))
            .then(pl.lit(DUPLICATED))
            .otherwise(pl.col("gene"))
            .alias("gene")
        )
        .group_by(["sample", "gene"])
        .agg(pl.len().cast(pl.Int64).alias("spots"))
    )
    return (
        counts.with_columns(
            pl.when(pl.col("gene") == DUPLICATED)
            .then(pl.lit("duplicated"))
            .otherwise(pl.lit("kept"))
            .alias("status"),
            (100.0 * pl.col("spots") / pl.col("spots").sum().over("sample"))
            .cast(pl.Float64)
            .alias("pct_of_sample"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "spots", "gene"], descending=[False, True, False])
    )
