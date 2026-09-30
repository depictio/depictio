"""Every domain of every searched database in one domain table.

Joins the hmmsearch domain hits of the four HMM libraries
(``hmmer/hmmsearch_domtbl``, one ``source`` per library) with the InterProScan
signature matches (``interproscan/matches``) into the contract's domain table:
``entity``, ``start``, ``end``, ``label``, ``source``. Either input may be
absent (a run with ``--skip_interproscan`` or with every HMM library skipped).

``database`` is the pipeline's search (pfam, funfam, nmpfams, metagroot,
interproscan); ``source`` is the finer origin a reader recognises: the HMM
library for hmmsearch, the member database (SFLD, HAMAP, ...) for InterProScan.
``accession`` is the HMM accession (hmmsearch) or the integrated InterPro entry
(InterProScan); ``description`` is the signature description InterProScan
reports (hmmsearch reports none for the family).

hmmsearch domains are kept when their independent E-value passes HMMER's own
default domain inclusion threshold (``--incdomE 0.01``); the raw hmmer table
keeps every reported domain. InterProScan matches are kept as reported (each
member database applies its own curated cut-offs).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="hmmer", dc_ref="hmmer_hmmsearch_domtbl", optional=True),
    RecipeSource(ref="interproscan", dc_ref="interproscan_matches", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "domain_id": pl.Utf8,
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "database": pl.Utf8,
    "source": pl.Utf8,
    "label": pl.Utf8,
    "description": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "span": pl.Int64,
    "protein_length": pl.Int64,
    "evalue": pl.Float64,
    "neg_log10_evalue": pl.Float64,
    "score": pl.Float64,
    "hmm_coverage": pl.Float64,
    "accession": pl.Utf8,
}

#: HMMER's default domain inclusion threshold (``--incdomE``).
INCLUSION_EVALUE = 0.01


def _hmmer(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("i_evalue") <= INCLUSION_EVALUE).select(
        "entity",
        "sample",
        pl.col("source").str.to_lowercase().alias("database"),
        "source",
        "label",
        pl.lit(None, dtype=pl.Utf8).alias("description"),
        "start",
        "end",
        "protein_length",
        pl.col("i_evalue").alias("evalue"),
        pl.col("dom_score").alias("score"),
        "hmm_coverage",
        "accession",
    )


def _interproscan(df: pl.DataFrame) -> pl.DataFrame:
    return df.select(
        "entity",
        "sample",
        pl.lit("interproscan").alias("database"),
        "source",
        "label",
        "description",
        "start",
        "end",
        "protein_length",
        "evalue",
        pl.lit(None, dtype=pl.Float64).alias("score"),
        pl.lit(None, dtype=pl.Float64).alias("hmm_coverage"),
        pl.col("interpro_accession").alias("accession"),
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Stack the hmmsearch and InterProScan spans into one domain table."""
    parts = []
    hmmer = sources.get("hmmer")
    if hmmer is not None and not hmmer.is_empty():
        parts.append(_hmmer(hmmer))
    ipr = sources.get("interproscan")
    if ipr is not None and not ipr.is_empty():
        parts.append(_interproscan(ipr))
    if not parts:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    out = pl.concat(parts, how="vertical_relaxed")
    out = out.with_columns(
        (pl.col("end") - pl.col("start") + 1).cast(pl.Int64).alias("span"),
        (-pl.col("evalue").clip(lower_bound=1e-300).log10()).alias("neg_log10_evalue"),
        pl.concat_str(
            ["entity", "database", "label", "start", "end"], separator=":", ignore_nulls=True
        ).alias("domain_id"),
    )
    out = out.unique(subset=["domain_id", "sample"], keep="first", maintain_order=True)
    return out.select(list(EXPECTED_SCHEMA)).sort(["sample", "entity", "start", "database"])
