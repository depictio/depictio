"""Tidy the FusionInspector abridged fusion table into one row per fusion call.

FusionInspector re-aligns the reads of a run against a mini-genome built from the
candidate fusion contigs and writes ``*.FusionInspector.fusions.abridged.tsv``:
one row per fusion transcript pair, with the junction and spanning read support,
the normalised expression (FFPM), the fusion-allele ratios (FAR) against each
partner's own expression, and the protein-level consequence of the fusion.

The recipe keeps the read evidence, derives the total supporting reads and the
junction fraction, splits the ``SYMBOL^ENSG`` partner fields into plain gene
symbols, puts FFPM on a log scale so the very wide dynamic range is plottable,
and counts the Pfam domains each partner contributes. FusionInspector writes a
literal ``.`` for every field it could not compute (a fusion with no junction
reads has no CDS and no protein consequence), so those are mapped to ``unknown``
or an empty string rather than kept as a fake category.

The abridged table carries no sample column and the recipe harness concatenates
the globbed files without their path, so no ``sample`` column can be recovered:
the fusion is the unit of analysis here.

Output columns:
    fusion, gene_5p, gene_3p, breakpoint_5p, breakpoint_3p, splice_type,
    junction_reads, spanning_frags, supporting_reads, ffpm, log_ffpm,
    junction_fraction, far_left, far_right, counter_fusion_left,
    counter_fusion_right, prot_fusion_type, large_anchor_support, cds_left_id,
    cds_right_id, n_domains_5p, n_domains_3p
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusions",
        glob_pattern="fusioninspector/*/*.FusionInspector.fusions.abridged.tsv",
        format="TSV",
        # `annots` embeds JSON-ish double quotes, so quoting must stay off.
        read_kwargs={"infer_schema_length": 10000, "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "fusion": pl.Utf8,
    "gene_5p": pl.Utf8,
    "gene_3p": pl.Utf8,
    "breakpoint_5p": pl.Utf8,
    "breakpoint_3p": pl.Utf8,
    "splice_type": pl.Utf8,
    "junction_reads": pl.Int64,
    "spanning_frags": pl.Int64,
    "supporting_reads": pl.Int64,
    "ffpm": pl.Float64,
    "log_ffpm": pl.Float64,
    "junction_fraction": pl.Float64,
    "far_left": pl.Float64,
    "far_right": pl.Float64,
    "counter_fusion_left": pl.Int64,
    "counter_fusion_right": pl.Int64,
    "prot_fusion_type": pl.Utf8,
    "large_anchor_support": pl.Utf8,
    "cds_left_id": pl.Utf8,
    "cds_right_id": pl.Utf8,
    "n_domains_5p": pl.Int64,
    "n_domains_3p": pl.Int64,
}


def _symbol(column: str) -> pl.Expr:
    """``FGFR3^ENSG00000068078.20`` -> ``FGFR3``."""
    return pl.col(column).cast(pl.Utf8).str.split("^").list.first()


def _n_domains(column: str) -> pl.Expr:
    """Count the ``^``-joined Pfam records; ``.`` means the partner has none."""
    field = pl.col(column).cast(pl.Utf8).fill_null(".")
    return (
        pl.when(field == ".")
        .then(pl.lit(0))
        .otherwise(field.str.count_matches(r"\^") + 1)
        .cast(pl.Int64)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Derive the read-support, expression and protein-level fusion columns."""
    df = sources["fusions"]
    junction = pl.col("JunctionReadCount").cast(pl.Int64)
    spanning = pl.col("SpanningFragCount").cast(pl.Int64)
    supporting = (junction + spanning).alias("supporting_reads")
    ffpm = pl.col("FFPM").cast(pl.Float64)

    return (
        df.select(
            pl.col("#FusionName").cast(pl.Utf8).alias("fusion"),
            _symbol("LeftGene").alias("gene_5p"),
            _symbol("RightGene").alias("gene_3p"),
            pl.col("LeftBreakpoint").cast(pl.Utf8).alias("breakpoint_5p"),
            pl.col("RightBreakpoint").cast(pl.Utf8).alias("breakpoint_3p"),
            pl.col("SpliceType").cast(pl.Utf8).alias("splice_type"),
            junction.alias("junction_reads"),
            spanning.alias("spanning_frags"),
            supporting,
            ffpm.alias("ffpm"),
            (ffpm + 1).log10().alias("log_ffpm"),
            pl.col("FAR_left").cast(pl.Float64).alias("far_left"),
            pl.col("FAR_right").cast(pl.Float64).alias("far_right"),
            pl.col("NumCounterFusionLeft").cast(pl.Int64).alias("counter_fusion_left"),
            pl.col("NumCounterFusionRight").cast(pl.Int64).alias("counter_fusion_right"),
            pl.col("PROT_FUSION_TYPE")
            .cast(pl.Utf8)
            .replace(".", "unknown")
            .fill_null("unknown")
            .alias("prot_fusion_type"),
            pl.col("LargeAnchorSupport").cast(pl.Utf8).alias("large_anchor_support"),
            pl.col("CDS_LEFT_ID").cast(pl.Utf8).replace(".", "").fill_null("").alias("cds_left_id"),
            pl.col("CDS_RIGHT_ID")
            .cast(pl.Utf8)
            .replace(".", "")
            .fill_null("")
            .alias("cds_right_id"),
            _n_domains("PFAM_LEFT").alias("n_domains_5p"),
            _n_domains("PFAM_RIGHT").alias("n_domains_3p"),
        )
        .with_columns(
            # A fusion with no junction reads and no spanning fragments has no
            # denominator, so its junction fraction is 0 rather than null.
            pl.when(pl.col("supporting_reads") > 0)
            .then(pl.col("junction_reads") / pl.col("supporting_reads"))
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("junction_fraction"),
        )
        .sort("supporting_reads", descending=True)
        .select(list(EXPECTED_SCHEMA))
    )
