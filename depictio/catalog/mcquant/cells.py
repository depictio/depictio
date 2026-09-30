"""Tidy MCQUANT's single-cell feature tables into one row per segmented cell.

MCQUANT writes one CSV per image and segmentation mask, under
``quantification/mcquant/<segmenter>/``. Every row is one label of the mask
(``CellID`` is the label value, so it matches the pixel values of the mask the
table was quantified on), then one mean-intensity column per marker of the
marker sheet, then the regionprops morphology (``X_centroid``, ``Y_centroid``,
``Area``, ``MajorAxisLength``, ``MinorAxisLength``, ``Eccentricity``,
``Solidity``, ``Extent``, ``Orientation``).

The file carries neither the sample nor the segmenter, so the source hands every
row the path of its file: the segmenter is the parent directory and the sample
is the file name. nf-core/mcmicro renames the table to ``<sample>.csv`` when the
image and mask names line up, and otherwise keeps MCQUANT's
``<image>_<mask>.csv`` (``<sample>_backsub_<sample>_backsub.csv`` for a
background-subtracted image), so the sample is the stem with a repeated
``<sample>(_backsub)`` tail and the ``_backsub`` / ``_mask`` stage words removed.

Marker columns are whatever the run's marker sheet named, so they are carried
under their own names (Float64) next to the fixed columns below. Two derived
columns make the table readable without knowing the panel:

* ``dominant_marker``: per cell, the non-nuclear marker whose log1p intensity
  sits highest above that marker's median in the same sample and segmenter
  (a robust z-score). Nuclear stains are recognised by name (``DNA``, ``DAPI``,
  ``Hoechst`` prefixes), since every cell carries them. ``none`` when the panel
  has no other marker.
* ``pc_1`` / ``pc_2``: the first two principal components of the standardised
  log1p marker intensities, fitted per segmenter over every sample, so cells of
  different samples share one map.

The optional ``segmenter`` param keeps the cells of one segmentation module
(``mesmer``, ``cellpose``, ``mccellpose``), which is what an image overlay needs:
a label value is only a cell id within one mask.

Output columns:
    sample, segmenter, cell_id, cell_uid, x_centroid, y_centroid, area,
    major_axis_length, minor_axis_length, eccentricity, solidity, extent,
    orientation, dominant_marker, pc_1, pc_2, <one Float64 column per marker>
"""

from __future__ import annotations

import re

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

_SOURCE_PATH = "_source_path"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="quant",
        glob_pattern="**/quantification/mcquant/*/*.csv",
        format="CSV",
        source_path=_SOURCE_PATH,
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "segmenter": pl.Utf8,
    "cell_id": pl.Int64,
    "cell_uid": pl.Utf8,
    "x_centroid": pl.Float64,
    "y_centroid": pl.Float64,
    "area": pl.Float64,
    "major_axis_length": pl.Float64,
    "minor_axis_length": pl.Float64,
    "eccentricity": pl.Float64,
    "solidity": pl.Float64,
    "extent": pl.Float64,
    "orientation": pl.Float64,
    "dominant_marker": pl.Utf8,
    "pc_1": pl.Float64,
    "pc_2": pl.Float64,
}
# Marker columns are named by the run's marker sheet; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: MCQUANT column -> output column, for everything that is not a marker.
MORPHOLOGY: dict[str, str] = {
    "X_centroid": "x_centroid",
    "Y_centroid": "y_centroid",
    "Area": "area",
    "MajorAxisLength": "major_axis_length",
    "MinorAxisLength": "minor_axis_length",
    "Eccentricity": "eccentricity",
    "Solidity": "solidity",
    "Extent": "extent",
    "Orientation": "orientation",
}
ID_COLUMN = "CellID"

#: Marker names read as a nuclear stain (present in every cell, never dominant).
NUCLEAR_RE = re.compile(r"^(dna|dapi|hoechst)", re.IGNORECASE)

_STEM_RE = re.compile(
    r"^(?P<s>.+?)(?:_backsub)?(?:\.ome)?(?:_mask)?"
    r"(?:_(?P=s)(?:_backsub)?(?:\.ome)?(?:_cp_masks|_mask)?)?$"
)


def sample_from_path(path: str) -> str:
    """``mcquant/cellpose/S1_backsub_S1_backsub.csv`` -> ``S1``; ``.../S1.csv`` -> ``S1``."""
    stem = path.rsplit("/", 1)[-1]
    stem = stem[: -len(".csv")] if stem.lower().endswith(".csv") else stem
    match = _STEM_RE.match(stem)
    return match.group("s") if match else stem


def segmenter_from_path(path: str) -> str:
    """``quantification/mcquant/mesmer/S1.csv`` -> ``mesmer``."""
    parts = path.split("/")
    return parts[-2] if len(parts) >= 2 else "unknown"


