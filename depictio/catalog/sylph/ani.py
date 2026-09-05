"""sylph per-genome containment: ANI against abundance and coverage.

``sylph profile`` reports, for every reference genome it detects in a sample, the
adjusted ANI of the containment match together with the taxonomic and sequence
abundances and the effective coverage. Read-count profilers cannot express this: ANI
says how close the reads are to the reference the abundance is attributed to, so a
high-abundance / low-ANI genome marks a confident-looking call that is really a
divergent relative.

The sample identifier is a column of the file itself (``Sample_file``), so a glob over
the per-sample tables keeps its per-sample resolution.

Output: sample, genome, contig_name, taxonomic_abundance, abundance_frac,
sequence_abundance, adjusted_ani, naive_ani, eff_cov, median_cov, containment_frac,
kmers_reassigned.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="profile", glob_pattern="sylph/*/*.sylph.tsv", format="tsv"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "genome": pl.Utf8,
    "contig_name": pl.Utf8,
    "taxonomic_abundance": pl.Float64,
    "abundance_frac": pl.Float64,
    "sequence_abundance": pl.Float64,
    "adjusted_ani": pl.Float64,
    "naive_ani": pl.Float64,
    "eff_cov": pl.Float64,
    "median_cov": pl.Float64,
    "containment_frac": pl.Float64,
    "kmers_reassigned": pl.Int64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# Read-file suffixes taxprofiler leaves on the sylph sample name.
_READ_SUFFIXES = (
    ".fastq.gz",
    ".fq.gz",
    ".fastq",
    ".fq",
    "_1.unmapped_other",
    "_1.unmapped",
    "_2.unmapped",
    ".unmapped_other",
    ".unmapped",
    ".merged",
    "_1",
    "_2",
)


def _sample_expr() -> pl.Expr:
    """Reduce `<sample>_1.unmapped.fastq.gz` back to the samplesheet sample id."""
    expr = pl.col("Sample_file").cast(pl.Utf8).str.split("/").list.last()
    for suffix in _READ_SUFFIXES:
        expr = expr.str.strip_suffix(suffix)
    return expr.alias("sample")


def _float(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Utf8).cast(pl.Float64, strict=False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Normalise the sylph profile columns and derive the 0-1 abundance fraction."""
    df = sources["profile"]
    required = {"Sample_file", "Genome_file", "Taxonomic_abundance", "Adjusted_ANI"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"sylph ani: the profile tables are missing {sorted(missing)}")

    def optional(column: str) -> pl.Expr:
        return _float(column) if column in df.columns else pl.lit(None, dtype=pl.Float64)

    # `Containment_ind` is "<shared>/<total>" k-mers; the ratio is the useful number.
    containment = (
        (
            pl.col("Containment_ind")
            .cast(pl.Utf8)
            .str.split_exact("/", 1)
            .struct.field("field_0")
            .cast(pl.Float64, strict=False)
            / pl.col("Containment_ind")
            .cast(pl.Utf8)
            .str.split_exact("/", 1)
            .struct.field("field_1")
            .cast(pl.Float64, strict=False)
        )
        if "Containment_ind" in df.columns
        else pl.lit(None, dtype=pl.Float64)
    )

    return (
        df.with_columns(
            _sample_expr(),
            pl.col("Genome_file")
            .cast(pl.Utf8)
            .str.split("/")
            .list.last()
            .str.strip_suffix(".fasta")
            .str.strip_suffix(".fna")
            .alias("genome"),
            (
                pl.col("Contig_name").cast(pl.Utf8)
                if "Contig_name" in df.columns
                else pl.lit(None, dtype=pl.Utf8)
            ).alias("contig_name"),
            _float("Taxonomic_abundance").alias("taxonomic_abundance"),
            optional("Sequence_abundance").alias("sequence_abundance"),
            _float("Adjusted_ANI").alias("adjusted_ani"),
            optional("Naive_ANI").alias("naive_ani"),
            optional("Eff_cov").alias("eff_cov"),
            optional("Median_cov").alias("median_cov"),
            containment.alias("containment_frac"),
            (
                pl.col("kmers_reassigned").cast(pl.Int64, strict=False)
                if "kmers_reassigned" in df.columns
                else pl.lit(0, dtype=pl.Int64)
            ).alias("kmers_reassigned"),
        )
        .with_columns((pl.col("taxonomic_abundance") / 100.0).alias("abundance_frac"))
        .select(
            "sample",
            "genome",
            "contig_name",
            "taxonomic_abundance",
            "abundance_frac",
            "sequence_abundance",
            "adjusted_ani",
            "naive_ani",
            "eff_cov",
            "median_cov",
            "containment_frac",
            "kmers_reassigned",
        )
        .sort(["sample", "taxonomic_abundance"], descending=[False, True])
    )
