"""AMP sequence clusters from the AMPcombi ``cluster`` representative table.

``ampcombi cluster`` groups the AMP candidates of the whole run with MMseqs2
and writes one row per cluster with its representative sequence header and
member count. The header is ``<sample>!<CDS id>``, so the sample that
contributed the representative is split out for filtering.

Output columns:
    cluster_id, representative, sample, members
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="representatives",
        path="reports/ampcombi2/Ampcombi_summary_cluster_representative_seq.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "cluster_id": pl.Int64,
    "representative": pl.Utf8,
    "sample": pl.Utf8,
    "members": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename the representative table and split the sample off the header."""
    df = sources["representatives"]
    header = pl.col("seq_headers").cast(pl.Utf8)
    return (
        df.select(
            pl.col("index").cast(pl.Int64, strict=False).alias("cluster_id"),
            header.alias("representative"),
            pl.when(header.str.contains("!"))
            .then(header.str.split("!").list.first())
            .otherwise(header)
            .alias("sample"),
            pl.col("total_cluster_members").cast(pl.Int64, strict=False).alias("members"),
        )
        .sort("members", "cluster_id", descending=[True, False])
        .select(list(EXPECTED_SCHEMA))
    )