def marker_columns(frame: pl.DataFrame) -> list[str]:
    """The marker intensity columns of a MCQUANT table, in file order."""
    fixed = {ID_COLUMN, _SOURCE_PATH, *MORPHOLOGY}
    return [c for c in frame.columns if c not in fixed and frame.schema[c].is_numeric()]


def is_nuclear(marker: str) -> bool:
    return bool(NUCLEAR_RE.match(marker))


def _dominant_marker(frame: pl.DataFrame, markers: list[str]) -> pl.Series:
    """Per cell, the non-nuclear marker with the highest robust z-score."""
    candidates = [m for m in markers if not is_nuclear(m)]
    if not candidates:
        return pl.Series("dominant_marker", ["none"] * frame.height, dtype=pl.Utf8)
    scores = []
    for m in candidates:
        logged = pl.col(m).fill_null(0.0).clip(lower_bound=0.0).log1p()
        med = logged.median().over("sample", "segmenter")
        mad = (logged - med).abs().median().over("sample", "segmenter")
        scores.append(((logged - med) / pl.when(mad > 0).then(mad).otherwise(1.0)).alias(m))
    z = frame.select(scores).to_numpy()
    best = np.nanargmax(np.nan_to_num(z, nan=-np.inf), axis=1)
    return pl.Series("dominant_marker", [candidates[i] for i in best], dtype=pl.Utf8)


def _principal_components(frame: pl.DataFrame, markers: list[str]) -> tuple[np.ndarray, ...]:
    """First two PCs of standardised log1p marker intensities, per segmenter."""
    pc1 = np.zeros(frame.height)
    pc2 = np.zeros(frame.height)
    if len(markers) < 2:
        return pc1, pc2
    segmenters = frame.get_column("segmenter").to_numpy()
    values = np.log1p(np.clip(frame.select(markers).fill_null(0.0).to_numpy(), 0.0, None))
    for seg in np.unique(segmenters):
        rows = segmenters == seg
        block = values[rows]
        if block.shape[0] < 3:
            continue
        block = block - block.mean(axis=0)
        sd = block.std(axis=0)
        block = block / np.where(sd > 0, sd, 1.0)
        _, _, vt = np.linalg.svd(block, full_matrices=False)
        coords = block @ vt[:2].T
        pc1[rows] = coords[:, 0]
        if coords.shape[1] > 1:
            pc2[rows] = coords[:, 1]
    return pc1, pc2


def load_cells(quant: pl.DataFrame, segmenter: str | None = None) -> tuple[pl.DataFrame, list[str]]:
    """The tidy per-cell frame and its marker columns (shared by the mcquant recipes)."""
    if ID_COLUMN not in quant.columns:
        raise ValueError(f"mcquant: no {ID_COLUMN} column in the quantification tables")
    missing = [c for c in ("X_centroid", "Y_centroid") if c not in quant.columns]
    if missing:
        raise ValueError(f"mcquant: quantification tables lack {missing}")
    paths = quant.get_column(_SOURCE_PATH).unique().to_list()
    sample_of = {p: sample_from_path(p) for p in paths}
    segmenter_of = {p: segmenter_from_path(p) for p in paths}
    frame = quant.with_columns(
        pl.col(_SOURCE_PATH).replace_strict(sample_of, return_dtype=pl.Utf8).alias("sample"),
        pl.col(_SOURCE_PATH).replace_strict(segmenter_of, return_dtype=pl.Utf8).alias("segmenter"),
    )
    if segmenter:
        frame = frame.filter(pl.col("segmenter") == segmenter)
    markers = marker_columns(quant)
    frame = frame.select(
        "sample",
        "segmenter",
        pl.col(ID_COLUMN).cast(pl.Int64).alias("cell_id"),
        *[
            (pl.col(src) if src in frame.columns else pl.lit(None)).cast(pl.Float64).alias(dst)
            for src, dst in MORPHOLOGY.items()
        ],
        *[pl.col(m).cast(pl.Float64) for m in markers],
    ).with_columns(
        pl.concat_str(
            [pl.col("sample"), pl.col("segmenter"), pl.col("cell_id").cast(pl.Utf8)],
            separator="/",
        ).alias("cell_uid")
    )
    return frame.sort("segmenter", "sample", "cell_id"), markers


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    segmenter = ((params or {}).get("segmenter") or "").strip() or None
    frame, markers = load_cells(sources["quant"], segmenter)
    if frame.is_empty():
        return frame
    pc1, pc2 = _principal_components(frame, markers)
    frame = frame.with_columns(
        _dominant_marker(frame, markers),
        pl.Series("pc_1", pc1, dtype=pl.Float64),
        pl.Series("pc_2", pc2, dtype=pl.Float64),
    )
    return frame.select(*EXPECTED_SCHEMA, *markers)
