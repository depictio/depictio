"""OptiType typing per sample: the genotype, its zygosity and its support.

One row per sample, from the optimal solution of its ``<sample>_result.tsv``:
the two alleles of HLA-A, -B and -C, the distinct alleles as the
``;``-separated list an epitopeprediction samplesheet takes in its ``alleles``
column (normalised to ``HLA-A*02:01``), how many loci were typed and how many
are homozygous or heterozygous (and the homozygous count as a label, for
colour), the reads the genotype explains, the solver's
objective and the objective per read.

The objective is not a fit score of its own. OptiType maximises the reads its
alleles explain less ``beta`` (``--beta``, 0.009 by default) times the reads for
every heterozygous locus, so ``objective / reads`` is about ``1 - beta x
heterozygous_loci``: it reads the zygosity. The support of a genotype is its
reads and, with ``--enumerations`` above 1, the objective gap to the runner-up
solution, a measure of how clearly the optimum wins (null with a single
solution); the table counts the solutions too.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.optitype import (
    HETEROZYGOUS,
    HOMOZYGOUS,
    best_calls,
    read_calls,
    with_call_annotations,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="results",
        input_schema={"source_path": pl.Utf8, "Reads": pl.Utf8, "Objective": pl.Utf8},
        glob_pattern="optitype/*/*_result.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "hla_a": pl.Utf8,
    "hla_b": pl.Utf8,
    "hla_c": pl.Utf8,
    "alleles": pl.Utf8,
    "distinct_alleles": pl.Int64,
    "typed_loci": pl.Int64,
    "homozygous_loci": pl.Int64,
    "heterozygous_loci": pl.Int64,
    "homozygous_class": pl.Utf8,
    "reads": pl.Int64,
    "objective": pl.Float64,
    "objective_per_read": pl.Float64,
    "solutions": pl.Int64,
    "runner_up_gap": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_LOCI = {"hla_a": "HLA-A", "hla_b": "HLA-B", "hla_c": "HLA-C"}


def homozygous_class(n: int | None) -> str | None:
    """``No homozygous locus``, ``1 homozygous locus``, ``2 homozygous loci`` ..."""
    if n is None:
        return None
    if n == 0:
        return "No homozygous locus"
    return f"{n} homozygous locus" if n == 1 else f"{n} homozygous loci"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    every = read_calls(sources["results"])
    calls = best_calls(every)
    if calls.is_empty():
        raise ValueError("OptiType results: no sample has a typed locus")
    annotated = with_call_annotations(calls).sort(["sample_id", "locus", "haplotype"])

    genotype = annotated.group_by(["sample_id", "locus"]).agg(
        pl.col("allele").str.join(" / ").alias("pair"),
        (pl.col("zygosity") == HOMOZYGOUS).any().alias("_hom"),
        (pl.col("zygosity") == HETEROZYGOUS).any().alias("_het"),
    )
    per_locus = genotype.pivot(on="locus", index="sample_id", values="pair")
    for column, locus in _LOCI.items():
        per_locus = per_locus.with_columns(
            (pl.col(locus) if locus in per_locus.columns else pl.lit(None, dtype=pl.Utf8)).alias(
                column
            )
        )

    per_sample = annotated.group_by("sample_id").agg(
        pl.col("allele").unique().sort().str.join(";").alias("alleles"),
        pl.col("allele").n_unique().cast(pl.Int64).alias("distinct_alleles"),
        pl.col("locus").n_unique().cast(pl.Int64).alias("typed_loci"),
        pl.col("reads").first(),
        pl.col("objective").first(),
    )
    homozygous = genotype.group_by("sample_id").agg(
        pl.col("_hom").sum().cast(pl.Int64).alias("homozygous_loci"),
        pl.col("_het").sum().cast(pl.Int64).alias("heterozygous_loci"),
    )
    # Solutions per sample, and the objective gap between the best two.
    solutions = (
        every.group_by(["sample_id", "solution"])
        .agg(pl.col("objective").first())
        .sort(["sample_id", "solution"])
        .group_by("sample_id", maintain_order=True)
        .agg(
            pl.len().cast(pl.Int64).alias("solutions"),
            pl.col("objective").alias("_objectives"),
        )
        .with_columns(
            pl.when(pl.col("solutions") > 1)
            .then(
                (
                    pl.col("_objectives").list.get(0, null_on_oob=True)
                    - pl.col("_objectives").list.get(1, null_on_oob=True)
                ).round(4)
            )
            .otherwise(None)
            .cast(pl.Float64)
            .alias("runner_up_gap")
        )
        .drop("_objectives")
    )
    out = (
        per_sample.join(per_locus.select(["sample_id", *_LOCI]), on="sample_id", how="left")
        .join(homozygous, on="sample_id", how="left")
        .join(solutions, on="sample_id", how="left")
        .with_columns(
            pl.when(pl.col("reads") > 0)
            .then((pl.col("objective") / pl.col("reads")).round(4))
            .otherwise(None)
            .alias("objective_per_read"),
            pl.col("objective").round(3),
            pl.col("homozygous_loci")
            .map_elements(homozygous_class, return_dtype=pl.Utf8)
            .alias("homozygous_class"),
        )
    )
    return out.select(list(OUTPUT_SCHEMA)).sort("sample_id")
