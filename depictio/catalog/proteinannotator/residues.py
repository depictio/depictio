"""The residue table of every protein: sequence, secondary structure, domains.

One row per residue of the filtered FASTA (``seqkit/sequences``), so every
protein has its full chain whether or not a later step annotated it. The
contract's residue columns are ``entity``, ``position``, ``residue``,
``category`` (the S4PRED state: Helix, Strand or Coil) and ``value`` (the
probability of that state). ``domain`` is the lowest E-value domain covering
the residue (any database) and ``domains_here`` how many domains cover it.

``sequence`` repeats the protein's full one-letter chain on each of its rows:
a structure tile in resolve mode folds the protein it shows from this column
(ESMFold through the structure resolver), and the rows it reads are this
protein's residues.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="sequences", dc_ref="seqkit_sequences"),
    RecipeSource(ref="structure", dc_ref="s4pred_secondary_structure", optional=True),
    RecipeSource(ref="domains", dc_ref="proteinannotator_domains", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "position": pl.Int64,
    "residue": pl.Utf8,
    "category": pl.Utf8,
    "value": pl.Float64,
    "domain": pl.Utf8,
    "domain_database": pl.Utf8,
    "domains_here": pl.Int64,
    "sequence": pl.Utf8,
}

KEYS = ["entity", "sample"]


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Explode every sequence into residues and attach structure and domains."""
    seqs = sources["sequences"].filter(pl.col("sequence").is_not_null() & (pl.col("length") > 0))
    residues = (
        seqs.select(
            *KEYS,
            "sequence",
            pl.col("sequence").str.split("").alias("residue"),
        )
        .with_columns(pl.int_ranges(1, pl.col("residue").list.len() + 1).alias("position"))
        .explode(["residue", "position"])
        .with_columns(pl.col("position").cast(pl.Int64))
    )

    structure = sources.get("structure")
    if structure is not None and not structure.is_empty():
        residues = residues.join(
            structure.select(*KEYS, "position", "category", "value"),
            on=[*KEYS, "position"],
            how="left",
        )
    else:
        residues = residues.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("category"),
            pl.lit(None, dtype=pl.Float64).alias("value"),
        )

    domains = sources.get("domains")
    if domains is not None and not domains.is_empty():
        spans = domains.select(
            *KEYS,
            pl.col("label").alias("domain"),
            pl.col("database").alias("domain_database"),
            "evalue",
            pl.int_ranges(pl.col("start"), pl.col("end") + 1).alias("position"),
        ).explode("position")
        spans = spans.with_columns(pl.col("position").cast(pl.Int64))
        per_residue = (
            spans.sort("evalue", nulls_last=True)
            .group_by([*KEYS, "position"], maintain_order=True)
            .agg(
                pl.col("domain").first(),
                pl.col("domain_database").first(),
                pl.len().cast(pl.Int64).alias("domains_here"),
            )
        )
        residues = residues.join(per_residue, on=[*KEYS, "position"], how="left")
    else:
        residues = residues.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("domain"),
            pl.lit(None, dtype=pl.Utf8).alias("domain_database"),
            pl.lit(None, dtype=pl.Int64).alias("domains_here"),
        )
    residues = residues.with_columns(pl.col("domains_here").fill_null(0))
    return residues.select(list(EXPECTED_SCHEMA)).sort([*KEYS, "position"])
