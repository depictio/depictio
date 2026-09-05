"""Tidy the CTAT-SPLICING ``*.cancer.introns`` candidate table into one row per intron.

CTAT-SPLICING annotates the splice junctions of a STAR alignment against the
CTAT cancer intron reference and writes the surviving candidates here. On top of
the plain junction columns it adds how often the intron was seen in TCGA tumour
cohorts and in GTEx normal tissues, each packed as a
``ESCA:26:13.61,STAD:32:8.06`` list of ``<cohort>:<count>:<percent>`` entries
ordered by decreasing prevalence, plus a variant name when the junction matches a
known event.

The recipe splits the packed intron coordinate and the ``ALK^ENSG00000171094.18``
gene string into plain columns, counts the TCGA cohorts and GTEx tissues, keeps
the leading (most prevalent) entry of each list, and exposes the unique-read
count as a float ``score`` because the manhattan render requires a float score.
A run in which no junction matched a cancer intron writes this file with a
header and no rows.

The candidate table carries no sample column and the recipe harness concatenates
the globbed files without their path, so a row cannot be attributed to a sample.
The intron is the unit of analysis here, not the sample.

Output columns:
    intron, chrom, start, end, strand, gene, gene_id, uniq_mapped, multi_mapped,
    score, n_tcga_cohorts, top_tcga_cohort, top_tcga_pct, n_gtex_tissues,
    top_gtex_tissue, top_gtex_pct, variant_name
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="cancer_introns",
        glob_pattern="ctatsplicing/*.cancer.introns",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "intron": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "gene": pl.Utf8,
    "gene_id": pl.Utf8,
    "uniq_mapped": pl.Int64,
    "multi_mapped": pl.Int64,
    "score": pl.Float64,
    "n_tcga_cohorts": pl.Int64,
    "top_tcga_cohort": pl.Utf8,
    "top_tcga_pct": pl.Float64,
    "n_gtex_tissues": pl.Int64,
    "top_gtex_tissue": pl.Utf8,
    "top_gtex_pct": pl.Float64,
    "variant_name": pl.Utf8,
}


def _entries(column: str) -> pl.Expr:
    """The ``<cohort>:<count>:<percent>`` entries of a packed count list."""
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .fill_null("")
        .str.split(",")
        .list.eval(pl.element().filter(pl.element().str.len_chars() > 0))
    )


def _n(list_col: str) -> pl.Expr:
    """How many entries the packed list holds (0 when it is empty)."""
    return pl.col(list_col).list.len().cast(pl.Int64)


def _top_name(list_col: str) -> pl.Expr:
    """The cohort or tissue of the leading (most prevalent) entry."""
    return pl.col(list_col).list.first().fill_null("").str.split(":").list.first().fill_null("")


def _top_pct(list_col: str) -> pl.Expr:
    """The percentage of the leading (most prevalent) entry."""
    return (
        pl.col(list_col)
        .list.first()
        .fill_null("")
        .str.extract(r":([\d.]+)$", 1)
        .cast(pl.Float64, strict=False)
        .fill_null(0.0)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split the packed coordinate, gene and cohort strings into plain columns."""
    df = sources["cancer_introns"]

    intron = pl.col("intron").cast(pl.Utf8)
    # The first gene wins when a junction is annotated against several of them.
    first_gene = pl.col("genes").cast(pl.Utf8).fill_null("").str.split(",").list.first()
    variant = pl.col("variant_name").cast(pl.Utf8).fill_null("")

    out = df.select(
        intron.alias("intron"),
        intron.str.extract(r"^([^:]+):", 1).alias("chrom"),
        intron.str.extract(r":(\d+)-", 1).cast(pl.Int64, strict=False).alias("start"),
        intron.str.extract(r"-(\d+)$", 1).cast(pl.Int64, strict=False).alias("end"),
        pl.col("strand").cast(pl.Utf8).alias("strand"),
        first_gene.str.split("^").list.first().alias("gene"),
        first_gene.str.extract(r"\^(.+)$", 1).fill_null("").alias("gene_id"),
        pl.col("uniq_mapped").cast(pl.Int64, strict=False).fill_null(0).alias("uniq_mapped"),
        pl.col("multi_mapped").cast(pl.Int64, strict=False).fill_null(0).alias("multi_mapped"),
        _entries("TCGA_sample_counts").alias("tcga"),
        _entries("GTEx_sample_counts").alias("gtex"),
        # "NA" is how the tool spells "no matching known variant".
        pl.when(variant == "NA").then(pl.lit("")).otherwise(variant).alias("variant_name"),
    )

    return (
        out.with_columns(
            _n("tcga").alias("n_tcga_cohorts"),
            _top_name("tcga").alias("top_tcga_cohort"),
            _top_pct("tcga").alias("top_tcga_pct"),
            _n("gtex").alias("n_gtex_tissues"),
            _top_name("gtex").alias("top_gtex_tissue"),
            _top_pct("gtex").alias("top_gtex_pct"),
            # The manhattan render needs a float score.
            pl.col("uniq_mapped").cast(pl.Float64).alias("score"),
        )
        .sort("chrom", "start")
        .select(list(EXPECTED_SCHEMA))
    )
