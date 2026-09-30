"""Cells segmented per well, laid out as the plate: one row per plate row.

The plate-map view every screening lab reads first: a grid with the plate's
rows down and its columns across, each cell the number of cells segmented in
that well. Edge effects, a dispensing error along one column, an empty or
overgrown row show up as a pattern on the grid long before they show up in a
profile. The table is a complex_heatmap matrix: ``plate_row`` names each row,
and one Float64 column per plate column (``col_01``, ``col_02``, ...) holds the
counts; wells that were not imaged are null, so they read as gaps rather than
as zero cells.

Only the plate columns the run imaged are emitted (a run of a few wells yields
a small grid, a full plate a 16 x 24 one), and with several plates each plate
contributes its own rows, prefixed with its barcode.

Source: the ``cp-wells`` per-well table (``cytotable/well_profile.py``).

Output schema:
    plate_row : Utf8        ``<plate> <row>``, the heatmap row label
    plate : Utf8            plate barcode
    row : Utf8              plate row letter(s)
    col_<NN> : Float64      cells segmented in well ``<row><NN>``, null when not imaged
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

WELLS_DC_TAG = "cp-wells"

SOURCES: list[RecipeSource] = [RecipeSource(ref="wells", dc_ref=WELLS_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "plate_row": pl.Utf8,
    "plate": pl.Utf8,
    "row": pl.Utf8,
}


def _row_order(row: str) -> tuple[int, str]:
    """Plate rows sort A..Z then AA..AF (1536-well plates), not lexically."""
    return (len(row), row)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    wells = sources["wells"].select("plate", "row", "column", "n_cells")
    wells = wells.with_columns(
        pl.format("col_{}", pl.col("column").cast(pl.Utf8).str.zfill(2)).alias("plate_column")
    )
    columns = [f"col_{c:02d}" for c in sorted(wells["column"].drop_nulls().unique().to_list())]
    grid = wells.pivot(
        on="plate_column", index=["plate", "row"], values="n_cells", aggregate_function="sum"
    )
    for name in columns:
        if name not in grid.columns:
            grid = grid.with_columns(pl.lit(None, dtype=pl.Float64).alias(name))
    rows = sorted(grid.select("plate", "row").iter_rows(), key=lambda r: (r[0], _row_order(r[1])))
    order = pl.DataFrame(
        {"plate": [r[0] for r in rows], "row": [r[1] for r in rows], "_order": range(len(rows))},
        schema={"plate": pl.Utf8, "row": pl.Utf8, "_order": pl.Int64},
    )
    grid = grid.join(order, on=["plate", "row"], how="left").sort("_order")
    return grid.select(
        (pl.col("plate") + " " + pl.col("row")).alias("plate_row"),
        pl.col("plate").cast(pl.Utf8),
        pl.col("row").cast(pl.Utf8),
        *[pl.col(name).cast(pl.Float64) for name in columns],
    )
