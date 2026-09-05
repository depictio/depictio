"""Sample by sample matrix of shared clones, for a clustered heatmap.

enchantR's ``clonal_overlap.tsv`` lists, for every pair of samples that share a
subject, the comma-separated ids of the clones found in both. The recipe counts
those ids and pivots them into a symmetric matrix: one row per sample
(``sample_id``), one Float64 column per sample, ``subject_id`` alongside as a
row annotation.

Pairs enchantR never compared are 0, and clones are defined within a subject,
so samples from different subjects always read 0. The diagonal is 0 too: a
sample's overlap with itself is its whole repertoire and would flatten the
colour scale that the real sharing lives in.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

_TABLES = "clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="overlap", path=f"{_TABLES}/clonal_overlap.tsv", format="TSV"),
    RecipeSource(ref="num_clones", path=f"{_TABLES}/num_clones_table.tsv", format="TSV"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
}
# Plus one Float64 column per sample; the sample set is discovered from the data.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def _subject(df: pl.DataFrame) -> pl.Expr:
    """The clone-definition group. A report without one gets a single group."""
    if "subject_id" in df.columns:
        return pl.col("subject_id").cast(pl.Utf8)
    return pl.lit("all", dtype=pl.Utf8).alias("subject_id")


def _count_ids(col: str) -> pl.Expr:
    """Number of non-empty, comma-separated clone ids in ``col``."""
    return (
        pl.col(col)
        .cast(pl.Utf8)
        .fill_null("")
        .str.split(",")
        .list.eval(pl.element().str.strip_chars().filter(pl.element() != ""))
        .list.len()
        .cast(pl.Float64)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot the pairwise overlaps into a symmetric sample by sample matrix."""
    num_clones = sources["num_clones"]
    samples_df = num_clones.select(pl.col("sample_id").cast(pl.Utf8), _subject(num_clones))
    samples = sorted(samples_df.get_column("sample_id").to_list())

    pairs = sources["overlap"].select(
        pl.col("sampleA").cast(pl.Utf8).alias("row"),
        pl.col("sampleB").cast(pl.Utf8).alias("col"),
        _count_ids("overlap_clone_id").alias("shared"),
    )
    long = pl.concat(
        [
            pairs,
            pairs.select(pl.col("col").alias("row"), pl.col("row").alias("col"), pl.col("shared")),
        ]
    )
    wide = long.pivot(values="shared", index="row", on="col", aggregate_function="max").rename(
        {"row": "sample_id"}
    )
    out = samples_df.join(wide, on="sample_id", how="left")
    for sample in samples:
        if sample not in out.columns:
            out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias(sample))
    out = out.with_columns([pl.col(s).cast(pl.Float64).fill_null(0.0) for s in samples])
    return out.select(["sample_id", "subject_id", *samples]).sort("sample_id")
