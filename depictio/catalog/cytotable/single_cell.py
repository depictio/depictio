"""One row per segmented cell, with a curated morphological profile.

nf-core/cellpainting collates the CellProfiler object tables of every imaging
site with CytoTable into ``cytotable/<batch>_<plate>_<well>_<site>.parquet``:
one row per cell, one column per measurement, which for the pipeline's analysis
pipeline is close to 6000 columns (every compartment x channel x texture scale x
radial ring). That width is what a profiling pipeline wants and what a dashboard
cannot use, so this recipe keeps a curated subset.

The feature rule, documented because it decides what every downstream panel can
show:

* identifiers: every ``Metadata_`` column CytoTable writes for the pipeline's
  object model (image number, object number, the cytoplasm's parent cell and
  nucleus), renamed to snake case;
* position: the nucleus centre (``Nuclei_Location_Center_X/Y``), in pixels of
  the site image;
* one to three features per family and compartment, the ones image-based
  profiling papers read first: size and shape (area, eccentricity, form factor,
  solidity), DNA content and intensity (integrated and mean nuclear DNA, mean
  intensity of every stain in the cell), texture (DNA contrast, mitochondrial
  entropy), granularity (mitochondria, ER), colocalisation (ER with
  mitochondria, DNA with RNA), perinuclear mitochondria (innermost radial ring)
  and crowding (adjacent neighbours).

The columns are projected at read time (``read_kwargs.columns``), so a run of a
full plate never materialises the full width. A run whose CellProfiler analysis
pipeline does not measure one of these features (a custom ``--cellprofiler_analysis_cppipe``)
fails to read with a column-not-found error naming it; extend or trim
``FEATURES`` to match that pipeline.

The plate, well and site come from the file name, which the pipeline builds as
``<batch>_<plate>_<well>_<site>``: the site is the last token, the well the one
before, the plate the one before that and the batch whatever precedes it (a
batch name may contain underscores, a plate barcode may not). The well is
normalised to a row letter plus a two-digit column (``A3`` -> ``A03``) so it
joins a plate map written either way.

Output schema:
    cell_id : Utf8          ``<plate>_<well>_s<site>_<object_number>``
    well_id : Utf8          ``<plate>_<well>``, the key the plate map joins on
    site_id : Utf8          ``<plate>_<well>_s<site>``
    batch : Utf8            batch name from the file name (may be empty)
    plate : Utf8            plate barcode
    well : Utf8             well, row letter + two-digit column
    site : Int64            imaging site (field of view) within the well
    image_number : Int64    CellProfiler ImageNumber of the site
    object_number : Int64   CellProfiler ObjectNumber of the cell within the site
    parent_cell : Int64     object number of the cell the cytoplasm belongs to
    parent_nucleus : Int64  object number of the cell's nucleus
    x, y : Float64          nucleus centre, pixels
    <feature> : Float64     the curated features, see ``FEATURES``
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: CytoTable identifier columns kept, renamed.
METADATA: dict[str, str] = {
    "Metadata_ImageNumber": "image_number",
    "Metadata_ObjectNumber": "object_number",
    "Metadata_Cytoplasm_Parent_Cells": "parent_cell",
    "Metadata_Cytoplasm_Parent_Nuclei": "parent_nucleus",
}

#: Nucleus centre, the cell's position in the site image.
POSITION: dict[str, str] = {
    "Nuclei_Location_Center_X": "x",
    "Nuclei_Location_Center_Y": "y",
}

#: The curated profile: CellProfiler column -> tidy name.
FEATURES: dict[str, str] = {
    "Cells_AreaShape_Area": "cell_area",
    "Cells_AreaShape_Eccentricity": "cell_eccentricity",
    "Cells_AreaShape_FormFactor": "cell_form_factor",
    "Cells_AreaShape_Solidity": "cell_solidity",
    "Nuclei_AreaShape_Area": "nucleus_area",
    "Nuclei_AreaShape_Eccentricity": "nucleus_eccentricity",
    "Nuclei_AreaShape_FormFactor": "nucleus_form_factor",
    "Cytoplasm_AreaShape_Area": "cytoplasm_area",
    "Nuclei_Intensity_IntegratedIntensity_DNA": "nucleus_dna_integrated",
    "Nuclei_Intensity_MeanIntensity_DNA": "nucleus_dna_mean",
    "Cells_Intensity_MeanIntensity_RNA": "cell_rna_mean",
    "Cells_Intensity_MeanIntensity_ER": "cell_er_mean",
    "Cells_Intensity_MeanIntensity_AGP": "cell_agp_mean",
    "Cells_Intensity_MeanIntensity_Mito": "cell_mito_mean",
    "Cytoplasm_Intensity_MeanIntensity_RNA": "cytoplasm_rna_mean",
    "Cytoplasm_Intensity_MeanIntensity_Mito": "cytoplasm_mito_mean",
    "Nuclei_Texture_Contrast_DNA_3_00_256": "nucleus_dna_texture_contrast",
    "Cells_Texture_Entropy_Mito_3_00_256": "cell_mito_texture_entropy",
    "Cells_Granularity_1_Mito": "cell_mito_granularity",
    "Cells_Granularity_1_ER": "cell_er_granularity",
    "Cells_Correlation_Correlation_ER_Mito": "cell_er_mito_correlation",
    "Cells_Correlation_Correlation_DNA_RNA": "cell_dna_rna_correlation",
    "Cells_RadialDistribution_MeanFrac_Mito_1of4": "cell_mito_inner_ring_frac",
    "Cells_Neighbors_NumberOfNeighbors_Adjacent": "cell_neighbors",
}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sites",
        glob_pattern="**/cytotable/*.parquet",
        format="parquet",
        read_kwargs={"columns": [*METADATA, *POSITION, *FEATURES]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "cell_id": pl.Utf8,
    "well_id": pl.Utf8,
    "site_id": pl.Utf8,
    "batch": pl.Utf8,
    "plate": pl.Utf8,
    "well": pl.Utf8,
    "site": pl.Int64,
    "image_number": pl.Int64,
    "object_number": pl.Int64,
    "parent_cell": pl.Int64,
    "parent_nucleus": pl.Int64,
    "x": pl.Float64,
    "y": pl.Float64,
    **{name: pl.Float64 for name in FEATURES.values()},
}

_STEM = re.compile(
    r"^(?:(?P<batch>.*)_)?(?P<plate>[^_]+)_(?P<well>[A-Za-z]{1,2}\d{1,3})_(?P<site>\d+)$"
)


def normalise_well(well: str) -> str:
    """``a3`` / ``A3`` / ``A003`` -> ``A03``; anything else is returned upper-cased."""
    match = re.fullmatch(r"([A-Za-z]{1,2})0*(\d{1,3})", well.strip())
    if not match:
        return well.strip().upper()
    return f"{match.group(1).upper()}{int(match.group(2)):02d}"


def parse_site_stem(path: str) -> dict[str, str | int | None]:
    """Batch, plate, well and site of one ``<batch>_<plate>_<well>_<site>.parquet``."""
    stem = path.rstrip("/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.parquet$", "", stem)
    match = _STEM.match(stem)
    if not match:
        raise ValueError(
            f"cytotable file {path!r} is not named <batch>_<plate>_<well>_<site>.parquet"
        )
    return {
        "batch": match.group("batch") or "",
        "plate": match.group("plate"),
        "well": normalise_well(match.group("well")),
        "site": int(match.group("site")),
    }


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    frame = sources["sites"]
    keys = pl.DataFrame(
        [{"source_path": p, **parse_site_stem(p)} for p in frame["source_path"].unique()],
        schema={
            "source_path": pl.Utf8,
            "batch": pl.Utf8,
            "plate": pl.Utf8,
            "well": pl.Utf8,
            "site": pl.Int64,
        },
    )
    frame = (
        frame.join(keys, on="source_path", how="left")
        .rename({**METADATA, **POSITION, **FEATURES})
        .with_columns(
            (pl.col("plate") + "_" + pl.col("well")).alias("well_id"),
            (pl.col("plate") + "_" + pl.col("well") + "_s" + pl.col("site").cast(pl.Utf8)).alias(
                "site_id"
            ),
        )
        .with_columns(
            (pl.col("site_id") + "_" + pl.col("object_number").cast(pl.Utf8)).alias("cell_id"),
        )
    )
    return frame.select([pl.col(name).cast(dtype) for name, dtype in EXPECTED_SCHEMA.items()]).sort(
        ["plate", "well", "site", "object_number"]
    )
