"""Tidy the FusionCatcher ``*.fusion-genes.txt`` candidate list into one row per fusion.

FusionCatcher writes one final candidate table per sample: the two partner gene
symbols, the annotation labels it matched the pair against, the read evidence
(common mapping reads, spanning pairs, spanning unique reads, longest anchor),
which finding method produced the call, both genomic breakpoints and the
predicted effect on the coding sequence. Its header carries parenthesised role
hints (``Gene_1_symbol(5end_fusion_partner)``), which this recipe renames to
plain snake-case names.

The recipe joins the two partners into a single ``fusion`` label, keeps the read
counts intact, and derives three ready-to-plot columns: ``supporting_reads``
(spanning pairs plus spanning unique reads), ``log_support`` (its log10, so the
long tail of a fusion table stays readable) and ``unique_fraction`` (how much of
the support comes from uniquely mapped reads, a proxy for call confidence).

The candidate table has no sample column and the recipe harness concatenates the
globbed files without their path, so a row cannot be attributed to a sample. The
fusion is the unit of analysis here, not the sample.

Output columns:
    fusion, gene_5p, gene_3p, description, n_annotations, common_mapping_reads,
    spanning_pairs, spanning_unique_reads, supporting_reads, longest_anchor,
    finding_method, breakpoint_5p, breakpoint_3p, predicted_effect, log_support,
    unique_fraction
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusion_genes",
        glob_pattern="fusioncatcher/*.fusion-genes.txt",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "fusion": pl.Utf8,
    "gene_5p": pl.Utf8,
    "gene_3p": pl.Utf8,
    "description": pl.Utf8,
    "n_annotations": pl.Int64,
    "common_mapping_reads": pl.Int64,
    "spanning_pairs": pl.Int64,
    "spanning_unique_reads": pl.Int64,
    "supporting_reads": pl.Int64,
    "longest_anchor": pl.Int64,
    "finding_method": pl.Utf8,
    "breakpoint_5p": pl.Utf8,
    "breakpoint_3p": pl.Utf8,
    "predicted_effect": pl.Utf8,
    "log_support": pl.Float64,
    "unique_fraction": pl.Float64,
}

_RENAME = {
    "Gene_1_symbol(5end_fusion_partner)": "gene_5p",
    "Gene_2_symbol(3end_fusion_partner)": "gene_3p",
    "Fusion_description": "description",
    "Counts_of_common_mapping_reads": "common_mapping_reads",
    "Spanning_pairs": "spanning_pairs",
    "Spanning_unique_reads": "spanning_unique_reads",
    "Longest_anchor_found": "longest_anchor",
    "Fusion_finding_method": "finding_method",
    "Fusion_point_for_gene_1(5end_fusion_partner)": "breakpoint_5p",
    "Fusion_point_for_gene_2(3end_fusion_partner)": "breakpoint_3p",
    "Predicted_effect": "predicted_effect",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename the parenthesised header, label each fusion and derive its support."""
    df = sources["fusion_genes"].rename(_RENAME, strict=False)

    gene_5p = pl.col("gene_5p").cast(pl.Utf8).fill_null("")
    gene_3p = pl.col("gene_3p").cast(pl.Utf8).fill_null("")
    description = pl.col("description").cast(pl.Utf8).fill_null("")
    spanning_pairs = pl.col("spanning_pairs").cast(pl.Int64, strict=False).fill_null(0)
    spanning_unique = pl.col("spanning_unique_reads").cast(pl.Int64, strict=False).fill_null(0)

    out = df.select(
        pl.concat_str([gene_5p, pl.lit("--"), gene_3p]).alias("fusion"),
        gene_5p.alias("gene_5p"),
        gene_3p.alias("gene_3p"),
        description.alias("description"),
        # The description is a comma separated annotation list; an empty string
        # means the pair matched no annotation database at all.
        pl.when(description.str.len_chars() == 0)
        .then(pl.lit(0, dtype=pl.Int64))
        .otherwise(description.str.count_matches(",").cast(pl.Int64) + 1)
        .alias("n_annotations"),
        pl.col("common_mapping_reads").cast(pl.Int64, strict=False).alias("common_mapping_reads"),
        spanning_pairs.alias("spanning_pairs"),
        spanning_unique.alias("spanning_unique_reads"),
        (spanning_pairs + spanning_unique).alias("supporting_reads"),
        pl.col("longest_anchor").cast(pl.Int64, strict=False).alias("longest_anchor"),
        pl.col("finding_method").cast(pl.Utf8).alias("finding_method"),
        pl.col("breakpoint_5p").cast(pl.Utf8).alias("breakpoint_5p"),
        pl.col("breakpoint_3p").cast(pl.Utf8).alias("breakpoint_3p"),
        pl.col("predicted_effect").cast(pl.Utf8).fill_null("unknown").alias("predicted_effect"),
    )

    support = pl.col("supporting_reads")
    return out.with_columns(
        (support + 1).cast(pl.Float64).log10().alias("log_support"),
        pl.when(support > 0)
        .then(pl.col("spanning_unique_reads") / support)
        .otherwise(0.0)
        .cast(pl.Float64)
        .alias("unique_fraction"),
    ).select(list(EXPECTED_SCHEMA))
