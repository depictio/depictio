"""One row per imaging site: how many cells were segmented and how they look.

The site (field of view) is the unit CellProfiler runs on, so it is where a
segmentation or acquisition problem shows first: a site out of focus, at the
plate edge or on a bubble yields few cells, or cells whose nuclei are abnormally
small or dim. This recipe rolls the single-cell table up to one row per site so
those sites can be spotted, filtered and read in a record card.

Every value is a count or a median over the site's cells, never a mean, so one
mis-segmented giant object does not move the site.

Source: the ``cp-cells`` single-cell table (``cytotable/single_cell.py``).

Output schema:
    site_id : Utf8                   ``<plate>_<well>_s<site>``
    well_id : Utf8                   ``<plate>_<well>``
    plate : Utf8                     plate barcode
    well : Utf8                      well
    site : Int64                     imaging site within the well
    n_cells : Int64                  cells segmented on the site
    median_cell_area : Float64       median cell area, pixels
    median_nucleus_area : Float64    median nucleus area, pixels
    median_nucleus_dna : Float64     median integrated nuclear DNA intensity
    median_neighbors : Float64       median number of adjacent cells
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

CELLS_DC_TAG = "cp-cells"

SOURCES: list[RecipeSource] = [RecipeSource(ref="cells", dc_ref=CELLS_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "site_id": pl.Utf8,
    "well_id": pl.Utf8,
    "plate": pl.Utf8,
    "well": pl.Utf8,
    "site": pl.Int64,
    "n_cells": pl.Int64,
    "median_cell_area": pl.Float64,
    "median_nucleus_area": pl.Float64,
    "median_nucleus_dna": pl.Float64,
    "median_neighbors": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    cells = sources["cells"]
    out = cells.group_by(["site_id", "well_id", "plate", "well", "site"]).agg(
        pl.len().cast(pl.Int64).alias("n_cells"),
        pl.col("cell_area").median().alias("median_cell_area"),
        pl.col("nucleus_area").median().alias("median_nucleus_area"),
        pl.col("nucleus_dna_integrated").median().alias("median_nucleus_dna"),
        pl.col("cell_neighbors").median().alias("median_neighbors"),
    )
    return out.select([pl.col(name).cast(dtype) for name, dtype in EXPECTED_SCHEMA.items()]).sort(
        ["plate", "well", "site"]
    )
