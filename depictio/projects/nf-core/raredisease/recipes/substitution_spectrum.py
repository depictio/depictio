"""Substitution spectrum per sample, with the sample's role in the family.

Overrides the catalog module ``vcf/substitution_spectrum`` (it calls the module's own
transform, so the folding and the shares are the module's) and adds one column, ``role``:
the sample's place in the family (Proband / Father / Mother / Sibling / Other), derived
from the pedigree exactly as the ``samples`` hub derives it. The dashboard colours the
spectrum by role like its sibling figures (Ts/Tv, het over hom-alt), so a reader sees
at once whether the proband's spectrum departs from the parents'. Without a pedigree
every sample reads Other.

Sources:
    variants  the ``vcf_variants`` collection (read through ``dc_ref``)
    ped       ``pedigree/*.ped``, optional

Output schema: the catalog module's columns plus
    role : Utf8     Proband / Father / Mother / Sibling / Other
"""

from __future__ import annotations

import polars as pl

from depictio.catalog.vcf import substitution_spectrum as catalog
from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    *catalog.SOURCES,
    RecipeSource(
        ref="ped",
        glob_pattern="pedigree/*.ped",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "new_columns": ["family_id", "sample_id", "father", "mother", "sex", "phenotype"],
            "infer_schema_length": 0,
        },
        input_schema={
            "family_id": pl.Utf8,
            "sample_id": pl.Utf8,
            "father": pl.Utf8,
            "mother": pl.Utf8,
            "phenotype": pl.Utf8,
        },
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {**catalog.OUTPUT_SCHEMA, "role": pl.Utf8}


def _roles(ped: pl.DataFrame | None) -> pl.DataFrame:
    """One row per pedigree sample: ``sample`` and ``role`` (the rule of ``samples.py``)."""
    if ped is None:
        return pl.DataFrame(schema={"sample": pl.Utf8, "role": pl.Utf8})
    rows = ped.filter(~pl.col("family_id").str.starts_with("#")).with_columns(
        pl.col("father", "mother").replace(["0", "", "-9"], None)
    )
    fathers = set(rows["father"].drop_nulls().to_list())
    mothers = set(rows["mother"].drop_nulls().to_list())
    has_parent = pl.col("father").is_not_null() | pl.col("mother").is_not_null()
    affected = pl.col("phenotype") == "2"
    return rows.select(
        pl.col("sample_id").alias("sample"),
        pl.when(pl.col("sample_id").is_in(list(fathers)))
        .then(pl.lit("Father"))
        .when(pl.col("sample_id").is_in(list(mothers)))
        .then(pl.lit("Mother"))
        .when(has_parent & affected)
        .then(pl.lit("Proband"))
        .when(has_parent)
        .then(pl.lit("Sibling"))
        .otherwise(pl.lit("Other"))
        .alias("role"),
    ).unique(subset="sample", keep="first", maintain_order=True)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """The catalog spectrum, with each sample's role joined on."""
    spectrum = catalog.transform({"variants": sources["variants"]})
    return (
        spectrum.join(_roles(sources.get("ped")), on="sample", how="left")
        .with_columns(pl.col("role").fill_null("Other"))
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
    )
