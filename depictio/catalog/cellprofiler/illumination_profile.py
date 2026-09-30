"""How uneven the illumination was, per plate and channel.

nf-core/cellpainting's first CellProfiler step computes one illumination
correction function per plate and channel (CorrectIlluminationCalculate) and
saves it as ``cellprofiler/illumination_correction/**/<plate>_Illum<channel>.npy``,
a 2-D float array the size of a site image by which every raw image of that
plate and channel is divided. The function is scaled so its minimum is 1, so
its maximum is how many times brighter the brightest part of the field was
illuminated than the dimmest: a flat function (close to 1 everywhere) means an
even field, a function reaching 2 or 3 at the centre means strong vignetting
that the correction had to undo, and a lopsided function points at a
misaligned light path.

The arrays are not tables, so they cannot be a recipe source: the recipe reads
them from the run directory named by the ``data_root`` param (the template
passes ``{DATA_ROOT}``). Each function is reduced to a radial profile, the mean
correction in 50 rings from the field centre (distance 0) to the corners
(distance 1), which is the shape vignetting takes; ``correction_range`` repeats
on every row the function's maximum over its minimum.

The optional ``samples`` hub restricts the plates to those the run analysed
when the run directory holds corrections of other plates too.

Output schema:
    series : Utf8             ``<plate> <channel>``, one profile per function
    plate : Utf8              plate barcode
    channel : Utf8            channel name (DNA, ER, RNA, AGP, Mito, Brightfield, ...)
    distance : Float64        distance from the field centre, 0 (centre) to 1 (corner)
    correction : Float64      mean correction factor in that ring
    correction_range : Float64  max / min of the whole function
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

SAMPLES_DC_TAG = "samples"
FUNCTION_GLOB = "**/illumination_correction/**/*_Illum*.npy"
N_RINGS = 50
_NAME = re.compile(r"^(?P<plate>.+?)_Illum(?P<channel>[A-Za-z0-9_]+)\.npy$")

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref=SAMPLES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "series": pl.Utf8,
    "plate": pl.Utf8,
    "channel": pl.Utf8,
    "distance": pl.Float64,
    "correction": pl.Float64,
    "correction_range": pl.Float64,
}


def radial_profile(function: np.ndarray, n_rings: int = N_RINGS) -> tuple[np.ndarray, np.ndarray]:
    """Ring centres (0..1, centre to corner) and the mean value of each ring."""
    height, width = function.shape
    yy, xx = np.indices(function.shape)
    cy, cx = (height - 1) / 2.0, (width - 1) / 2.0
    radius = np.hypot(yy - cy, xx - cx)
    radius = radius / radius.max()
    ring = np.minimum((radius * n_rings).astype(int), n_rings - 1)
    sums = np.bincount(ring.ravel(), weights=function.ravel(), minlength=n_rings)
    counts = np.bincount(ring.ravel(), minlength=n_rings)
    means = np.divide(sums, counts, out=np.full(n_rings, np.nan), where=counts > 0)
    centres = (np.arange(n_rings) + 0.5) / n_rings
    return centres, means


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    root = (params or {}).get("data_root")
    if not root:
        raise ValueError("illumination_profile needs the run directory as the data_root param")
    samples = sources.get("samples")
    plates = (
        set(samples["plate"].drop_nulls().to_list())
        if samples is not None and not samples.is_empty() and "plate" in samples.columns
        else None
    )
    rows: list[dict[str, object]] = []
    for path in sorted(Path(root).expanduser().glob(FUNCTION_GLOB)):
        match = _NAME.match(path.name)
        if not match:
            continue
        plate, channel = match.group("plate"), match.group("channel")
        if plates is not None and plate not in plates:
            continue
        function = np.load(path).astype(np.float64)
        if function.ndim != 2 or function.size == 0:
            continue
        low = float(np.nanmin(function))
        span = float(np.nanmax(function)) / low if low > 0 else float("nan")
        for distance, value in zip(*radial_profile(function), strict=True):
            rows.append(
                {
                    "series": f"{plate} {channel}",
                    "plate": plate,
                    "channel": channel,
                    "distance": float(distance),
                    "correction": float(value),
                    "correction_range": span,
                }
            )
    if not rows:
        raise ValueError(f"no illumination function matching {FUNCTION_GLOB} under {root}")
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["plate", "channel", "distance"])
