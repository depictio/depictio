"""Tidy the CTAT-SPLICING ``*.introns`` splice-junction table into one row per intron.

CTAT-SPLICING reads the junctions a STAR alignment reports and writes one row
per intron: the junction coordinate as a single ``chr2:29193923-29196769``
string, the strand, the gene the junction falls in as a ``ALK^ENSG00000171094.18``
symbol/identifier pair (several genes, comma separated, when the junction is
ambiguous) and how many uniquely and multi mapped reads support it. The recipe
splits both packed strings into plain columns, adds the intron length and the
read totals, and exposes the unique-read count as a float ``score`` because the
manhattan render requires a float score.

The ``ctatsplicing/*.introns`` glob also matches the ``*.cancer.introns`` file
the same tool writes, whose three extra annotation columns arrive through the
harness ``diagonal_relaxed`` concat as nulls on the plain rows. The recipe
therefore selects only the five base columns and drops duplicate intron keys.
That is correct because the cancer introns are a subset of all introns: every
cancer row is already present in the full table, with the same coordinates,
strand, gene and read counts.

The junction table carries no sample column, so the source declares
``source_path`` and the sample is read off the file name
(``ctatsplicing/<sample>.introns``, or ``<sample>.cancer.introns`` for the
twin); intron keys are deduplicated per sample.

Output columns:
    sample, intron, chrom, start, end, intron_length, strand, gene, gene_id,
    uniq_mapped, multi_mapped, total_mapped, uniq_fraction, score
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# The sample exists only in the file NAME: the source hands every row the path
# of its file, and the sample is the basename minus the tool suffix. The cancer
# twin's longer suffix is stripped first.
_SOURCE_PATH = "_source_path"
_SAMPLE_SUFFIXES = (".cancer.introns", ".introns")


def _sample() -> pl.Expr:
    """``ctatsplicing/S1.introns`` or ``ctatsplicing/S1.cancer.introns`` -> ``S1``."""
    name = pl.col(_SOURCE_PATH).str.split("/").list.last()
    expr = name
    for suffix in _SAMPLE_SUFFIXES:
        expr = (
            pl.when(name.str.ends_with(suffix)).then(name.str.strip_suffix(suffix)).otherwise(expr)
        )
    return expr.alias("sample")


SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="introns",
        source_path=_SOURCE_PATH,
        glob_pattern="ctatsplicing/*.introns",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "intron": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "intron_length": pl.Int64,
    "strand": pl.Utf8,
    "gene": pl.Utf8,
    "gene_id": pl.Utf8,
    "uniq_mapped": pl.Int64,
    "multi_mapped": pl.Int64,
    "total_mapped": pl.Int64,
    "uniq_fraction": pl.Float64,
    "score": pl.Float64,
}

_BASE_COLUMNS = ["intron", "strand", "genes", "uniq_mapped", "multi_mapped"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split the packed intron and gene strings, then derive lengths and totals."""
    # Only the base columns: the cancer-intron file matched by the same glob
    # brings three extra annotation columns along (see the module docstring).
    df = (
        sources["introns"]
        .select(_sample(), *_BASE_COLUMNS)
        .unique(subset=["sample", "intron"], keep="first", maintain_order=True)
    )

    intron = pl.col("intron").cast(pl.Utf8)
    # The first gene wins when a junction is annotated against several of them.
    first_gene = pl.col("genes").cast(pl.Utf8).fill_null("").str.split(",").list.first()
    uniq = pl.col("uniq_mapped").cast(pl.Int64, strict=False).fill_null(0)
    multi = pl.col("multi_mapped").cast(pl.Int64, strict=False).fill_null(0)

    out = df.select(
        pl.col("sample"),
        intron.alias("intron"),
        intron.str.extract(r"^([^:]+):", 1).alias("chrom"),
        intron.str.extract(r":(\d+)-", 1).cast(pl.Int64, strict=False).alias("start"),
        intron.str.extract(r"-(\d+)$", 1).cast(pl.Int64, strict=False).alias("end"),
        pl.col("strand").cast(pl.Utf8).alias("strand"),
        first_gene.str.split("^").list.first().alias("gene"),
        first_gene.str.extract(r"\^(.+)$", 1).fill_null("").alias("gene_id"),
        uniq.alias("uniq_mapped"),
        multi.alias("multi_mapped"),
        (uniq + multi).alias("total_mapped"),
    )

    total = pl.col("total_mapped")
    return (
        out.with_columns(
            (pl.col("end") - pl.col("start")).alias("intron_length"),
            pl.when(total > 0)
            .then(pl.col("uniq_mapped") / total)
            .otherwise(0.0)
            .cast(pl.Float64)
            .alias("uniq_fraction"),
            # The manhattan render needs a float score.
            pl.col("uniq_mapped").cast(pl.Float64).alias("score"),
        )
        .sort("sample", "chrom", "start")
        .select(list(EXPECTED_SCHEMA))
    )
