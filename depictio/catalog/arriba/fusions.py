"""Tidy Arriba's ``fusions.tsv`` into one row per retained fusion call.

Arriba writes one TSV per sample listing the fusions it kept, with the two
partner genes, their breakpoints, the transcriptomic site each breakpoint falls
in, the event type, the reading frame and the read evidence split across four
columns (``split_reads1``, ``split_reads2``, ``discordant_mates`` and the two
local coverages). The recipe joins the partners into a single ``fusion`` label,
sums the evidence into one supporting-read count, and derives two numbers a plot
can bind directly: ``log_support`` (a compressed evidence scale) and
``support_fraction`` (the share of local reads that support the fusion, which
sizes the dot plot).

Arriba writes ``.`` for a missing value, so the source reads it as null and the
recipe fills the text columns with an empty string and the read counts with 0.
That keeps every rendered column non-null. The discarded calls Arriba writes to
``fusions.discarded.tsv`` are a different file and are not matched here.

The per-sample file carries no sample column, so the source declares
``source_path`` and the sample is read off the file name.

Each breakpoint is a ``chrom:position`` string, so the recipe also splits the
chromosome out of both of them and pairs them into ``chrom_pair``. That reads the
same rows as a partner-chromosome flow (an intra-chromosomal duplication and a
translocation are different events) and gives a fusion-level grouping on a run
whose sample column is constant.

Output columns:
    sample, fusion, gene_5p, gene_3p, breakpoint_5p, breakpoint_3p, chrom_5p, chrom_3p,
    chrom_pair, site_5p, site_3p, fusion_type, confidence, reading_frame,
    split_reads, discordant_mates, supporting_reads, coverage, log_support,
    support_fraction, retained_protein_domains, tags
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# The sample exists only in the file NAME (`arriba/<sample>.arriba.fusions.tsv`): the source hands every
# row the path of its file, and the sample is the basename minus the suffix.
# Without it a cohort run pools every sample's calls into one table.
_SOURCE_PATH = "_source_path"
_SAMPLE_SUFFIX = ".arriba.fusions.tsv"


def _sample() -> pl.Expr:
    """``arriba/S1.arriba.fusions.tsv`` -> ``S1``."""
    return (
        pl.col(_SOURCE_PATH)
        .str.split("/")
        .list.last()
        .str.strip_suffix(_SAMPLE_SUFFIX)
        .alias("sample")
    )


SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusions",
        source_path=_SOURCE_PATH,
        glob_pattern="arriba/*.arriba.fusions.tsv",
        format="TSV",
        read_kwargs={
            "infer_schema_length": 10000,
            "quote_char": None,
            # Arriba's placeholder for "not available"; the read-count columns
            # never carry it, so they still parse as integers.
            "null_values": ["."],
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "fusion": pl.Utf8,
    "gene_5p": pl.Utf8,
    "gene_3p": pl.Utf8,
    "breakpoint_5p": pl.Utf8,
    "breakpoint_3p": pl.Utf8,
    "chrom_5p": pl.Utf8,
    "chrom_3p": pl.Utf8,
    "chrom_pair": pl.Utf8,
    "site_5p": pl.Utf8,
    "site_3p": pl.Utf8,
    "fusion_type": pl.Utf8,
    "confidence": pl.Utf8,
    "reading_frame": pl.Utf8,
    "split_reads": pl.Int64,
    "discordant_mates": pl.Int64,
    "supporting_reads": pl.Int64,
    "coverage": pl.Int64,
    "log_support": pl.Float64,
    "support_fraction": pl.Float64,
    "retained_protein_domains": pl.Utf8,
    "tags": pl.Utf8,
}


def _text(name: str) -> pl.Expr:
    """Read a text column as a never-null string so no render binds a null."""
    return pl.col(name).cast(pl.Utf8).fill_null("")


def _count(name: str) -> pl.Expr:
    """Read a read-count column as a never-null integer."""
    return pl.col(name).cast(pl.Int64, strict=False).fill_null(0)


def _chrom(breakpoint_col: str) -> pl.Expr:
    """The contig half of Arriba's ``chrom:position`` breakpoint string."""
    return (
        pl.col(breakpoint_col)
        .str.split(":")
        .list.first()
        .cast(pl.Utf8)
        .fill_null("")
        .replace("", "unknown")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Label each fusion and derive its aggregated read evidence."""
    df = sources["fusions"]

    base = df.select(
        _sample(),
        _text("#gene1").alias("gene_5p"),
        _text("gene2").alias("gene_3p"),
        _text("breakpoint1").alias("breakpoint_5p"),
        _text("breakpoint2").alias("breakpoint_3p"),
        _text("site1").alias("site_5p"),
        _text("site2").alias("site_3p"),
        _text("type").alias("fusion_type"),
        _text("confidence").alias("confidence"),
        _text("reading_frame").alias("reading_frame"),
        (_count("split_reads1") + _count("split_reads2")).alias("split_reads"),
        _count("discordant_mates").alias("discordant_mates"),
        (_count("coverage1") + _count("coverage2")).alias("coverage"),
        _text("retained_protein_domains").alias("retained_protein_domains"),
        _text("tags").alias("tags"),
    ).with_columns(
        pl.concat_str("gene_5p", pl.lit("--"), "gene_3p").alias("fusion"),
        (pl.col("split_reads") + pl.col("discordant_mates")).alias("supporting_reads"),
    )

    local_reads = pl.col("supporting_reads") + pl.col("coverage")
    return (
        base.with_columns(
            (pl.col("supporting_reads") + 1).log10().cast(pl.Float64).alias("log_support"),
            pl.when(local_reads > 0)
            .then(pl.col("supporting_reads") / local_reads)
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("support_fraction"),
            _chrom("breakpoint_5p").alias("chrom_5p"),
            _chrom("breakpoint_3p").alias("chrom_3p"),
        )
        .with_columns(
            pl.concat_str("chrom_5p", pl.lit(" to "), "chrom_3p").alias("chrom_pair"),
        )
        .select(list(EXPECTED_SCHEMA))
    )
