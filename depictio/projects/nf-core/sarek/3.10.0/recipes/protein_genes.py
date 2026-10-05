"""One row per gene of the coding-variant lollipop: the Genes tab's selector.

Reads ``snpeff_protein_lollipop`` (coding variants with an amino-acid position,
one row per sample, caller and variant, on the genes carrying the most of them)
and folds it to one row per gene:

* ``gene``: the gene symbol, the same column name and values as the lollipop,
  so a point picked on the scatter narrows the lollipop and moves the 3D
  structure to that gene;
* ``variants``: distinct variants on the protein; ``positions``: distinct
  amino-acid positions they hit;
* ``calls``: distinct sample and variant pairs, whatever the caller;
* ``shared_pct``: the share of those calls that two or more callers made, in
  percent. A gene whose variants only one caller sees is usually a mapping or
  repeat artefact rather than a real burden;
* ``samples``, ``callers``: how many samples and callers put a variant on it;
* ``high_variants``, ``moderate_variants``: distinct variants of each impact;
* ``worst_impact``: the most severe impact class on the gene (HIGH, then
  MODERATE, then LOW);
* ``median_vaf``: the median variant allele fraction of its calls.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="variants", dc_ref="snpeff_protein_lollipop")]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene": pl.Utf8,
    "variants": pl.Int64,
    "positions": pl.Int64,
    "calls": pl.Int64,
    "shared_pct": pl.Float64,
    "samples": pl.Int64,
    "callers": pl.Int64,
    "high_variants": pl.Int64,
    "moderate_variants": pl.Int64,
    "worst_impact": pl.Utf8,
    "median_vaf": pl.Float64,
}

#: Impact classes from the most to the least severe.
IMPACT_ORDER: list[str] = ["HIGH", "MODERATE", "LOW"]


def _distinct_variants(impact: str) -> pl.Expr:
    """Distinct variants of one impact class on the gene."""
    return pl.col("variant_key").filter(pl.col("impact") == impact).n_unique().cast(pl.Int64)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Fold the coding variants per gene, with the caller agreement of its calls."""
    df = sources["variants"]
    calls = (
        df.group_by("gene", "sample", "variant_key")
        .agg(pl.col("caller").n_unique().alias("n_callers"))
        .group_by("gene")
        .agg(
            pl.len().cast(pl.Int64).alias("calls"),
            ((pl.col("n_callers") >= 2).mean() * 100).alias("shared_pct"),
        )
    )
    rank = pl.col("impact").replace_strict(
        {impact: i for i, impact in enumerate(IMPACT_ORDER)},
        default=len(IMPACT_ORDER),
        return_dtype=pl.Int64,
    )
    per_gene = df.group_by("gene").agg(
        pl.col("variant_key").n_unique().cast(pl.Int64).alias("variants"),
        pl.col("aa_pos").n_unique().cast(pl.Int64).alias("positions"),
        pl.col("sample").n_unique().cast(pl.Int64).alias("samples"),
        pl.col("caller").n_unique().cast(pl.Int64).alias("callers"),
        _distinct_variants("HIGH").alias("high_variants"),
        _distinct_variants("MODERATE").alias("moderate_variants"),
        pl.col("impact").sort_by(rank).first().alias("worst_impact"),
        pl.col("vaf").median().cast(pl.Float64).alias("median_vaf"),
    )
    return (
        per_gene.join(calls, on="gene", how="left")
        .select(list(EXPECTED_SCHEMA))
        .sort(["variants", "gene"], descending=[True, False])
    )
