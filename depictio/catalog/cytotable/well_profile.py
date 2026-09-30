"""One row per well: its cell count and median morphological profile.

The well is the unit a Cell Painting screen treats: one perturbation per well,
several sites per well, hundreds of cells per site. Image-based profiling
aggregates the single cells of a well to its median profile (the pycytominer
``aggregate`` step) before comparing perturbations, because the median is
robust to the mis-segmented objects every site carries. This recipe does the
same over the curated features of the single-cell table, and adds two things a
dashboard needs next to it:

* ``z_<feature>``: each median profile feature as a robust z-score across the
  run's wells, ``(value - median) / (1.4826 * MAD)``, so features with very
  different units (areas in pixels, correlations in -1..1) share one colour
  scale on the well x feature heatmap. It is standardised against every well of
  the run, not against negative-control wells: which wells are controls is
  design metadata the plate map carries, and the per-group comparison is on the
  Perturbations tab. A feature with no spread across wells (MAD of 0) falls
  back to the standard deviation, and to 0 when that is 0 too;
* ``group``: the value of the run's grouping column (the template's
  ``GROUP_COL``, passed as the ``group_col`` param) read from the ``samples``
  plate-map hub, so the heatmap and the box plots can be split by perturbation
  group without a join. A well the plate map does not list gets
  ``Not in plate map``; a run without a hub gets ``All wells``.

The plate row and column are parsed from the well name (``B03`` -> row ``B``,
column 3) for the plate layout.

Sources: the ``cp-cells`` single-cell table and, optionally, the ``samples`` hub.

Output schema:
    well_id : Utf8             ``<plate>_<well>``
    plate : Utf8               plate barcode
    well : Utf8                well
    row : Utf8                 plate row letter(s)
    column : Int64             plate column number
    group : Utf8               the well's value of the grouping column
    n_sites : Int64            sites imaged in the well
    n_cells : Int64            cells segmented in the well
    cells_per_site : Float64   n_cells / n_sites
    <feature> : Float64        median of every Float64 single-cell feature
    z_<feature> : Float64      robust z-score of that median across wells
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

CELLS_DC_TAG = "cp-cells"
SAMPLES_DC_TAG = "samples"
HUB_KEY = "well_id"
DEFAULT_GROUP_COL = "pert_type"
NO_HUB_GROUP = "All wells"
UNLISTED_GROUP = "Not in plate map"

#: Float columns of the single-cell table that are positions, not features.
NON_FEATURES = frozenset({"x", "y"})

#: The curated features ``cytotable/single_cell.py`` writes (recipes may not
#: import one another, so the names are repeated here). Any extra Float64
#: column of the single-cell table is profiled too; these are the ones the
#: schema guarantees and the catalog renders bind.
CURATED_FEATURES: tuple[str, ...] = (
    "cell_area",
    "cell_eccentricity",
    "cell_form_factor",
    "cell_solidity",
    "nucleus_area",
    "nucleus_eccentricity",
    "nucleus_form_factor",
    "cytoplasm_area",
    "nucleus_dna_integrated",
    "nucleus_dna_mean",
    "cell_rna_mean",
    "cell_er_mean",
    "cell_agp_mean",
    "cell_mito_mean",
    "cytoplasm_rna_mean",
    "cytoplasm_mito_mean",
    "nucleus_dna_texture_contrast",
    "cell_mito_texture_entropy",
    "cell_mito_granularity",
    "cell_er_granularity",
    "cell_er_mito_correlation",
    "cell_dna_rna_correlation",
    "cell_mito_inner_ring_frac",
    "cell_neighbors",
)

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="cells", dc_ref=CELLS_DC_TAG),
    RecipeSource(ref="samples", dc_ref=SAMPLES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "well_id": pl.Utf8,
    "plate": pl.Utf8,
    "well": pl.Utf8,
    "row": pl.Utf8,
    "column": pl.Int64,
    "group": pl.Utf8,
    "n_sites": pl.Int64,
    "n_cells": pl.Int64,
    "cells_per_site": pl.Float64,
    **{name: pl.Float64 for name in CURATED_FEATURES},
    **{f"z_{name}": pl.Float64 for name in CURATED_FEATURES},
}


def feature_columns(cells: pl.DataFrame) -> list[str]:
    """The Float64 single-cell measurements, in table order."""
    return [
        name
        for name, dtype in cells.schema.items()
        if dtype == pl.Float64 and name not in NON_FEATURES
    ]


def hub_groups(
    samples: pl.DataFrame | None, group_col: str | None
) -> tuple[pl.DataFrame | None, str]:
    """``(well_id, group)`` from the hub, and the label of wells it misses."""
    if samples is None or samples.is_empty() or HUB_KEY not in samples.columns:
        return None, NO_HUB_GROUP
    column = group_col if group_col and group_col in samples.columns else None
    if column is None:
        column = DEFAULT_GROUP_COL if DEFAULT_GROUP_COL in samples.columns else None
    if column is None:
        return None, NO_HUB_GROUP
    groups = samples.select(pl.col(HUB_KEY), pl.col(column).cast(pl.Utf8).alias("group")).unique(
        subset=HUB_KEY
    )
    return groups, UNLISTED_GROUP


def robust_z(column: str) -> pl.Expr:
    """``(x - median) / (1.4826 * MAD)``, falling back to the SD, then to 0."""
    value = pl.col(column)
    centre = value.median()
    mad = (value - centre).abs().median() * 1.4826
    scale = pl.when(mad > 0).then(mad).otherwise(value.std(ddof=0))
    return pl.when(scale > 0).then((value - centre) / scale).otherwise(0.0).alias(f"z_{column}")


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    cells = sources["cells"]
    features = feature_columns(cells)
    wells = cells.group_by(["well_id", "plate", "well"]).agg(
        pl.col("site").n_unique().cast(pl.Int64).alias("n_sites"),
        pl.len().cast(pl.Int64).alias("n_cells"),
        *[pl.col(f).median().alias(f) for f in features],
    )
    wells = wells.with_columns(
        (pl.col("n_cells") / pl.col("n_sites")).cast(pl.Float64).alias("cells_per_site"),
        pl.col("well").str.extract(r"^([A-Za-z]+)", 1).str.to_uppercase().alias("row"),
        pl.col("well").str.extract(r"(\d+)$", 1).cast(pl.Int64).alias("column"),
    )
    groups, fallback = hub_groups(sources.get("samples"), (params or {}).get("group_col"))
    if groups is not None:
        wells = wells.join(groups, on=HUB_KEY, how="left")
    else:
        wells = wells.with_columns(pl.lit(None, dtype=pl.Utf8).alias("group"))
    wells = wells.with_columns(pl.col("group").fill_null(fallback))
    wells = wells.with_columns([robust_z(f) for f in features])
    head = [name for name in EXPECTED_SCHEMA if name not in features and name[2:] not in features]
    ordered = [*head, *features, *[f"z_{f}" for f in features]]
    return wells.select(
        [pl.col(name).cast(EXPECTED_SCHEMA.get(name, pl.Float64)) for name in ordered]
    ).sort(["plate", "row", "column"])
