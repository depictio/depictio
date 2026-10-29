"""One row per sample and gene across the three DROP analyses: the triage list.

OUTRIDER, FRASER and the allelic test each judge a different thing about a gene, and a
diagnosis rests on the genes where more than one agrees: an under-expressed gene that
is also spliced abnormally, or silenced on one allele. The three call tables are laid
out per analysis, so this recipe joins them on the sample and the gene symbol and
ranks each sample's genes by how many analyses call them and how strong the evidence is.

A gene enters a sample's list when at least one analysis calls it (the ``significant``
or ``mono_allelic`` flag of that analysis, so the dashboard's thresholds apply), or when
it is among the sample's ``top_n`` best-ranked genes. The second rule keeps the list
readable on a run where nothing passes the cut-offs: the strongest evidence is still
ranked, and the ``support`` column says "not called" for it. A run too small for any
adjusted p-value to pass the cut-offs (a test set of ten samples) calls nothing, and the
list is then each sample's ``top_n`` genes by raw p-value (``significance``, the summed
-log10 p-value of the analyses); ``n_nominal`` counts the analyses whose raw p-value is
at nominal significance, so a reader sees which of those leads have any evidence at all.

Where a gene sits: the gene's span when the run published its gene table (expression
calls), else the splicing junction, else the variant. Rows without any position stay in
the table and leave the genome views.

A gene is one symbol. Rows FRASER leaves unannotated and variants outside a gene carry
no symbol to join on, so they are not part of this list; they stay in their own tab.

Sources:
    samples      the sample hub (the group of each sample)
    expression   OUTRIDER calls (optional)
    splicing     FRASER calls (optional)
    mae          mono-allelic expression variants (optional)

Params:
    top_n      best-ranked genes kept per sample besides the called ones (default 25)
    nominal_p  raw p-value at or below which an analysis is a nominal hit for the gene,
               counted in ``n_nominal`` (default 0.05)

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={"sample": pl.Utf8, "drop_group": pl.Utf8},
    ),
    RecipeSource(
        ref="expression",
        dc_ref="expression_outliers",
        optional=True,
        input_schema={
            "sample": pl.Utf8,
            "gene_id": pl.Utf8,
            "gene_name": pl.Utf8,
            "z_score": pl.Float64,
            "abs_z_score": pl.Float64,
            "l2fc": pl.Float64,
            "p_value": pl.Float64,
            "padj": pl.Float64,
            "significant": pl.Boolean,
            "nominal": pl.Boolean,
            "hpo_match": pl.Boolean,
            "chrom": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
        },
    ),
    RecipeSource(
        ref="splicing",
        dc_ref="splicing_outliers",
        optional=True,
        input_schema={
            "sample": pl.Utf8,
            "gene_name": pl.Utf8,
            "delta_psi": pl.Float64,
            "abs_delta_psi": pl.Float64,
            "p_value": pl.Float64,
            "padj_gene": pl.Float64,
            "significant": pl.Boolean,
            "nominal": pl.Boolean,
            "hpo_match": pl.Boolean,
            "chrom": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
        },
    ),
    RecipeSource(
        ref="mae",
        dc_ref="mae_variants",
        optional=True,
        input_schema={
            "sample": pl.Utf8,
            "gene_name": pl.Utf8,
            "alt_ratio": pl.Float64,
            "p_value": pl.Float64,
            "padj": pl.Float64,
            "mono_allelic": pl.Boolean,
            "chrom": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "call_id": pl.Utf8,
    "sample": pl.Utf8,
    "drop_group": pl.Utf8,
    "gene_name": pl.Utf8,
    "expression_outlier": pl.Boolean,
    "splicing_outlier": pl.Boolean,
    "mae_outlier": pl.Boolean,
    "n_analyses": pl.Int64,
    "n_nominal": pl.Int64,
    "support": pl.Utf8,
    "called_in": pl.Utf8,
    "phenotype_gene": pl.Boolean,
    "phenotype": pl.Utf8,
    "significance": pl.Float64,
    "sample_rank": pl.Int64,
    "expression_score": pl.Float64,
    "splicing_score": pl.Float64,
    "mae_score": pl.Float64,
    "z_score": pl.Float64,
    "l2fc": pl.Float64,
    "expression_padj": pl.Float64,
    "delta_psi": pl.Float64,
    "splicing_padj": pl.Float64,
    "alt_ratio": pl.Float64,
    "mae_padj": pl.Float64,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "locus": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
}

DEFAULT_TOP_N = 25
#: Raw p-value at or below which an analysis counts as a nominal hit for the gene.
DEFAULT_NOMINAL_P = 0.05
_MAX_LOG = 300.0
_KEY = ["sample", "gene_name"]
# FRASER and the MAE table write these where a row has no gene symbol.
_NO_GENE = ["unannotated", "intergenic"]


def _score(p: pl.Expr) -> pl.Expr:
    """-log10 of a p-value (a value of 0 is capped); null stays null."""
    return p.clip(1e-300, 1.0).log10().abs().clip(0.0, _MAX_LOG)


def _usable(df: pl.DataFrame | None) -> pl.DataFrame | None:
    """The analysis table with a gene symbol, or None when the analysis did not run."""
    if df is None or df.is_empty():
        return None
    return df.filter(pl.col("gene_name").is_not_null() & ~pl.col("gene_name").is_in(_NO_GENE))


def _expression(df: pl.DataFrame) -> pl.DataFrame:
    """One row per sample and gene: its called OUTRIDER row, else its most significant one."""
    return (
        df.sort(
            ["significant", "p_value", "abs_z_score"],
            descending=[True, False, True],
            nulls_last=True,
        )
        .group_by(_KEY, maintain_order=True)
        .agg(
            pl.col("gene_id").first().alias("gene_id"),
            pl.col("significant").first().alias("expression_outlier"),
            pl.col("nominal").first().alias("_ae_nominal"),
            pl.col("hpo_match").any().alias("_ae_hpo"),
            _score(pl.col("p_value").first()).alias("expression_score"),
            pl.col("z_score").first().alias("z_score"),
            pl.col("l2fc").first().alias("l2fc"),
            pl.col("padj").first().alias("expression_padj"),
            pl.col("chrom").first().alias("_ae_chrom"),
            pl.col("start").first().alias("_ae_start"),
            pl.col("end").first().alias("_ae_end"),
        )
    )


def _splicing(df: pl.DataFrame) -> pl.DataFrame:
    """One row per sample and gene: its called junction, else its most significant one."""
    return (
        df.sort(
            ["significant", "p_value", "abs_delta_psi"],
            descending=[True, False, True],
            nulls_last=True,
        )
        .group_by(_KEY, maintain_order=True)
        .agg(
            pl.col("significant").first().alias("splicing_outlier"),
            pl.col("nominal").first().alias("_as_nominal"),
            pl.col("hpo_match").any().alias("_as_hpo"),
            _score(pl.col("p_value").first()).alias("splicing_score"),
            pl.col("delta_psi").first().alias("delta_psi"),
            pl.col("padj_gene").first().alias("splicing_padj"),
            pl.col("chrom").first().alias("_as_chrom"),
            pl.col("start").first().alias("_as_start"),
            pl.col("end").first().alias("_as_end"),
        )
    )


def _mae(df: pl.DataFrame, nominal_p: float = DEFAULT_NOMINAL_P) -> pl.DataFrame:
    """One row per sample and gene: its mono-allelic variant, else its most unbalanced one."""
    return (
        df.sort(["mono_allelic", "p_value"], descending=[True, False], nulls_last=True)
        .group_by(_KEY, maintain_order=True)
        .agg(
            pl.col("mono_allelic").first().alias("mae_outlier"),
            (pl.col("mono_allelic").first() | (pl.col("p_value").first() <= nominal_p)).alias(
                "_mae_nominal"
            ),
            _score(pl.col("p_value").first()).alias("mae_score"),
            pl.col("alt_ratio").first().alias("alt_ratio"),
            pl.col("padj").first().alias("mae_padj"),
            pl.col("chrom").first().alias("_mae_chrom"),
            pl.col("start").first().alias("_mae_start"),
            pl.col("end").first().alias("_mae_end"),
        )
    )


# Every column an analysis contributes, so one that did not run still has them (null).
_PART_COLUMNS: dict[str, dict[str, type[pl.DataType]]] = {
    "expression": {
        "gene_id": pl.Utf8,
        "expression_outlier": pl.Boolean,
        "_ae_hpo": pl.Boolean,
        "_ae_nominal": pl.Boolean,
        "expression_score": pl.Float64,
        "z_score": pl.Float64,
        "l2fc": pl.Float64,
        "expression_padj": pl.Float64,
        "_ae_chrom": pl.Utf8,
        "_ae_start": pl.Int64,
        "_ae_end": pl.Int64,
    },
    "splicing": {
        "splicing_outlier": pl.Boolean,
        "_as_hpo": pl.Boolean,
        "_as_nominal": pl.Boolean,
        "splicing_score": pl.Float64,
        "delta_psi": pl.Float64,
        "splicing_padj": pl.Float64,
        "_as_chrom": pl.Utf8,
        "_as_start": pl.Int64,
        "_as_end": pl.Int64,
    },
    "mae": {
        "mae_outlier": pl.Boolean,
        "_mae_nominal": pl.Boolean,
        "mae_score": pl.Float64,
        "alt_ratio": pl.Float64,
        "mae_padj": pl.Float64,
        "_mae_chrom": pl.Utf8,
        "_mae_start": pl.Int64,
        "_mae_end": pl.Int64,
    },
}


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Join the analyses on sample and gene, rank each sample's genes, keep the shortlist."""
    p = params or {}
    top_n = int(p.get("top_n") or DEFAULT_TOP_N)
    nominal_p = float(p.get("nominal_p") or DEFAULT_NOMINAL_P)

    tables = {
        "expression": _usable(sources.get("expression")),
        "splicing": _usable(sources.get("splicing")),
        "mae": _usable(sources.get("mae")),
    }
    builders = {
        "expression": _expression,
        "splicing": _splicing,
        "mae": lambda table: _mae(table, nominal_p),
    }
    parts = {name: builders[name](table) for name, table in tables.items() if table is not None}
    if not parts:
        return pl.DataFrame(schema={**OUTPUT_SCHEMA, **OPTIONAL_OUTPUT_SCHEMA})

    joined = pl.concat([part.select(_KEY) for part in parts.values()]).unique(maintain_order=True)
    for name, columns in _PART_COLUMNS.items():
        if name in parts:
            joined = joined.join(parts[name], on=_KEY, how="left")
        else:
            joined = joined.with_columns(
                *[pl.lit(None, dtype=dtype).alias(col) for col, dtype in columns.items()]
            )

    hub = sources["samples"].select("sample", "drop_group").unique(subset="sample", keep="first")
    joined = joined.join(hub, on="sample", how="left")

    flags = ["expression_outlier", "splicing_outlier", "mae_outlier"]
    out = joined.with_columns(*[pl.col(f).fill_null(False) for f in flags])
    out = out.with_columns(
        pl.sum_horizontal(*[pl.col(f).cast(pl.Int64) for f in flags]).alias("n_analyses"),
        pl.sum_horizontal(
            *[
                pl.col(f).fill_null(False).cast(pl.Int64)
                for f in ("_ae_nominal", "_as_nominal", "_mae_nominal")
            ]
        ).alias("n_nominal"),
        (pl.col("_ae_hpo").fill_null(False) | pl.col("_as_hpo").fill_null(False)).alias(
            "phenotype_gene"
        ),
        pl.sum_horizontal(
            pl.col("expression_score").fill_null(0.0),
            pl.col("splicing_score").fill_null(0.0),
            pl.col("mae_score").fill_null(0.0),
        ).alias("significance"),
        pl.coalesce("_ae_chrom", "_as_chrom", "_mae_chrom").alias("chrom"),
        pl.coalesce("_ae_start", "_as_start", "_mae_start").cast(pl.Int64).alias("start"),
        pl.coalesce("_ae_end", "_as_end", "_mae_end").cast(pl.Int64).alias("end"),
    )
    # Rank within the sample: the genes most analyses call first, then the strongest evidence.
    out = out.sort(
        ["sample", "n_analyses", "significance", "gene_name"],
        descending=[False, True, True, False],
    ).with_columns((pl.int_range(pl.len()).over("sample") + 1).cast(pl.Int64).alias("sample_rank"))
    out = out.filter((pl.col("n_analyses") >= 1) | (pl.col("sample_rank") <= top_n))

    names = pl.concat_list(
        pl.when(pl.col("expression_outlier")).then(pl.lit("Expression")),
        pl.when(pl.col("splicing_outlier")).then(pl.lit("Splicing")),
        pl.when(pl.col("mae_outlier")).then(pl.lit("Mono-allelic")),
    )
    end = pl.col("end").fill_null(pl.col("start"))
    out = out.with_columns(
        pl.when(pl.col("n_analyses") == 0)
        .then(pl.lit("not called"))
        .when(pl.col("n_analyses") == 1)
        .then(pl.lit("1 analysis"))
        .otherwise(pl.col("n_analyses").cast(pl.Utf8) + pl.lit(" analyses"))
        .alias("support"),
        pl.when(pl.col("n_analyses") == 0)
        .then(pl.lit("none"))
        .otherwise(names.list.drop_nulls().list.join(" + "))
        .alias("called_in"),
        pl.when(pl.col("phenotype_gene"))
        .then(pl.lit("Phenotype match"))
        .otherwise(pl.lit("No match"))
        .alias("phenotype"),
        (pl.col("sample") + pl.lit(":") + pl.col("gene_name")).alias("call_id"),
        pl.when(pl.col("chrom").is_not_null() & pl.col("start").is_not_null())
        .then(
            pl.col("chrom")
            + pl.lit(":")
            + pl.col("start").cast(pl.Utf8)
            + pl.lit("-")
            + end.cast(pl.Utf8)
        )
        .otherwise(None)
        .alias("locus"),
        end.alias("end"),
    )
    columns = list(OUTPUT_SCHEMA) + list(OPTIONAL_OUTPUT_SCHEMA)
    return out.select(columns).sort(["sample", "sample_rank"])
