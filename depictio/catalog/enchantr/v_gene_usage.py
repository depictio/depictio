"""V gene usage per sample, at family and gene resolution, in long format.

airrflow's ``repertoire_comparison.Rmd`` runs alakazam's ``countGenes`` after
clonal assignment and writes two tables under ``repertoire_comparison/V_family/``:
the V family distribution (IGHV1 ... IGHV7, TRBV ...) and the V gene
distribution by sequence (IGHV3-23, IGHV4-59 ...). Both have the same shape, so
they are stacked into one long table with a ``rank`` column naming the
resolution, which is what a stacked composition over a switchable level needs.

Columns: sample_id, subject_id, locus, rank ("V family" or "V gene"), taxon (the
gene or family name), v_family (the family, also for gene rows), seq_count,
locus_count (the per-sample, per-locus denominator) and seq_freq.

For gene rows the family is the IMGT prefix before the first hyphen
(``IGHV3-23`` -> ``IGHV3``), which is what alakazam's own ``getFamily`` returns;
a name with no hyphen is its own family. The gene table alone is enough to
rebuild the family rows, but the family table is read directly when present so
the family numbers stay the report's own.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

_V_FAMILY_DIR = "repertoire_comparison/V_family"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="family", path=f"{_V_FAMILY_DIR}/V_family_distribution_data.tsv", format="TSV"
    ),
    RecipeSource(
        ref="gene",
        path=f"{_V_FAMILY_DIR}/V_gene_distribution_by_sequence_data.tsv",
        format="TSV",
        optional=True,
    ),
]

FAMILY_RANK = "V family"
GENE_RANK = "V gene"

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "locus": pl.Utf8,
    "rank": pl.Utf8,
    "taxon": pl.Utf8,
    "v_family": pl.Utf8,
    "seq_count": pl.Int64,
    "locus_count": pl.Int64,
    "seq_freq": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def _subject(df: pl.DataFrame) -> pl.Expr:
    """The clone-definition group. A report without one gets a single group."""
    if "subject_id" in df.columns:
        return pl.col("subject_id").cast(pl.Utf8)
    return pl.lit("all", dtype=pl.Utf8).alias("subject_id")


def _level(df: pl.DataFrame, rank: str) -> pl.DataFrame:
    """One resolution of the usage table, cast and renamed to the shared shape."""
    taxon = pl.col("gene").cast(pl.Utf8)
    family = taxon if rank == FAMILY_RANK else taxon.str.split("-").list.first()
    return df.select(
        pl.col("sample_id").cast(pl.Utf8),
        _subject(df),
        pl.col("locus").cast(pl.Utf8),
        pl.lit(rank, dtype=pl.Utf8).alias("rank"),
        taxon.alias("taxon"),
        family.cast(pl.Utf8).alias("v_family"),
        pl.col("seq_count").cast(pl.Int64),
        pl.col("locus_count").cast(pl.Int64),
        pl.col("seq_freq").cast(pl.Float64),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Stack the family and gene usage tables into one long table."""
    frames = [_level(sources["family"], FAMILY_RANK)]
    gene = sources.get("gene")
    if gene is not None:
        frames.append(_level(gene, GENE_RANK))
    out = pl.concat(frames, how="vertical_relaxed")
    return out.sort(["rank", "sample_id", "locus", "taxon"])
