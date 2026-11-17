"""nf-core/rnavar genotype concordance: how alike two samples' PASS genotypes are.

The square sample-by-sample matrix of the share of PASS genotype calls two
samples have in common. A genotype call is a site (contig, position and alleles,
``variant_key``) with its genotype, so a site both samples call but one as
heterozygous and the other as homozygous is a disagreement, not a match. The
share is the Jaccard index of the two samples' calls: calls both make, over
calls either makes, in percent.

Replicates of one cell line should sit near each other and apart from the other
lines; a replicate that sits with another line is a swap, a contaminated library
or a very shallow one. RNA calls follow expression, so no pair reaches 100 off
the diagonal: the comparison is between pairs, not against a ceiling.

The matrix is symmetric with 100 on the diagonal, the shape the heatmap's
clustering expects.

Sources:
    variants  ``vcf_variants`` (this template's ``variants.py``)

Output schema: ``sample`` (Utf8, the heatmap's index) plus one Float64 column per
sample, named after it, holding the percentage; null where neither sample made a
call.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants",
        dc_ref="vcf_variants",
        input_schema={
            "sample": pl.Utf8,
            "variant_key": pl.Utf8,
            "gt": pl.Utf8,
            "is_pass": pl.Boolean,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
}
# One column per sample of the run, unknown until ingest.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Compare every pair of samples on the genotype calls they share."""
    calls = (
        sources["variants"]
        .filter(
            pl.col("is_pass").fill_null(False)
            & pl.col("sample").is_not_null()
            & pl.col("variant_key").is_not_null()
        )
        .select(
            "sample",
            # "1|0" and "0/1" are the same genotype: drop the phase, sort the alleles.
            pl.concat_str(
                [
                    pl.col("variant_key"),
                    pl.col("gt")
                    .fill_null("")
                    .str.replace_all(r"\|", "/")
                    .str.split("/")
                    .list.sort()
                    .list.join("/"),
                ],
                separator="#",
            ).alias("call"),
        )
        .unique()
    )
    samples = sorted(calls["sample"].unique().to_list())
    if not samples:
        return pl.DataFrame(schema={"sample": pl.Utf8})
    calls_of = {s: calls.filter(pl.col("sample") == s).select("call") for s in samples}
    size = {s: frame.height for s, frame in calls_of.items()}

    def concordance(a: str, b: str) -> float | None:
        if a == b:
            return 100.0
        both = calls_of[a].join(calls_of[b], on="call", how="inner").height
        either = size[a] + size[b] - both
        return round(both * 100.0 / either, 2) if either else None

    rows = {a: [concordance(a, b) for b in samples] for a in samples}
    return pl.DataFrame(
        {
            "sample": samples,
            **{b: [rows[a][j] for a in samples] for j, b in enumerate(samples)},
        },
        schema={"sample": pl.Utf8, **{b: pl.Float64 for b in samples}},
    )
