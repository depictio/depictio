"""Per-reconstructed-feature SIDLE reconstruction confidence.

``reconstruction_summary/metadata.tsv`` reports, for each reconstructed
feature, how many of the amplified regions mapped to it and how much kmer
support stood behind them — the two numbers that say whether a cross-region
feature is real or an artefact of one region. It is a QIIME 2 metadata export,
so its second row is a ``#q2:types`` type-declaration line that has to go
before anything is cast.

Output schema:
    feature_id : Utf8                 reconstructed feature
    num_regions : Int64               amplified regions that mapped to it
    total_kmers_mapped : Int64        kmer support summed over those regions
    mean_kmer_per_region : Float64    mean support per mapped region
    stdv_kmer_per_region : Float64    spread of that support
    mapped_asvs : Utf8                the per-region ASVs behind the feature
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="qc",
        path="sidle/DB/3_reconstructed/reconstruction_summary/metadata.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "num_regions": pl.Int64,
    "total_kmers_mapped": pl.Int64,
    "mean_kmer_per_region": pl.Float64,
    "stdv_kmer_per_region": pl.Float64,
    "mapped_asvs": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Drop the #q2:types declaration row, rename to snake_case, cast numerics."""
    rename_map = {
        "feature-id": "feature_id",
        "num-regions": "num_regions",
        "total-kmers-mapped": "total_kmers_mapped",
        "mean-kmer-per-region": "mean_kmer_per_region",
        "stdv-kmer-per-region": "stdv_kmer_per_region",
        "mapped-asvs": "mapped_asvs",
    }
    df = sources["qc"].rename({k: v for k, v in rename_map.items() if k in sources["qc"].columns})
    df = df.filter(pl.col("feature_id") != "#q2:types")
    df = df.with_columns(
        pl.col("num_regions").cast(pl.Int64, strict=False),
        pl.col("total_kmers_mapped").cast(pl.Int64, strict=False),
        pl.col("mean_kmer_per_region").cast(pl.Float64, strict=False),
        pl.col("stdv_kmer_per_region").cast(pl.Float64, strict=False),
    )
    return df.select(list(EXPECTED_SCHEMA.keys()))
