"""PCA embedding of AMP candidates over their physicochemical properties.

Each point is one AMP candidate from the AMPcombi summary, placed by a
principal-component analysis of molecular weight, isoelectric point,
hydrophobicity and the helix / turn / sheet secondary-structure fractions
(standardised before the decomposition). The sample and tool probabilities
ride along so the embedding can be coloured by either.

Output columns:
    cds_id, dim_1, dim_2, sample, prob_ampir, prob_macrel, prob_max,
    charge_class, aa_length
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.dimreduction import run_pca

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="reports/ampcombi2/Ampcombi_summary.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA", ""], "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "cds_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "sample": pl.Utf8,
    "prob_ampir": pl.Float64,
    "prob_macrel": pl.Float64,
    "prob_max": pl.Float64,
    "charge_class": pl.Utf8,
    "aa_length": pl.Int64,
}

_FEATURES = (
    "molecular_weight",
    "isoelectric_point",
    "hydrophobicity",
    "helix_fraction",
    "turn_fraction",
    "sheet_fraction",
)
_PROB_COLS = ("prob_ampir", "prob_macrel", "prob_amplify")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Standardised PCA on the physicochemical descriptors, two components."""
    df = sources["summary"]

    def _col(name: str, dtype: type[pl.DataType]) -> pl.Expr:
        if name in df.columns:
            return pl.col(name).cast(dtype, strict=False)
        return pl.lit(None).cast(dtype)

    # Each AMP candidate id must be unique across samples: AMPcombi keys the
    # CDS by contig ORF, which repeats across assemblies, so prefix it.
    base = df.select(
        (pl.col("sample_id").cast(pl.Utf8) + "!" + pl.col("CDS_id").cast(pl.Utf8)).alias("cds_id"),
        pl.col("sample_id").cast(pl.Utf8).alias("sample"),
        *[_col(c, pl.Float64).alias(c) for c in _FEATURES],
        *[_col(c, pl.Float64).alias(c) for c in _PROB_COLS],
        _col("aa_sequence", pl.Utf8).str.len_chars().cast(pl.Int64).alias("aa_length"),
    ).drop_nulls(list(_FEATURES))

    coords = run_pca(base.select("cds_id", *_FEATURES), n_components=2, scale=True)
    coords = coords.rename({"sample_id": "cds_id"}).select("cds_id", "dim_1", "dim_2")

    meta = base.select(
        "cds_id",
        "sample",
        "prob_ampir",
        "prob_macrel",
        pl.max_horizontal(*_PROB_COLS).alias("prob_max"),
        pl.when(pl.col("isoelectric_point") >= 8.0)
        .then(pl.lit("basic"))
        .when(pl.col("isoelectric_point") <= 6.0)
        .then(pl.lit("acidic"))
        .otherwise(pl.lit("neutral"))
        .alias("charge_class"),
        "aa_length",
    )
    return coords.join(meta, on="cds_id", how="inner").select(list(EXPECTED_SCHEMA))
