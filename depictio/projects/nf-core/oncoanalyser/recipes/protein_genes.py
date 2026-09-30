"""One row per tumor and gene with a protein change: the protein tab's selector.

Reads the protein changes (``purple_protein_changes``) and, when present, the
driver catalog (``purple_drivers``), and folds them to one row per tumor and
gene, the unit the protein views show one at a time:

* ``entity``: the gene symbol, the same column name and values as the protein
  changes, so a point picked on the scatter narrows the lollipop and moves the
  3D structure to that gene;
* ``changes``: protein changes on the gene in that tumor; ``hotspots``: how
  many of them sit at a known hotspot;
* ``max_af``: the highest purity-adjusted allele frequency among them (near the
  tumor's clonal level for an early, clonal change);
* ``worst_effect``: the most severe coding effect among them
  (``NONSENSE_OR_FRAMESHIFT``, then ``MISSENSE``, ``SPLICE``, ``SYNONYMOUS``);
* ``driver_likelihood``: PURPLE's likelihood that the gene's somatic point
  mutations drive the tumor, from the ``MUTATION`` row of the driver catalog;
  0 when the catalog has no such row (the gene is outside the driver panel or
  its changes do not qualify), so every gene keeps its point;
* ``gene_role``: ``ONCO`` or ``TSG`` from the driver catalog, ``unlisted`` when
  the gene is not in it; ``driver_types``: every somatic driver type the
  catalog lists for the gene in that tumor, comma separated (a missense change
  on a gene that is also lost reads ``LOH, MUTATION``);
* ``reported``: True when PURPLE reports one of those drivers.

The driver catalog is optional: without it the likelihood is 0 and the role
``unlisted`` for every gene.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="changes", dc_ref="purple_protein_changes"),
    RecipeSource(ref="drivers", dc_ref="purple_drivers", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    "changes": pl.Int64,
    "hotspots": pl.Int64,
    "max_af": pl.Float64,
    "worst_effect": pl.Utf8,
    "driver_likelihood": pl.Float64,
    "gene_role": pl.Utf8,
    "driver_types": pl.Utf8,
    "reported": pl.Boolean,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Coding effects from the most to the least severe; anything else ranks last.
EFFECT_ORDER: list[str] = ["NONSENSE_OR_FRAMESHIFT", "MISSENSE", "SPLICE", "SYNONYMOUS"]

KEYS = ["entity", "sample"]


def _driver_summary(drivers: pl.DataFrame | None) -> pl.DataFrame:
    """Per tumor and gene: point-mutation likelihood, role, somatic driver types."""
    schema = {
        "entity": pl.Utf8,
        "sample": pl.Utf8,
        "driver_likelihood": pl.Float64,
        "gene_role": pl.Utf8,
        "driver_types": pl.Utf8,
        "driver_reported": pl.Boolean,
    }
    if drivers is None or drivers.is_empty():
        return pl.DataFrame(schema=schema)
    somatic = drivers.filter(pl.col("origin") == "somatic")
    return (
        somatic.group_by(pl.col("gene").alias("entity"), "sample")
        .agg(
            pl.col("driver_likelihood")
            .filter(pl.col("driver") == "MUTATION")
            .max()
            .alias("driver_likelihood"),
            pl.col("category").drop_nulls().first().alias("gene_role"),
            pl.col("driver").unique().sort().str.join(", ").alias("driver_types"),
            pl.col("reported").any().alias("driver_reported"),
        )
        .select(list(schema))
        .cast(schema)
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Fold the protein changes per tumor and gene, then add the driver fields."""
    changes = sources["changes"]
    rank = pl.col("category").replace_strict(
        {effect: i for i, effect in enumerate(EFFECT_ORDER)},
        default=len(EFFECT_ORDER),
        return_dtype=pl.Int64,
    )
    per_gene = changes.group_by(KEYS).agg(
        pl.len().cast(pl.Int64).alias("changes"),
        pl.col("hotspot").fill_null(False).sum().cast(pl.Int64).alias("hotspots"),
        pl.col("value").max().alias("max_af"),
        pl.col("category").sort_by(rank).first().alias("worst_effect"),
    )
    out = per_gene.join(_driver_summary(sources.get("drivers")), on=KEYS, how="left")
    return (
        out.with_columns(
            pl.col("driver_likelihood").fill_null(0.0),
            pl.col("gene_role").fill_null("unlisted"),
            pl.col("driver_types").fill_null(""),
            pl.col("driver_reported").fill_null(False).alias("reported"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["driver_likelihood", "changes", "entity"], descending=[True, True, False])
    )
