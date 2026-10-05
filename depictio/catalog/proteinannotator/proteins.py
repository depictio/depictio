"""One row per protein: length, domain hits per database, cover, structure.

The protein list is the filtered FASTA (``seqkit/sequences``), so a protein no
database annotated still has its row. Domain counts come from the unified
domain table (``proteinannotator/domains``) and the secondary structure shares
from S4PRED (``s4pred/secondary_structure``); both are optional, and a missing
source leaves its columns at zero or null.

``annotated_pct`` is the share of the protein's residues covered by at least
one domain of any database; ``top_domain`` is the domain with the lowest
E-value, the one a reader would name the protein by.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.protein_annotation import DATABASES, covered_positions

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="sequences", dc_ref="seqkit_sequences"),
    RecipeSource(ref="domains", dc_ref="proteinannotator_domains", optional=True),
    RecipeSource(ref="structure", dc_ref="s4pred_secondary_structure", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "description": pl.Utf8,
    "length": pl.Int64,
    "annotation_status": pl.Utf8,
    "domain_hits": pl.Int64,
    "databases_hit": pl.Int64,
    **{f"{db}_hits": pl.Int64 for db in DATABASES},
    "annotated_residues": pl.Int64,
    "annotated_pct": pl.Float64,
    "top_domain": pl.Utf8,
    "top_domain_database": pl.Utf8,
    "top_domain_evalue": pl.Float64,
    "helix_pct": pl.Float64,
    "strand_pct": pl.Float64,
    "coil_pct": pl.Float64,
}

KEYS = ["entity", "sample"]


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Aggregate the domain and structure tables onto the protein list."""
    proteins = sources["sequences"].select(*KEYS, "description", "length")
    domains = sources.get("domains")
    if domains is None:
        domains = pl.DataFrame(
            schema={
                "entity": pl.Utf8,
                "sample": pl.Utf8,
                "database": pl.Utf8,
                "label": pl.Utf8,
                "start": pl.Int64,
                "end": pl.Int64,
                "evalue": pl.Float64,
            }
        )

    per_db = domains.group_by(KEYS).agg(
        pl.len().cast(pl.Int64).alias("domain_hits"),
        pl.col("database").n_unique().cast(pl.Int64).alias("databases_hit"),
        *[(pl.col("database") == db).sum().cast(pl.Int64).alias(f"{db}_hits") for db in DATABASES],
    )
    top = (
        domains.sort("evalue", nulls_last=True)
        .group_by(KEYS, maintain_order=True)
        .first()
        .select(
            *KEYS,
            pl.col("label").alias("top_domain"),
            pl.col("database").alias("top_domain_database"),
            pl.col("evalue").alias("top_domain_evalue"),
        )
    )
    cover = (
        covered_positions(domains, by=tuple(KEYS))
        .group_by(KEYS)
        .agg(pl.len().cast(pl.Int64).alias("annotated_residues"))
    )
    out = proteins.join(per_db, on=KEYS, how="left").join(top, on=KEYS, how="left")
    out = out.join(cover, on=KEYS, how="left")

    structure = sources.get("structure")
    if structure is not None and not structure.is_empty():
        shares = structure.group_by(KEYS).agg(
            *[
                ((pl.col("category") == state).mean() * 100.0).alias(f"{name}_pct")
                for state, name in (("Helix", "helix"), ("Strand", "strand"), ("Coil", "coil"))
            ]
        )
        out = out.join(shares, on=KEYS, how="left")
    else:
        out = out.with_columns(
            *[pl.lit(None, dtype=pl.Float64).alias(f"{n}_pct") for n in ("helix", "strand", "coil")]
        )

    counts = ["domain_hits", "databases_hit", *[f"{db}_hits" for db in DATABASES]]
    out = out.with_columns(
        *[pl.col(c).fill_null(0) for c in counts],
        pl.col("annotated_residues").fill_null(0),
    )
    out = out.with_columns(
        pl.when(pl.col("length") > 0)
        .then(pl.col("annotated_residues") * 100.0 / pl.col("length"))
        .otherwise(None)
        .alias("annotated_pct"),
        pl.when(pl.col("domain_hits") > 0)
        .then(pl.lit("annotated"))
        .otherwise(pl.lit("unannotated"))
        .alias("annotation_status"),
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(KEYS)
