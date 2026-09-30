"""The single-cell feature matrix, labelled with the well's perturbation group.

The matrix a two-group comparison is computed over: one row per cell, the
curated morphological features as Float64 columns, and nothing else numeric
(no positions, no object numbers), because the group_compare renderer tests
every numeric column it finds. Each cell carries its well and the value of the
run's grouping column, read from the ``samples`` plate-map hub (the template's
``GROUP_COL``, passed as the ``group_col`` param), so the comparison can open
on two perturbation groups with no lasso at all.

A cell-level test between groups treats cells as independent observations,
which they are not (cells of one well share its handling). It is a screen for
which features move, the way image-based profiling tools rank features before
a well-level analysis; the well-level medians are on the per-well table.

Sources: the ``cp-cells`` single-cell table and, optionally, the ``samples`` hub.

Output schema:
    cell_id : Utf8         ``<plate>_<well>_s<site>_<object_number>``
    well_id : Utf8         ``<plate>_<well>``
    site_id : Utf8         ``<plate>_<well>_s<site>``
    well : Utf8            well
    group : Utf8           the well's value of the grouping column
    <feature> : Float64    every Float64 single-cell feature
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
NON_FEATURES = frozenset({"x", "y"})

#: The curated features ``cytotable/single_cell.py`` writes (repeated: recipes
#: may not import one another). Extra Float64 columns pass through.
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
    "cell_id": pl.Utf8,
    "well_id": pl.Utf8,
    "site_id": pl.Utf8,
    "well": pl.Utf8,
    "group": pl.Utf8,
    **{name: pl.Float64 for name in CURATED_FEATURES},
}


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


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    cells = sources["cells"]
    features = [
        name
        for name, dtype in cells.schema.items()
        if dtype == pl.Float64 and name not in NON_FEATURES
    ]
    groups, fallback = hub_groups(sources.get("samples"), (params or {}).get("group_col"))
    if groups is not None:
        cells = cells.join(groups, on=HUB_KEY, how="left")
    else:
        cells = cells.with_columns(pl.lit(None, dtype=pl.Utf8).alias("group"))
    cells = cells.with_columns(pl.col("group").fill_null(fallback))
    head = ["cell_id", "well_id", "site_id", "well", "group"]
    return cells.select(
        *[pl.col(name).cast(pl.Utf8) for name in head],
        *[pl.col(name).cast(pl.Float64) for name in features],
    )
