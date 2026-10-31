"""Shared parsing for MCQUANT single-cell tables (nf-core/mcmicro).

MCQUANT (labsyspharm/quantification) writes one CSV per image and segmentation
mask: one row per segmented cell, with

* ``CellID``: the mask label, an integer that restarts at 1 for every image and
  every mask, so it is never unique across a run;
* one column per quantified channel: the cell's mean intensity in that channel,
  named after the marker sheet's ``marker_name`` (channels the sheet marks
  ``remove`` are dropped by the pipeline before quantification);
* the ``skimage.measure.regionprops`` morphology of the cell: ``X_centroid``,
  ``Y_centroid`` (pixels of the registered image, origin top-left, y down),
  ``Area`` (pixels), ``MajorAxisLength``, ``MinorAxisLength``, ``Eccentricity``,
  ``Solidity``, ``Extent`` and ``Orientation``.

nf-core/mcmicro publishes them as ``quantification/mcquant/<segmenter>/<file>.csv``.
The segmenter is the directory (``mesmer``, ``cellpose``, ``mccellpose``). The
file is meant to be ``<sample>.csv``, but the rename in the pipeline's
``conf/modules.config`` only fires for a mask called ``<sample>_mask``, so 2.0.0
writes the Cellpose tables as ``<sample>_backsub_<sample>_backsub.csv``
(image stem, then mask stem). ``sample_from_stem`` reads every one of those
shapes back to the sample.

The marker columns are only known at ingest (one per channel of the run's
panel), so every reader here takes them as "the numeric columns that are not an
id or a morphology column", in file order (``marker_columns``).
"""

from __future__ import annotations

import math
import re

import numpy as np
import polars as pl

#: The mask label column.
ID_COLUMN = "CellID"
#: regionprops columns MCQUANT writes after the marker columns.
CENTROID_COLUMNS = ("X_centroid", "Y_centroid")
MORPHOLOGY_COLUMNS = (
    "X_centroid",
    "Y_centroid",
    "Area",
    "MajorAxisLength",
    "MinorAxisLength",
    "Eccentricity",
    "Solidity",
    "Extent",
    "Orientation",
)
#: Columns the readers add; never a marker.
DERIVED_COLUMNS = ("cell_key", "sample", "segmenter", "aspect_ratio", "source_path")

#: Cofactor of the asinh transform the intensity summaries use, the
#: `spatial_cells` default: asinh(x / 150) is linear near 0 and logarithmic in
#: the bright tail, so a 16-bit mean intensity reads on one axis.
ASINH_COFACTOR = 150.0

#: Segmenter directory (or a mask stem's tool) to its reader-facing name.
SEGMENTER_LABELS = {
    "mesmer": "Mesmer",
    "deepcell_mesmer": "Mesmer",
    "cellpose": "Cellpose",
    "mccellpose": "MCCellpose",
}

#: Nuclear counterstains: a marker named like one is the DNA channel of its
#: cycle, the one segmentation runs on, not a protein readout.
_NUCLEAR_RE = re.compile(r"^(dna|dapi|hoechst|hoe|nuclei|nuclear|h33342|draq5|syto)", re.I)
#: Stage suffixes nf-core/mcmicro appends to an image or a mask stem.
_STAGE_SUFFIX_RE = re.compile(r"(?:\.ome)?(?:_backsub|_cp_masks|_mask|_masks)+$")


def segmenter_label(name: str | None) -> str:
    """``Mesmer`` for ``mesmer``; an unknown tool keeps its own name."""
    key = (name or "").strip()
    return SEGMENTER_LABELS.get(key.lower(), key or "Unknown")


def _strip_stage(stem: str) -> str:
    previous = None
    while previous != stem:
        previous = stem
        stem = _STAGE_SUFFIX_RE.sub("", stem)
    return stem


def sample_from_stem(stem: str) -> str:
    """The sample of an MCQUANT file stem.

    ``TEST1`` stays ``TEST1``; ``TEST1_backsub_TEST1_backsub`` (image stem then
    mask stem, the Cellpose name of 2.0.0) and ``TEST1_backsub_TEST1_mask`` both
    read ``TEST1``.
    """
    stem = re.sub(r"\.csv$", "", stem.strip(), flags=re.I)
    # Image stem then mask stem: `<a>_<b>` where both halves name one sample.
    parts = stem.split("_")
    for cut in range(1, len(parts)):
        left = _strip_stage("_".join(parts[:cut]))
        right = _strip_stage("_".join(parts[cut:]))
        if left and left == right:
            return left
    return _strip_stage(stem) or stem


def is_nuclear(marker: str) -> bool:
    """Whether a marker name is a nuclear counterstain (DNA_1, DAPI, Hoechst...)."""
    return bool(_NUCLEAR_RE.match(marker.strip()))


def marker_columns(frame: pl.DataFrame) -> list[str]:
    """The marker columns of an MCQUANT table, in file order."""
    skip = {ID_COLUMN, *MORPHOLOGY_COLUMNS, *DERIVED_COLUMNS}
    return [c for c, dtype in frame.schema.items() if c not in skip and dtype.is_numeric()]


