"""CAZyme gene cluster (CGC) substrate predictions from run_dbCAN.

``run_dbCAN easy_substrate`` predicts the substrate of every CAZyme gene
cluster by homology to dbCAN-PUL and by dbCAN-sub majority vote. The recipe
concatenates the per-sample ``*_substrate_prediction.tsv`` files; the CGC id
is ``<contig>|CGC<n>`` and the sample is read from the per-sample directory, as in
``dbcan/overview.py``.

Output columns:
    sample, cgc_id, contig, pul_id, substrate, bitscore, sub_substrate,
    sub_score, clusters
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="substrates",
        glob_pattern="cazyme/dbcan/substrate/*/*_substrate_prediction.tsv",
        format="TSV",
        source_path="source_path",
        read_kwargs={"infer_schema_length": 10000, "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cgc_id": pl.Utf8,
    "contig": pl.Utf8,
    "pul_id": pl.Utf8,
    "substrate": pl.Utf8,
    "bitscore": pl.Float64,
    "sub_substrate": pl.Utf8,
    "sub_score": pl.Float64,
    "clusters": pl.Int64,
}


def _sample(df: pl.DataFrame, contig: pl.Expr, subdir: str) -> pl.Expr:
    """Sample from the per-sample directory the file sits in, else the contig prefix.

    run_dbCAN writes one ``<subdir>/<sample>/`` directory per sample and no
    sample column; ``source_path`` carries that directory. Rows read without it
    (fixtures) fall back to the ``<sample>.<contig>`` prefix of MGnify / ENA
    assemblies, then to a single ``run`` pseudo-sample.
    """
    from_prefix = (
        pl.when(contig.str.contains(r"^[^.]+\..+"))
        .then(contig.str.extract(r"^([^.]+)\.", 1))
        .otherwise(pl.lit("run"))
    )
    if "source_path" not in df.columns:
        return from_prefix
    from_path = pl.col("source_path").str.extract(rf"{subdir}/([^/]+)/[^/]+$", 1)
    return pl.coalesce(from_path, from_prefix)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename the dbCAN substrate columns and split the CGC id."""
    df = sources["substrates"]

    def _col(name: str, dtype: type[pl.DataType]) -> pl.Expr:
        if name in df.columns:
            return pl.col(name).cast(dtype, strict=False)
        return pl.lit(None).cast(dtype)

    cgc = _col("#cgcid", pl.Utf8)
    contig = cgc.str.split("|").list.first()
    return (
        df.select(
            _sample(df, contig, "substrate").alias("sample"),
            cgc.alias("cgc_id"),
            contig.alias("contig"),
            _col("PULID", pl.Utf8).alias("pul_id"),
            _col("dbCAN-PUL substrate", pl.Utf8).fill_null("unassigned").alias("substrate"),
            _col("bitscore", pl.Float64).alias("bitscore"),
            _col("dbCAN-sub substrate", pl.Utf8).alias("sub_substrate"),
            _col("dbCAN-sub substrate score", pl.Float64).alias("sub_score"),
            pl.lit(1, dtype=pl.Int64).alias("clusters"),
        )
        .sort("sample", "cgc_id")
        .select(list(EXPECTED_SCHEMA))
    )
