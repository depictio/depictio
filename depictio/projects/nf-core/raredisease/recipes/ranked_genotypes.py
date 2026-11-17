"""nf-core/raredisease ranked genotypes: one row per ranked variant and carrying sample.

``ranked_variants`` holds one row per variant with the family's genotypes packed
into ``calls`` (``sample|GT|DP|GQ|VAF`` for every sample carrying the alternate
allele, joined by ``;``). This recipe unpacks it, so a sample filter can narrow
the ranked variants to the ones that sample carries (the template links this
collection to the sample hub on ``sample`` and to ``ranked_variants`` on
``variant_key``), and the per-sample views (who carries a de novo call, how deep
each genotype was read) have a row to count.

Sources:
    ranked  ``ranked_variants`` (this template's ``ranked_variants.py``)

Output schema:
    variant_key : Utf8      the ranked variant (links to ranked_variants)
    sample : Utf8           the carrying sample
    gt : Utf8               genotype as written (0/1, 1/1, ...)
    gt_class : Utf8         Hom alt, Het or Half call (one allele missing)
    dp : Int64              read depth of the sample at the variant
    gq : Int64              genotype quality
    vaf : Float64           alternate allele fraction from the allele depths
    gene : Utf8             the variant's first gene symbol
    call_label : Utf8       gene and protein (or coding) change, the label of a figure row
    rank_score : Float64    the variant's family rank score, for ordering
    model_class : Utf8      the variant's inheritance model class
    de_novo : Boolean       the variant fits a de novo model
    impact : Utf8           the variant's VEP impact
    is_clinical : Boolean   the clinical VCF holds the variant
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="ranked",
        dc_ref="ranked_variants",
        input_schema={
            "variant_key": pl.Utf8,
            "calls": pl.Utf8,
            "gene": pl.Utf8,
            "call_label": pl.Utf8,
            "rank_score": pl.Float64,
            "model_class": pl.Utf8,
            "de_novo": pl.Boolean,
            "impact": pl.Utf8,
            "is_clinical": pl.Boolean,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "variant_key": pl.Utf8,
    "sample": pl.Utf8,
    "gt": pl.Utf8,
    "gt_class": pl.Utf8,
    "dp": pl.Int64,
    "gq": pl.Int64,
    "vaf": pl.Float64,
    "gene": pl.Utf8,
    "call_label": pl.Utf8,
    "rank_score": pl.Float64,
    "model_class": pl.Utf8,
    "de_novo": pl.Boolean,
    "impact": pl.Utf8,
    "is_clinical": pl.Boolean,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpack ``calls`` into one row per carrying sample."""
    ranked = sources["ranked"].filter(pl.col("calls").is_not_null())
    fields = pl.col("call").str.split("|")
    gt = fields.list.get(1, null_on_oob=True)
    alleles = gt.str.replace_all(r"[|/]", ",").str.split(",")
    carried = alleles.list.eval(pl.element().str.contains(r"[1-9]")).list.sum()
    return (
        ranked.with_columns(pl.col("calls").str.split(";").alias("call"))
        .explode("call")
        .with_columns(
            fields.list.get(0, null_on_oob=True).alias("sample"),
            gt.alias("gt"),
            fields.list.get(2, null_on_oob=True).cast(pl.Int64, strict=False).alias("dp"),
            fields.list.get(3, null_on_oob=True).cast(pl.Int64, strict=False).alias("gq"),
            fields.list.get(4, null_on_oob=True).cast(pl.Float64, strict=False).alias("vaf"),
        )
        .with_columns(
            pl.when(gt.str.contains(r"\."))
            .then(pl.lit("Half call"))
            .when(carried == 2)
            .then(pl.lit("Hom alt"))
            .otherwise(pl.lit("Het"))
            .alias("gt_class")
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "variant_key"])
    )