def load_cells(raw: pl.DataFrame, source_col: str = "source_path") -> pl.DataFrame:
    """Every cell of every MCQUANT table, with its sample, segmenter and a run-wide key.

    ``raw`` is the glob concatenation of ``quantification/mcquant/*/*.csv`` with
    the file path in ``source_col``. Adds ``sample``, ``segmenter`` (display
    name), ``cell_key`` (``<sample>|<segmenter>|<CellID>``, unique over the run)
    and ``aspect_ratio`` (major over minor axis); casts the markers and the
    morphology to Float64 and ``CellID`` to Int64.
    """
    missing = [c for c in (ID_COLUMN, *CENTROID_COLUMNS, "Area") if c not in raw.columns]
    if missing:
        raise ValueError(
            f"mcquant table: missing column(s) {missing}; got {raw.columns[:20]}. "
            "Expected MCQUANT output (CellID, one column per marker, X_centroid, Y_centroid, Area ...)"
        )
    path = pl.col(source_col).cast(pl.Utf8).str.replace_all(r"\\", "/")
    frame = raw.with_columns(
        path.str.extract(r"([^/]+)/[^/]+$", 1).fill_null("").alias("_segmenter_dir"),
        path.str.extract(r"([^/]+)$", 1).fill_null("").alias("_stem"),
    )
    frame = frame.with_columns(
        pl.col("_stem").map_elements(sample_from_stem, return_dtype=pl.Utf8).alias("sample"),
        pl.col("_segmenter_dir")
        .map_elements(segmenter_label, return_dtype=pl.Utf8)
        .alias("segmenter"),
        pl.col(ID_COLUMN).cast(pl.Int64),
    ).drop("_segmenter_dir", "_stem")
    markers = marker_columns(frame)
    morphology = [c for c in MORPHOLOGY_COLUMNS if c in frame.columns]
    frame = frame.with_columns(
        *[pl.col(c).cast(pl.Float64) for c in [*markers, *morphology]],
    )
    for column in MORPHOLOGY_COLUMNS:
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(column))
    frame = frame.with_columns(
        pl.concat_str(
            [pl.col("sample"), pl.col("segmenter"), pl.col(ID_COLUMN).cast(pl.Utf8)],
            separator="|",
        ).alias("cell_key"),
        pl.when(pl.col("MinorAxisLength") > 0)
        .then((pl.col("MajorAxisLength") / pl.col("MinorAxisLength")).round(4))
        .otherwise(None)
        .alias("aspect_ratio"),
    ).filter(pl.col(ID_COLUMN).is_not_null())
    lead = ["cell_key", "sample", "segmenter", ID_COLUMN]
    tail = [*MORPHOLOGY_COLUMNS, "aspect_ratio"]
    return frame.select(lead + markers + tail).sort(["sample", "segmenter", ID_COLUMN])


def asinh(expr: pl.Expr, cofactor: float = ASINH_COFACTOR) -> pl.Expr:
    """asinh(x / cofactor), as a polars expression."""
    return (expr / cofactor).arcsinh()


def melt_markers(cells: pl.DataFrame) -> pl.DataFrame:
    """One row per cell and marker: ``intensity`` and ``asinh_intensity``."""
    markers = marker_columns(cells)
    if not markers:
        raise ValueError(
            "mcquant table: no marker column (a numeric column besides the morphology)"
        )
    long = cells.select("cell_key", "sample", "segmenter", ID_COLUMN, *markers).unpivot(
        index=["cell_key", "sample", "segmenter", ID_COLUMN],
        on=markers,
        variable_name="marker",
        value_name="intensity",
    )
    order = {m: i + 1 for i, m in enumerate(markers)}
    return long.with_columns(
        pl.col("intensity").cast(pl.Float64),
        asinh(pl.col("intensity").cast(pl.Float64)).round(4).alias("asinh_intensity"),
        pl.col("marker").replace_strict(order, return_dtype=pl.Int64).alias("marker_order"),
        pl.col("marker")
        .map_elements(
            lambda m: "Nuclear stain" if is_nuclear(m) else "Marker", return_dtype=pl.Utf8
        )
        .alias("marker_role"),
    )


def centroid_hits(
    centres: tuple[np.ndarray, np.ndarray, np.ndarray],
    points: tuple[np.ndarray, np.ndarray],
) -> np.ndarray:
    """How many ``points`` fall inside each centre's disc.

    ``centres`` is ``(x, y, radius)``, a cell of one segmenter with the radius of
    a disc of its area; ``points`` are the centroids of another segmenter's cells
    on the same image. Points are sorted by x once and each disc reads only the
    slice of points within its radius on x, so a run of 10^5 cells stays linear
    in practice.
    """
    cx, cy, cr = centres
    px, py = points
    if len(px) == 0 or len(cx) == 0:
        return np.zeros(len(cx), dtype=np.int64)
    order = np.argsort(px, kind="stable")
    sx, sy = px[order], py[order]
    lo = np.searchsorted(sx, cx - cr, side="left")
    hi = np.searchsorted(sx, cx + cr, side="right")
    out = np.zeros(len(cx), dtype=np.int64)
    for i in range(len(cx)):
        a, b = lo[i], hi[i]
        if b <= a:
            continue
        dx = sx[a:b] - cx[i]
        dy = sy[a:b] - cy[i]
        out[i] = int(np.count_nonzero(dx * dx + dy * dy <= cr[i] * cr[i]))
    return out


def equivalent_radius(area: np.ndarray) -> np.ndarray:
    """Radius of the disc of each area, in the same units."""
    return np.sqrt(np.clip(area, 0, None) / math.pi)
