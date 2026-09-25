"""Tidy STAR-Fusion's abridged prediction table into one row per fusion call.

STAR-Fusion writes one abridged TSV per sample: the fusion name, the two
partner genes as ``SYMBOL^ENSG`` identifiers, their breakpoints, how the
junction splices, the read evidence split between junction reads and spanning
fragments, whether a long anchor supports the call, the normalised FFPM
abundance and a long annotation string. The recipe strips the Ensembl id off the
gene symbols, sums the two evidence counts into one supporting-read count, and
derives ``log_ffpm`` (a compressed abundance scale) and ``junction_fraction``
(the share of the evidence that crosses the junction itself, which sizes the dot
plot).

Only the abridged table is matched. The full ``fusion_predictions.tsv`` is a
superset that repeats these columns plus the per-read detail, so reading both
would double every call.

The per-sample file carries no sample column, so the source declares
``source_path`` and the sample is read off the file name.

Output columns:
    sample, fusion, gene_5p, gene_3p, breakpoint_5p, breakpoint_3p, splice_type,
    junction_reads, spanning_frags, supporting_reads, ffpm, log_ffpm,
    junction_fraction, large_anchor_support, annotations
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# The sample exists only in the file NAME (`starfusion/<sample>.starfusion.abridged.tsv`): the source hands every
# row the path of its file, and the sample is the basename minus the suffix.
# Without it a cohort run pools every sample's calls into one table.
_SOURCE_PATH = "_source_path"
_SAMPLE_SUFFIX = ".starfusion.abridged.tsv"


def _sample() -> pl.Expr:
    """``starfusion/S1.starfusion.abridged.tsv`` -> ``S1``."""
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
        glob_pattern="starfusion/*.starfusion.abridged.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
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
    "large_anchor_support": pl.Utf8,
    "annotations": pl.Utf8,
}


def _text(name: str) -> pl.Expr:
    """Read a text column as a never-null string so no render binds a null."""
    return pl.col(name).cast(pl.Utf8).fill_null("")


def _symbol(name: str) -> pl.Expr:
    """Keep the gene symbol from a ``SYMBOL^ENSG00000123456.7`` identifier."""
    return _text(name).str.split("^").list.first()


def _count(name: str) -> pl.Expr:
    """Read a read-count column as a never-null integer."""
    return pl.col(name).cast(pl.Int64, strict=False).fill_null(0)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Normalise the gene symbols and derive the aggregated read evidence."""
    df = sources["fusions"]

    base = df.select(
        _sample(),
        _text("#FusionName").alias("fusion"),
        _symbol("LeftGene").alias("gene_5p"),
        _symbol("RightGene").alias("gene_3p"),
        _text("LeftBreakpoint").alias("breakpoint_5p"),
        _text("RightBreakpoint").alias("breakpoint_3p"),
        _text("SpliceType").alias("splice_type"),
        _count("JunctionReadCount").alias("junction_reads"),
        _count("SpanningFragCount").alias("spanning_frags"),
        pl.col("FFPM").cast(pl.Float64, strict=False).fill_null(0.0).alias("ffpm"),
        _text("LargeAnchorSupport").alias("large_anchor_support"),
        _text("annots").alias("annotations"),
    ).with_columns(
        (pl.col("junction_reads") + pl.col("spanning_frags")).alias("supporting_reads"),
        (pl.col("ffpm") + 1).log10().cast(pl.Float64).alias("log_ffpm"),
    )

    return base.with_columns(
        pl.when(pl.col("supporting_reads") > 0)
        .then(pl.col("junction_reads") / pl.col("supporting_reads"))
        .otherwise(0.0)
        .cast(pl.Float64)
        .alias("junction_fraction"),
    ).select(list(EXPECTED_SCHEMA))
