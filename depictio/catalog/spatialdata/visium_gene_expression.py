"""Expression of a chosen gene list per spot, one row per spot and gene.

Input: ``spatialdata_visium_genes_raw``, a ``format: spatialdata`` table DC over
the same table element as ``spatialdata_visium_spots_raw`` that also pulls the
chosen genes out of X (one column per gene, named by its var name)::

    dc_specific_properties:
      format: spatialdata
      spatialdata:
        table: tables/<sample>_table
        image: images/<sample>_hires_image
        coordinates: region
        genes: ["{GENES}"]

The gene list is the run's to choose (a template variable, never a default
panel). In nf-core/spatialvi's stores X holds log1p(normalised counts) and the
var names are the reference's gene ids (Ensembl ids on a Space Ranger
reference), so the variable lists ids, not symbols.

Which columns are genes: the ``genes`` transform param when given (a comma
list, the same variable), otherwise every numeric column that is not a known
obs, coordinate or QC column.

Output schema:
    sample : Utf8          sample id (the store's region key)
    spot_uid : Utf8        "<sample>:<spot_id>", as in spatialdata/visium_spots
    x, y : Float64         spot centre, level-0 pixels of the image
    cluster : Utf8         per-sample Leiden cluster ("C<n>"), else null
    gene : Utf8            var name of the gene
    expression : Float64   value in X (log1p-normalised in spatialvi)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "spatialdata_visium_genes_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="spots", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "spot_uid": pl.Utf8,
    "x": pl.Float64,
    "y": pl.Float64,
    "cluster": pl.Utf8,
    "gene": pl.Utf8,
    "expression": pl.Float64,
}

# obs columns spatialdata-io and the spatialvi QC / clustering steps write.
_NOT_GENES = {
    "sample",
    "x",
    "y",
    "in_tissue",
    "array_row",
    "array_col",
    "spot_id",
    "obs_id",
    "region",
    "n_genes_by_counts",
    "total_counts",
    "n_counts",
    "n_genes",
    "total_counts_normalized",
}
_NOT_GENE_PREFIXES = ("pct_counts", "total_counts_", "clusters", "log1p_")
_SPOT_ID = ("spot_id", "obs_id", "barcode")


def _gene_columns(df: pl.DataFrame, requested: str | None) -> list[str]:
    if requested:
        wanted = [g.strip() for g in requested.split(",") if g.strip()]
        present = [g for g in wanted if g in df.columns]
        if present:
            return present
    return [
        c
        for c, dtype in df.schema.items()
        if c not in _NOT_GENES and not c.startswith(_NOT_GENE_PREFIXES) and dtype.is_numeric()
    ]


def _cluster_label(expr: pl.Expr) -> pl.Expr:
    """A Leiden label as a category, as spatialdata/visium_spots writes it (``C<n>``)."""
    text = expr.cast(pl.Utf8).str.strip_chars()
    return pl.when(text.str.contains(r"^\d+$")).then(pl.lit("C") + text).otherwise(text)


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    df = sources["spots"]
    if not {"x", "y"} <= set(df.columns):
        raise ValueError("visium_gene_expression: the table has no x / y (read it with an image)")
    spot = next((c for c in _SPOT_ID if c in df.columns), None)
    if spot is None:
        raise ValueError(f"visium_gene_expression: none of the spot id columns {_SPOT_ID}")
    sample = (
        pl.coalesce(pl.col("region").cast(pl.Utf8), pl.col("sample").cast(pl.Utf8))
        if "region" in df.columns
        else pl.col("sample").cast(pl.Utf8)
    )
    cluster = next((c for c in ("clusters", "leiden", "cluster") if c in df.columns), None)
    genes = _gene_columns(df, (params or {}).get("genes"))
    base = df.select(
        sample.alias("sample"),
        pl.col(spot).cast(pl.Utf8).alias("_spot"),
        pl.col("x").cast(pl.Float64),
        pl.col("y").cast(pl.Float64),
        (_cluster_label(pl.col(cluster)) if cluster else pl.lit(None, dtype=pl.Utf8)).alias(
            "cluster"
        ),
        *[pl.col(g).cast(pl.Float64, strict=False) for g in genes],
    ).with_columns(
        pl.concat_str([pl.col("sample"), pl.col("_spot")], separator=":").alias("spot_uid")
    )
    if not genes:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    long = base.unpivot(
        index=["sample", "spot_uid", "x", "y", "cluster"],
        on=genes,
        variable_name="gene",
        value_name="expression",
    )
    return long.select(list(EXPECTED_SCHEMA)).sort(["gene", "sample", "spot_uid"])
