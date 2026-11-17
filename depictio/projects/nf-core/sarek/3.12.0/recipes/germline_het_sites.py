"""The normal's heterozygous germline sites, read in the tumour: where did a parental copy go?

A person is heterozygous at tens of thousands of sites of an exome: half of the reads carry the
alternate allele (an allele fraction of 0.5). In a tumour that has lost one parental copy of a
region (loss of heterozygosity, LOH) the same sites are read at a fraction near 0 or 1, and in one
that gained a copy at about 0.33 or 0.67. So the tumour's allele fraction at the *normal's*
heterozygous sites, read along the genome, shows the regions that lost or gained a copy and, when it
sits at 0.5 everywhere, a tumour that kept both.

The reads of both samples are in one record when a caller genotypes the pair together (Freebayes on a
pair), which is where this collection comes from: one row per single-nucleotide site whose normal
genotype is heterozygous and whose two depths reach ``MIN_DEPTH`` (10). A run without such a caller
has no table and the section is skipped. A tumour whose purity is below 100 % mixes in normal reads,
so a lost copy reads at 0.1 to 0.2 rather than 0.

``allele_state`` bins the tumour's fraction: ``Balanced`` (0.35 to 0.65, both copies), ``Imbalanced``
(0.15 to 0.35 or 0.65 to 0.85, a gained or partly lost copy) and ``LOH-like`` (under 0.15 or over
0.85, one parental allele nearly gone). ``chrom_rank`` orders the contigs 1 to 22, then X, Y and
the rest, for an axis.

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf import SOURCE_PATH_COL
from depictio.recipes.lib.vcf_somatic import joint_het_sites

MIN_DEPTH = 10
BALANCED = "Balanced"
IMBALANCED = "Imbalanced"
LOH_LIKE = "LOH-like"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        dc_ref="vcf_calls_raw",
        input_schema={"raw_line": pl.Utf8, "source_path": pl.Utf8},
    ),
    RecipeSource(
        ref="pairs",
        dc_ref="pairs",
        input_schema={"pair_id": pl.Utf8, "patient": pl.Utf8, "tumour": pl.Utf8, "normal": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "unit": pl.Utf8,
    "patient": pl.Utf8,
    "sample": pl.Utf8,
    "normal": pl.Utf8,
    "chrom": pl.Utf8,
    "chrom_rank": pl.Int64,
    "pos": pl.Int64,
    "variant_key": pl.Utf8,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "normal_vaf": pl.Float64,
    "normal_dp": pl.Int64,
    "tumour_vaf": pl.Float64,
    "tumour_dp": pl.Int64,
    "allele_state": pl.Utf8,
}


def _chrom_rank() -> pl.Expr:
    """1 to 22 for the autosomes, 23 X, 24 Y, 25 for a mitochondrial or unplaced contig."""
    name = pl.col("chrom").str.replace(r"(?i)^chr", "").str.to_uppercase()
    number = name.cast(pl.Int64, strict=False)
    return (
        pl.when(number.is_between(1, 22))
        .then(number)
        .when(name == "X")
        .then(pl.lit(23))
        .when(name == "Y")
        .then(pl.lit(24))
        .otherwise(pl.lit(25))
        .cast(pl.Int64)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Read the pair's heterozygous normal sites in the tumour."""
    raw = sources["raw"]
    pairs = sources["pairs"].select(
        pl.col("pair_id").alias("unit"),
        pl.col("patient"),
        pl.col("tumour").alias("sample"),
        "normal",
    )
    sites = joint_het_sites(raw.select("raw_line", SOURCE_PATH_COL), min_depth=MIN_DEPTH)
    if sites.is_empty():
        raise ValueError(
            "sarek germline_het_sites: no pair genotyped jointly (Freebayes) among the run's VCFs"
        )
    out = sites.join(pairs, on="unit", how="inner")
    if out.is_empty():
        raise ValueError("sarek germline_het_sites: no jointly genotyped pair of the sample sheet")
    state = pl.col("tumour_vaf")
    return (
        out.with_columns(
            _chrom_rank().alias("chrom_rank"),
            pl.when(state.is_between(0.35, 0.65))
            .then(pl.lit(BALANCED))
            .when(state.is_between(0.15, 0.85))
            .then(pl.lit(IMBALANCED))
            .otherwise(pl.lit(LOH_LIKE))
            .alias("allele_state"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["unit", "chrom_rank", "pos"])
    )
