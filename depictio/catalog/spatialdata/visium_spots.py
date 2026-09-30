"""The spots of a Visium SpatialData store, on a schema that does not move.

nf-core/spatialvi's stores hold one AnnData table per sample
(``tables/<sample>_table``, see module.yaml). A ``format: spatialdata`` table
DC reads one of them into a frame whose ``sample`` column is the STORE name
(``merged``), with the obs columns, and x / y in the pixels of the image named
by the DC. This recipe:

* takes the sample from the table's ``region`` obs column (the region key,
  equal to the sample id the pipeline gave spatialdata-io), falling back to the
  reader's ``sample`` when a store has no region column;
* keeps a fixed set of QC columns (null when the run did not compute one);
* adds the integrated cluster from the optional integrated store
  (``<method>.zarr``, the same table plus ``clusters_<method>``), joined on the
  spot, so a run with ``--skip_integration`` still loads.

Inputs, both ``format: spatialdata`` table DCs over the same table element,
read with ``coordinates: region`` (the pipeline's obsm["spatial"] is already in
hires pixels, the spot shapes are not)::

    spatialdata_visium_spots_raw        integration/data/merged.zarr
    spatialdata_visium_integrated_raw   integration/data/<method>.zarr (optional)

    dc_specific_properties:
      format: spatialdata
      spatialdata:
        table: tables/<sample>_table
        image: images/<sample>_hires_image
        coordinates: region

Output schema:
    sample : Utf8               sample id (the store's region key)
    spot_id : Utf8              spot id within the sample (instance key)
    spot_uid : Utf8             "<sample>:<spot_id>", unique over the run
    x, y : Float64              spot centre, level-0 pixels of the image
    array_row, array_col : Int64  position on the capture array
    total_counts : Float64      UMIs of the spot (before normalisation)
    n_genes : Int64             genes with at least one count
    pct_counts_mt : Float64     mitochondrial share of the counts, percent
    pct_counts_ribo : Float64   ribosomal share, percent
    pct_counts_hb : Float64     haemoglobin share, percent
    cluster : Utf8              per-sample Leiden cluster, "C<n>"
    cluster_integrated : Utf8   integrated Leiden cluster, "C<n>", else null

Leiden labels are digits; they are written ``C<n>`` so every reader (plots,
colour legends, CSV inference) treats them as categories, not numbers.
    integration_method : Utf8   harmony | scanorama, else null
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "spatialdata_visium_spots_raw"
INTEGRATED_DC_TAG = "spatialdata_visium_integrated_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="spots", dc_ref=RAW_DC_TAG),
    RecipeSource(ref="integrated", dc_ref=INTEGRATED_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "spot_id": pl.Utf8,
    "spot_uid": pl.Utf8,
    "x": pl.Float64,
    "y": pl.Float64,
    "array_row": pl.Int64,
    "array_col": pl.Int64,
    "total_counts": pl.Float64,
    "n_genes": pl.Int64,
    "pct_counts_mt": pl.Float64,
    "pct_counts_ribo": pl.Float64,
    "pct_counts_hb": pl.Float64,
    "cluster": pl.Utf8,
    "cluster_integrated": pl.Utf8,
    "integration_method": pl.Utf8,
}

# output column -> obs candidates, first present wins
_COLUMNS: dict[str, tuple[str, ...]] = {
    "array_row": ("array_row",),
    "array_col": ("array_col",),
    "total_counts": ("total_counts", "n_counts"),
    "n_genes": ("n_genes_by_counts", "n_genes"),
    "pct_counts_mt": ("pct_counts_mt",),
    "pct_counts_ribo": ("pct_counts_ribo",),
    "pct_counts_hb": ("pct_counts_hb",),
    "cluster": ("clusters", "leiden", "cluster"),
}
_SPOT_ID = ("spot_id", "obs_id", "barcode")


def _cluster_label(expr: pl.Expr) -> pl.Expr:
    """A Leiden label as a category: digits become ``C<n>``, other labels are kept."""
    text = expr.cast(pl.Utf8).str.strip_chars()
    return pl.when(text.str.contains(r"^\d+$")).then(pl.lit("C") + text).otherwise(text)


def _pick(df: pl.DataFrame, candidates: tuple[str, ...], dtype: type[pl.DataType]) -> pl.Expr:
    for name in candidates:
        if name in df.columns:
            return pl.col(name).cast(dtype, strict=False)
    return pl.lit(None, dtype=dtype)


def _keyed(df: pl.DataFrame) -> pl.DataFrame:
    """`sample` from the region key and a string spot id, the join key of both stores."""
    sample = (
        pl.coalesce(pl.col("region").cast(pl.Utf8), pl.col("sample").cast(pl.Utf8))
        if "region" in df.columns
        else pl.col("sample").cast(pl.Utf8)
    )
    spot = next((c for c in _SPOT_ID if c in df.columns), None)
    if spot is None:
        raise ValueError(f"visium_spots: the table has none of the spot id columns {_SPOT_ID}")
    return df.with_columns(sample.alias("_sample"), pl.col(spot).cast(pl.Utf8).alias("_spot"))


def _integrated(df: pl.DataFrame | None) -> pl.DataFrame | None:
    if df is None or df.is_empty():
        return None
    cols = [c for c in df.columns if c.startswith("clusters_")]
    if not cols:
        return None
    col = cols[0]
    return _keyed(df).select(
        "_sample",
        "_spot",
        _cluster_label(pl.col(col)).alias("cluster_integrated"),
        pl.lit(col.removeprefix("clusters_")).alias("integration_method"),
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    raw = sources["spots"]
    if raw is None or not {"x", "y"} <= set(raw.columns):
        raise ValueError(
            "visium_spots: the spots table has no x / y; read it with an image and "
            "coordinates: region"
        )
    spots = _keyed(raw)
    result = spots.select(
        pl.col("_sample"),
        pl.col("_spot"),
        pl.col("x").cast(pl.Float64),
        pl.col("y").cast(pl.Float64),
        *[
            _pick(spots, cands, EXPECTED_SCHEMA[name]).alias(name)
            for name, cands in _COLUMNS.items()
        ],
    ).with_columns(_cluster_label(pl.col("cluster")).alias("cluster"))
    integrated = _integrated(sources.get("integrated"))
    if integrated is not None:
        result = result.join(integrated, on=["_sample", "_spot"], how="left")
    else:
        result = result.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("cluster_integrated"),
            pl.lit(None, dtype=pl.Utf8).alias("integration_method"),
        )
    result = result.rename({"_sample": "sample", "_spot": "spot_id"}).with_columns(
        pl.concat_str([pl.col("sample"), pl.col("spot_id")], separator=":").alias("spot_uid")
    )
    return result.select(list(EXPECTED_SCHEMA)).sort(["sample", "spot_id"])
