"""Space Ranger's capture spots, one row per spot of every sample.

``outs/spatial/tissue_positions.csv`` lists every spot of the slide's capture
area (about 5 000 on a 6.5 mm area, 14 000 on an 11 mm one) with its in-tissue
call, its row and column on the capture array and its centre in the pixels of
the full-resolution image Space Ranger was given. There is no sample column:
one file per sample, so the sample comes from the path (``<sample>/spaceranger/
outs/spatial/``)::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*/spaceranger/outs/spatial/tissue_positions\\.csv$'}
      dc_specific_properties:
        format: CSV
        polars_kwargs:
          include_file_paths: source_path

Space Ranger 1.x wrote a header-less ``tissue_positions_list.csv`` instead;
that layout is not read here.

The pixel columns are full-resolution: multiply by ``tissue_hires_scalef`` /
``tissue_lowres_scalef`` (``scalefactors_json.json``) to place a spot on the
downscaled PNGs. For the image the bioimage viewer shows, use the spots table
of the SpatialData store instead, whose x / y are already in its pixels.

Output schema:
    sample : Utf8              sample the spot belongs to
    barcode : Utf8             spot barcode
    spot_uid : Utf8            "<sample>:<barcode>", unique over the run
    in_tissue : Int64          1 under tissue, 0 outside
    under_tissue : Int64       same as in_tissue (a column a sum card reads)
    tissue_call : Utf8         "under tissue" | "outside tissue"
    array_row, array_col : Int64         position on the capture array
    pxl_row_fullres, pxl_col_fullres : Float64   centre, full-resolution pixels
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "spaceranger_tissue_positions_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="positions", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "barcode": pl.Utf8,
    "spot_uid": pl.Utf8,
    "in_tissue": pl.Int64,
    "under_tissue": pl.Int64,
    "tissue_call": pl.Utf8,
    "array_row": pl.Int64,
    "array_col": pl.Int64,
    "pxl_row_fullres": pl.Float64,
    "pxl_col_fullres": pl.Float64,
}

_REQUIRED = (
    "barcode",
    "in_tissue",
    "array_row",
    "array_col",
    "pxl_row_in_fullres",
    "pxl_col_in_fullres",
)
_SAMPLE_RE = r"(?:^|/)([^/]+)/spaceranger/outs/spatial/tissue_positions\.csv$"
_FALLBACK_SAMPLE_RE = r"(?:^|/)([^/]+)/outs/spatial/tissue_positions\.csv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["positions"]
    missing = [c for c in (*_REQUIRED, "source_path") if c not in df.columns]
    if missing:
        raise ValueError(
            f"spaceranger_tissue_positions: input lacks {missing} (a Space Ranger 2+ "
            "tissue_positions.csv scanned with include_file_paths: source_path)"
        )
    path = pl.col("source_path").cast(pl.Utf8).str.replace_all(r"\\", "/")
    in_tissue = pl.col("in_tissue").cast(pl.Int64, strict=False)
    result = df.select(
        pl.coalesce(
            path.str.extract(_SAMPLE_RE, 1), path.str.extract(_FALLBACK_SAMPLE_RE, 1)
        ).alias("sample"),
        pl.col("barcode").cast(pl.Utf8),
        in_tissue.alias("in_tissue"),
        in_tissue.alias("under_tissue"),
        pl.when(in_tissue == 1)
        .then(pl.lit("under tissue"))
        .otherwise(pl.lit("outside tissue"))
        .alias("tissue_call"),
        pl.col("array_row").cast(pl.Int64, strict=False),
        pl.col("array_col").cast(pl.Int64, strict=False),
        pl.col("pxl_row_in_fullres").cast(pl.Float64, strict=False).alias("pxl_row_fullres"),
        pl.col("pxl_col_in_fullres").cast(pl.Float64, strict=False).alias("pxl_col_fullres"),
    )
    if result.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            "spaceranger_tissue_positions: a row's source_path does not look like "
            "'<sample>/spaceranger/outs/spatial/tissue_positions.csv'"
        )
    result = result.with_columns(
        pl.concat_str([pl.col("sample"), pl.col("barcode")], separator=":").alias("spot_uid")
    )
    return result.select(list(EXPECTED_SCHEMA)).sort(["sample", "array_row", "array_col"])
