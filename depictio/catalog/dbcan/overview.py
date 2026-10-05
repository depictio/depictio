"""Tidy the run_dbCAN ``overview.tsv`` files into one row per CAZyme gene.

run_dbCAN annotates every predicted protein with three tools (HMMER against
dbCAN HMMs, dbCAN-sub, DIAMOND against CAZy) and writes one overview per
sample with the per-tool families, the number of agreeing tools, its
recommended family and the predicted substrate. The recipe concatenates the
per-sample files, strips the alignment coordinates from the HMM hits
(``GH2(23-690)`` -> ``GH2``), resolves a family for single-tool genes from the
one tool that called it and derives the CAZy class from the family prefix.

The overview carries no sample column, so ``sample`` is read from the
per-sample directory the file sits in (``source_path``), else from the gene id,
which nf-core/funcscan inherits from the assembly contig headers
(``<sample>.<contig>_<orf>`` for MGnify / ENA assemblies). Assemblies whose
contig names do not start with the sample id yield a single pseudo-sample.

Output columns:
    sample, gene_id, contig, hmmer, dbcan_sub, diamond, n_tools, family,
    cazy_class, substrate, ec_number, genes
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="overview",
        glob_pattern="cazyme/dbcan/cazyme_annotation/*/*_overview.tsv",
        format="TSV",
        source_path="source_path",
        read_kwargs={"infer_schema_length": 10000, "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "gene_id": pl.Utf8,
    "contig": pl.Utf8,
    "hmmer": pl.Utf8,
    "dbcan_sub": pl.Utf8,
    "diamond": pl.Utf8,
    "n_tools": pl.Int64,
    "family": pl.Utf8,
    "cazy_class": pl.Utf8,
    "substrate": pl.Utf8,
    "ec_number": pl.Utf8,
    "genes": pl.Int64,
}

_CLASS_NAMES = {
    "GH": "Glycoside hydrolase",
    "GT": "Glycosyltransferase",
    "PL": "Polysaccharide lyase",
    "CE": "Carbohydrate esterase",
    "AA": "Auxiliary activity",
    "CBM": "Carbohydrate-binding module",
}


def _clean(col: pl.Expr) -> pl.Expr:
    """``-`` means no hit; drop alignment coordinates and dbCAN-sub ``_eNN`` ids."""
    return (
        pl.when(col == "-")
        .then(None)
        .otherwise(col.str.replace_all(r"\(\d+-\d+\)", "").str.replace_all(r"_e\d+", ""))
    )


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
    """Normalise the overview and derive family / class per gene."""
    df = sources["overview"].rename(
        {
            "Gene ID": "gene_id",
            "EC#": "ec_number",
            "dbCAN_hmm": "hmmer",
            "dbCAN_sub": "dbcan_sub",
            "DIAMOND": "diamond",
            "#ofTools": "n_tools",
            "Recommend Results": "recommended",
            "Substrate": "substrate",
        },
        strict=False,
    )
    gene_id = pl.col("gene_id").cast(pl.Utf8)
    out = df.select(
        gene_id.alias("gene_id"),
        gene_id.str.replace(r"_\d+$", "").alias("contig"),
        _clean(pl.col("hmmer").cast(pl.Utf8)).alias("hmmer"),
        _clean(pl.col("dbcan_sub").cast(pl.Utf8)).alias("dbcan_sub"),
        _clean(pl.col("diamond").cast(pl.Utf8)).alias("diamond"),
        pl.col("n_tools").cast(pl.Int64, strict=False).alias("n_tools"),
        _clean(pl.col("recommended").cast(pl.Utf8)).alias("recommended"),
        _clean(pl.col("substrate").cast(pl.Utf8)).fill_null("unassigned").alias("substrate"),
        _clean(pl.col("ec_number").cast(pl.Utf8)).alias("ec_number"),
        *([pl.col("source_path")] if "source_path" in df.columns else []),
    )
    # dbCAN recommends a family only when two tools agree; single-tool genes
    # take the family of the one tool that called them (first domain when the
    # hit is a multi-domain ``GH43_10+CBM91`` string).
    family = (
        pl.coalesce(pl.col("recommended"), pl.col("hmmer"), pl.col("dbcan_sub"), pl.col("diamond"))
        .str.split("+")
        .list.first()
    )
    return (
        out.with_columns(family.alias("family"))
        .with_columns(
            pl.col("family").str.extract(r"^([A-Z]+)", 1).alias("class_code"),
        )
        .with_columns(
            pl.col("class_code")
            .replace_strict(_CLASS_NAMES, default=pl.col("class_code"))
            .fill_null("Unclassified")
            .alias("cazy_class"),
            # Sample from the per-sample directory (see _sample).
            _sample(df, pl.col("contig"), "cazyme_annotation").alias("sample"),
            pl.lit(1, dtype=pl.Int64).alias("genes"),
        )
        .sort("sample", "gene_id")
        .select(list(EXPECTED_SCHEMA))
    )
