"""Sample by V gene usage matrix (sequence fractions) for a clustered heatmap.

Pivots ``repertoire_comparison/V_family/V_gene_distribution_by_sequence_data.tsv``
(airrflow's repertoire comparison report, alakazam ``countGenes`` at gene
resolution) so each row is a sample and each column a V gene holding the
fraction of that sample's sequences using it; genes a sample never used are 0.

Samples as rows rather than genes keeps the matrix wide even for a small run (a
clustered heatmap needs several numeric columns to cluster on) and lets
``subject_id`` ride along as a row annotation.

``row_id`` is the heatmap index: the sample id when the run has a single locus,
``<sample> (<locus>)`` when a sample carries several.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="v_gene",
        path="repertoire_comparison/V_family/V_gene_distribution_by_sequence_data.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "row_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "locus": pl.Utf8,
}
# Plus one Float64 column per V gene; the gene set is discovered from the data.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def _subject(df: pl.DataFrame) -> pl.Expr:
    """The clone-definition group. A report without one gets a single group."""
    if "subject_id" in df.columns:
        return pl.col("subject_id").cast(pl.Utf8)
    return pl.lit("all", dtype=pl.Utf8).alias("subject_id")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot V gene usage to a wide sample by gene fraction matrix."""
    df = sources["v_gene"]
    df = df.select(
        pl.col("sample_id").cast(pl.Utf8),
        _subject(df),
        pl.col("locus").cast(pl.Utf8),
        pl.col("gene").cast(pl.Utf8),
        pl.col("seq_freq").cast(pl.Float64),
    )
    multi_locus = df.get_column("locus").n_unique() > 1
    row_id = (
        pl.concat_str([pl.col("sample_id"), pl.lit(" ("), pl.col("locus"), pl.lit(")")])
        if multi_locus
        else pl.col("sample_id")
    )
    df = df.with_columns(row_id.cast(pl.Utf8).alias("row_id"))

    index = ["row_id", "sample_id", "subject_id", "locus"]
    genes = sorted(df.get_column("gene").unique().to_list())
    wide = df.pivot(values="seq_freq", index=index, on="gene", aggregate_function="sum")
    wide = wide.with_columns([pl.col(g).cast(pl.Float64).fill_null(0.0) for g in genes])
    return wide.select([*index, *genes]).sort("row_id")
