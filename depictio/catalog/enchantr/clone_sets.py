"""Clone by sample presence matrix (0/1) for an UpSet plot of shared clones.

Every clone of enchantR's ``clone_sizes_table.tsv`` becomes one row, keyed as
``<subject_id>:<clone_id>`` because airrflow defines clones within a subject
(the same clone number under two subjects is two different clones). One Int8
column per sample marks whether the clone was seen there, so the UpSet
intersections read as "clones shared by exactly these samples".

``n_samples`` (how many samples the clone appears in) and ``total_sequences``
(its size summed across them) ride along so the plot can be narrowed to the
shared clones, which are the interesting ones.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="clone_sizes",
        path=(
            "clonal_analysis/repertoire_analysis/repertoire_analysis_report/tables/"
            "clone_sizes_table.tsv"
        ),
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "clone": pl.Utf8,
    "subject_id": pl.Utf8,
    "n_samples": pl.Int64,
    "total_sequences": pl.Int64,
}
# Plus one Int8 set column per sample; the sample set is discovered from the data.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot clone membership to a binary clone by sample matrix."""
    df = sources["clone_sizes"].with_columns(
        pl.col("sample_id").cast(pl.Utf8),
        pl.col("clone_id").cast(pl.Utf8),
        pl.col("seq_count").cast(pl.Int64),
    )
    if "subject_id" in df.columns:
        df = df.with_columns(pl.col("subject_id").cast(pl.Utf8))
    else:
        df = df.with_columns(pl.lit("all", dtype=pl.Utf8).alias("subject_id"))
    df = df.with_columns(
        pl.concat_str([pl.col("subject_id"), pl.lit(":"), pl.col("clone_id")]).alias("clone")
    )

    samples = sorted(df.get_column("sample_id").unique().to_list())
    wide = (
        df.with_columns(pl.lit(1, dtype=pl.Int8).alias("present"))
        .pivot(
            values="present",
            index=["clone", "subject_id"],
            on="sample_id",
            aggregate_function="max",
        )
        .with_columns([pl.col(s).fill_null(0).cast(pl.Int8) for s in samples])
    )
    totals = df.group_by("clone").agg(
        pl.col("sample_id").n_unique().cast(pl.Int64).alias("n_samples"),
        pl.col("seq_count").sum().cast(pl.Int64).alias("total_sequences"),
    )
    return (
        wide.join(totals, on="clone", how="left")
        .select(["clone", "subject_id", "n_samples", "total_sequences", *samples])
        .sort(["n_samples", "total_sequences"], descending=True)
    )
