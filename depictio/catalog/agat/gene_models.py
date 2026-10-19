"""The gene models of each annotation, one row per assembly and feature type.

AGAT's report (``agat_sp_statistics.pl``) answers the questions an annotation is
judged on, scattered over a hundred lines per feature type; this recipe pulls
them into one row per assembly and transcript type (``mrna`` for protein-coding
genes, ``lnc_rna``, ``trna``...). Only types that AGAT counts genes for are
kept (``region`` and ``sequence_feature`` describe the sequences, not genes).

Counts (genes, transcripts, exons) come from the full block. The per-transcript
shape (exons per transcript, transcript length) comes from the
longest-isoform block when AGAT wrote one: one transcript per gene, so two
annotations compare on their gene models rather than on how many isoforms each
kept. A type without isoforms has only the full block, which then answers both.

Input: every ``*.stats.txt`` under the run, one line per row, with its path in
``source_path``. The parsing lives in ``depictio.recipes.lib.agat_stats``.

Output schema:
    genome : Utf8                     assembly, from the file name
    feature_type : Utf8               transcript type: mrna, lnc_rna, trna, ...
    genes : Int64                     genes with a transcript of that type
    transcripts : Int64               transcripts of the type
    transcripts_per_gene : Float64    their mean per gene
    exons : Int64                     exons of those transcripts
    exons_per_transcript : Float64    mean exons per transcript (longest isoform)
    single_exon_genes : Int64         genes whose transcript has one exon (0 when AGAT prints no line)
    single_exon_gene_pct : Float64    of the genes, percent; null without genes
    overlapping_genes : Int64         genes overlapping another gene of the type
    mean_gene_length : Float64        bp
    median_gene_length : Float64      bp
    mean_transcript_length : Float64  bp, introns included (longest isoform)
    mean_exon_length : Float64        bp
    mean_intron_length : Float64      bp, introns between exons
    mean_cds_length : Float64         bp, spliced coding length; null for non-coding types
    total_gene_length : Int64         bp covered by the genes
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.agat_stats import (
    RAW_LINE_COL,
    READ_KWARGS,
    SOURCE_PATH_COL,
    parse_reports,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reports",
        glob_pattern="**/*.stats.txt",
        format="csv",
        read_kwargs=READ_KWARGS,
        source_path=SOURCE_PATH_COL,
        input_schema={RAW_LINE_COL: pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "feature_type": pl.Utf8,
    "genes": pl.Int64,
    "transcripts": pl.Int64,
    "transcripts_per_gene": pl.Float64,
    "exons": pl.Int64,
    "exons_per_transcript": pl.Float64,
    "single_exon_genes": pl.Int64,
    "single_exon_gene_pct": pl.Float64,
    "overlapping_genes": pl.Int64,
    "mean_gene_length": pl.Float64,
    "median_gene_length": pl.Float64,
    "mean_transcript_length": pl.Float64,
    "mean_exon_length": pl.Float64,
    "mean_intron_length": pl.Float64,
    "mean_cds_length": pl.Float64,
    "total_gene_length": pl.Int64,
}

#: Output column -> (AGAT metric with ``{t}`` for the feature type, block).
#: ``full`` reads the whole annotation; ``longest`` the one-isoform block,
#: falling back to the full one for a type that has no isoforms.
METRICS: dict[str, tuple[str, str]] = {
    "genes": ("Number of gene", "full"),
    "transcripts": ("Number of {t}", "full"),
    "transcripts_per_gene": ("mean {t}s per gene", "full"),
    "exons": ("Number of exon", "full"),
    "exons_per_transcript": ("mean exons per {t}", "longest"),
    "single_exon_genes": ("Number of single exon gene", "full"),
    "overlapping_genes": ("Number gene overlapping", "full"),
    "mean_gene_length": ("mean gene length (bp)", "full"),
    "median_gene_length": ("median gene length (bp)", "full"),
    "mean_transcript_length": ("mean {t} length (bp)", "longest"),
    "mean_exon_length": ("mean exon length (bp)", "full"),
    "mean_intron_length": ("mean intron in exon length (bp)", "full"),
    "mean_cds_length": ("mean cds length (bp)", "longest"),
    "total_gene_length": ("Total gene length (bp)", "full"),
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per assembly and gene-bearing feature type."""
    long = parse_reports(sources["reports"])
    if long.is_empty():
        raise ValueError("agat_gene_models: no AGAT statistics block in the matched files")

    values: dict[tuple[str, str, str, str], float | None] = {
        (g, f, i, m): v
        for g, f, i, m, v in long.select(
            "genome", "feature_type", "isoforms", "metric", "value"
        ).iter_rows()
    }
    keys = (
        long.filter(pl.col("metric") == "Number of gene")
        .select("genome", "feature_type")
        .unique(maintain_order=True)
        .iter_rows()
    )
    rows: list[dict] = []
    for genome, feature in keys:
        row: dict = {"genome": genome, "feature_type": feature}
        for column, (template, block) in METRICS.items():
            metric = template.format(t=feature)
            full = values.get((genome, feature, "all", metric))
            if block == "longest":
                row[column] = values.get((genome, feature, "longest", metric), full)
            else:
                row[column] = full
        rows.append(row)
    if not rows:
        raise ValueError("agat_gene_models: no feature type with genes in the AGAT reports")

    frame = pl.DataFrame(
        rows,
        schema={
            c: (pl.Float64 if c not in ("genome", "feature_type") else pl.Utf8)
            for c in OUTPUT_SCHEMA
        },
        orient="row",
    )
    # AGAT prints the single-exon lines only when there is one: a type with
    # genes and no such line has none.
    frame = frame.with_columns(
        pl.when(pl.col("genes") > 0)
        .then(pl.col("single_exon_genes").fill_null(0))
        .otherwise(pl.col("single_exon_genes"))
        .alias("single_exon_genes")
    )
    return (
        frame.with_columns(
            pl.when(pl.col("genes") > 0)
            .then((pl.col("single_exon_genes") * 100.0 / pl.col("genes")).round(2))
            .otherwise(None)
            .alias("single_exon_gene_pct")
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["genome", "genes"], descending=[False, True])
    )
