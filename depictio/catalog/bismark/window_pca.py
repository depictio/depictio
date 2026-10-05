"""Where each library sits in the space of its own binned methylome.

``bismark_binned_methylation`` leaves a complete sample x window matrix: the
same windows measured in every library, which is exactly the shape a principal
component analysis wants. The first two components of that matrix are the
standard first look at a bisulfite cohort, and they answer a question no
per-sample QC number can: do the libraries separate by the biology the design
claims or by depth, batch or conversion rate.

The decomposition is a plain SVD through
``depictio/recipes/lib/dimreduction.run_pca`` (numpy only, so nothing is pinned
into a recipe that the CLI environment may not carry), on the standardised
windows. With a handful of libraries and tens of thousands of windows it is
instant; the cost was paid upstream, in the binning.

The sample sheet is joined in when the template declares one, under the
repo-wide ``samples`` hub tag, so the embedding can be coloured by the design
rather than by the sample id. It is optional: without it the coordinates are
still there and the design columns are null.

Output schema:
    sample_id : Utf8   library
    dim_1 : Float64    first principal component
    dim_2 : Float64    second principal component
    dim_3 : Float64    third principal component
    <design columns> : Utf8  every factor of the sample hub (the run's
                             METADATA_FILE), when it declares any
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bismark_names import hub_factor_columns
from depictio.recipes.lib.dimreduction import run_pca
from depictio.recipes.lib.genomic_bins import window_matrix
from depictio.recipes.lib.sample_hub import annotate_from_hub

MATRIX_DC_TAG = "bismark_binned_methylation"
SAMPLES_DC_TAG = "samples"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="windows", dc_ref=MATRIX_DC_TAG),
    RecipeSource(ref="samples", dc_ref=SAMPLES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "dim_3": pl.Float64,
}
# Design columns are run-dependent (the sample hub's factors); validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Sample-hub columns carried onto the embedding when the hub declares them.


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """PCA the sample x window matrix, then colour it with the sample sheet."""
    matrix = window_matrix(sources["windows"])
    if matrix.height < 3:
        raise ValueError(
            f"bismark_window_pca: a PCA needs at least three libraries, got {matrix.height}"
        )

    n_components = min(3, matrix.height - 1)
    coords = run_pca(matrix, n_components=n_components, scale=True)
    for index in range(n_components + 1, 4):
        coords = coords.with_columns(pl.lit(None, pl.Float64).alias(f"dim_{index}"))

    samples = sources.get("samples")
    factors = hub_factor_columns(samples)
    return (
        annotate_from_hub(coords, samples, factors)
        .select(*EXPECTED_SCHEMA, *factors)
        .sort("sample_id")
    )
