"""The segmentation images of a run, as an image-gallery table.

CellProfiler writes two kinds of PNG a reader looks at before trusting any
number: the assay-development ``*_ObjectOverlay.png`` (one representative site
per well, nuclei and cell outlines drawn over the stains, the pipeline's visual
QC gate) and the analysis step's per-site ``<well>_s<site>--cell_outlines.png``
and ``--nuclei_outlines.png``. This recipe lists them, one row per image, with
the plate, well and site each one shows, so an image-gallery collection can
filter them by well, site or perturbation group like any other table.

The images are files, not tables, so they cannot be a recipe source: the recipe
walks the run directory named by the ``data_root`` param (the template passes
``{DATA_ROOT}``) and records each path relative to it, which is what the
gallery joins to its storage prefix.

Where each image comes from:

* ``<batch>_<plate>_<well>_ObjectOverlay.png``: plate and well from the name
  (the well is the last token, the plate the one before); the site is the
  assay-development site (``--cellprofiler_assaydevelopment_site``), which the
  file name does not carry, so it is left empty;
* ``<well>_s<site>--{cell,nuclei}_outlines.png``: well and site from the name,
  plate from the enclosing ``<batch>_<plate>_<well>_<site>`` directory when the
  run publishes one directory per site. A run that publishes the analysis flat
  names no plate, so the plate is taken from the ``samples`` hub when exactly one
  plate lists that well (and left empty otherwise).

Output schema:
    image_id : Utf8     the path, unique per row
    image_path : Utf8   path relative to the run directory
    image_kind : Utf8   Object overlay / Cell outlines / Nuclei outlines
    well_id : Utf8      ``<plate>_<well>`` (empty when the plate is unknown)
    plate : Utf8        plate barcode
    well : Utf8         well, row letter + two-digit column
    site : Int64        imaging site (empty for the overlays)
    site_id : Utf8      ``<plate>_<well>_s<site>`` (empty without a site)
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource

SAMPLES_DC_TAG = "samples"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref=SAMPLES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "image_id": pl.Utf8,
    "image_path": pl.Utf8,
    "image_kind": pl.Utf8,
    "well_id": pl.Utf8,
    "plate": pl.Utf8,
    "well": pl.Utf8,
    "site": pl.Int64,
    "site_id": pl.Utf8,
}

_WELL = r"[A-Za-z]{1,2}\d{1,3}"
_OVERLAY = re.compile(rf"^(?:.*_)?(?P<plate>[^_]+)_(?P<well>{_WELL})_ObjectOverlay\.png$")
_OUTLINE = re.compile(rf"^(?P<well>{_WELL})_s(?P<site>\d+)--(?P<kind>cell|nuclei)_outlines\.png$")
_SITE_DIR = re.compile(rf"^(?:.*_)?(?P<plate>[^_]+)_(?P<well>{_WELL})_(?P<site>\d+)$")
_KINDS = {"cell": "Cell outlines", "nuclei": "Nuclei outlines"}


def normalise_well(well: str) -> str:
    """``a3`` / ``A3`` / ``A003`` -> ``A03``; anything else is returned upper-cased."""
    match = re.fullmatch(r"([A-Za-z]{1,2})0*(\d{1,3})", well.strip())
    if not match:
        return well.strip().upper()
    return f"{match.group(1).upper()}{int(match.group(2)):02d}"


def _plates_by_well(samples: pl.DataFrame | None) -> dict[str, str]:
    """Well -> plate for the wells exactly one hub plate lists."""
    if samples is None or samples.is_empty() or not {"plate", "well"} <= set(samples.columns):
        return {}
    pairs = samples.select("plate", "well").drop_nulls().unique()
    counts = pairs.group_by("well").agg(pl.col("plate").first(), pl.len().alias("n"))
    return {w: p for w, p, n in counts.iter_rows() if n == 1}


def classify(rel: Path, plates_by_well: dict[str, str]) -> dict[str, object] | None:
    """The row of one image, or None when it is not a segmentation image."""
    overlay = _OVERLAY.match(rel.name)
    if overlay:
        plate, well, site = overlay.group("plate"), normalise_well(overlay.group("well")), None
        kind = "Object overlay"
    else:
        outline = _OUTLINE.match(rel.name)
        if not outline:
            return None
        well, site = normalise_well(outline.group("well")), int(outline.group("site"))
        kind = _KINDS[outline.group("kind")]
        site_dir = _SITE_DIR.match(rel.parent.name)
        plate = site_dir.group("plate") if site_dir else plates_by_well.get(well)
    well_id = f"{plate}_{well}" if plate else None
    return {
        "image_id": rel.as_posix(),
        "image_path": rel.as_posix(),
        "image_kind": kind,
        "well_id": well_id,
        "plate": plate,
        "well": well,
        "site": site,
        "site_id": f"{well_id}_s{site}" if well_id and site is not None else None,
    }


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    root_param = (params or {}).get("data_root")
    if not root_param:
        raise ValueError("object_overlays needs the run directory as the data_root param")
    root = Path(root_param).expanduser()
    plates_by_well = _plates_by_well(sources.get("samples"))
    rows = [
        row
        for path in sorted(root.glob("**/cellprofiler/**/*.png"))
        if (row := classify(path.relative_to(root), plates_by_well)) is not None
    ]
    if not rows:
        raise ValueError(f"no CellProfiler overlay or outline PNG under {root}")
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["image_kind", "plate", "well", "site"])
