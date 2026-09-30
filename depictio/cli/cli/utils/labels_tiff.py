"""Segmentation-mask TIFFs to multiscale OME-Zarr labels images.

Most segmentation tools (Mesmer, Cellpose, StarDist, ilastik) write a plain
TIFF mask: one integer per pixel, the cell id, 0 for background. The viewer
reads tiles of a multiscale pyramid, so a ``bioimage`` DC with ``format:
tiff`` / ``kind: labels`` converts each mask at ingest into an NGFF 0.4
labels image, uploaded like any OME-Zarr store:

* the store root is itself an NGFF ``multiscales`` image (so viv's OME-Zarr
  loader opens it), axes ``y, x``, plus an ``image-label`` block marking it
  as a label image;
* level 0 is the mask as it is; each further level keeps every second pixel
  along y and x (nearest neighbour: label ids are never averaged) until the
  largest side is at most ``LABELS_MIN_SIDE``;
* zarr v2, ``/`` dimension separator, ``LABELS_CHUNK`` x ``LABELS_CHUNK``
  chunks, zlib level 5 (the codec every browser decodes, as the example
  stores use), all-background chunks left out (zarr readers fill them with 0);
* the dtype is the source's when it is an integer of at most 32 bits, else
  uint32 when the ids fit (a 64-bit mask with small ids), else an error:
  WebGL has no 64-bit integer textures.

Written with numpy and zlib only (no zarr dependency) and read with
``tifffile``. The whole level 0 is held in memory: a 20k x 20k uint32 mask is
1.6 GB.
"""

from __future__ import annotations

import json
import os
import zlib
from dataclasses import dataclass
from typing import Any

import numpy as np

# Chunk edge along y and x: the tile size the viewer requests.
LABELS_CHUNK = 256
# Pyramid levels are added until the largest side is at most this.
LABELS_MIN_SIDE = 512
LABELS_ZLIB_LEVEL = 5
# Bumped when the converted layout changes, so the upload marker (keyed on the
# source TIFF) no longer matches and every mask is converted again.
LABELS_CONVERSION_VERSION = "1"
_UINT32_MAX = 2**32 - 1


@dataclass(frozen=True)
class LabelsTiffInfo:
    """What the TIFF header says about a mask, before any pixel is read."""

    shape: tuple[int, int]
    dtype: np.dtype


def _series_of(tif: Any, path: str) -> Any:
    if not tif.series:
        raise ValueError(f"{path} holds no image")
    return tif.series[0]


def inspect_labels_tiff(path: str) -> LabelsTiffInfo:
    """Raise ValueError unless ``path`` is a TIFF holding a 2D integer mask.

    Reads the header only. Accepted: an integer dtype and, once singleton axes
    are dropped, exactly two axes (y, x). Rejected with a message naming what
    was found: float masks (probabilities, not ids), RGB(A) images, stacks
    (more than one plane) and 1D data.
    """
    import tifffile

    try:
        with tifffile.TiffFile(path) as tif:
            series = _series_of(tif, path)
            shape = tuple(int(s) for s in series.shape)
            axes = str(series.axes)
            dtype = np.dtype(series.dtype)
    except Exception as e:  # tifffile's TiffFileError, OSError, a broken IFD
        raise ValueError(f"{path} is not a readable TIFF: {e}") from e

    if "S" in axes and shape[axes.index("S")] in (3, 4):
        raise ValueError(
            f"{path} is an RGB(A) image (axes {axes}, shape {shape}), not a label mask: "
            "a labels TIFF holds one integer cell id per pixel"
        )
    if not np.issubdtype(dtype, np.integer):
        raise ValueError(
            f"{path} has dtype {dtype}, not an integer type: a labels TIFF holds one "
            "integer cell id per pixel (0 = background), not probabilities or intensities"
        )
    kept = tuple(s for s in shape if s != 1)
    if len(kept) != 2:
        raise ValueError(
            f"{path} has shape {shape} (axes {axes}): a labels TIFF must be one 2D plane "
            "(y, x), possibly with singleton axes"
        )
    return LabelsTiffInfo(shape=(kept[0], kept[1]), dtype=dtype)


def read_labels_tiff(path: str) -> np.ndarray:
    """The mask of ``path`` as a 2D array of the dtype ``labels_dtype`` picks."""
    import tifffile

    info = inspect_labels_tiff(path)
    with tifffile.TiffFile(path) as tif:
        data = np.asarray(_series_of(tif, path).asarray())
    data = data.reshape(info.shape)
    target = labels_dtype(data, path)
    return data if data.dtype == target else data.astype(target)


def labels_dtype(data: np.ndarray, path: str = "mask") -> np.dtype:
    """The dtype the converted store keeps.

    The source's when it is an integer of at most 32 bits, else uint32 when
    every id fits. Negative ids are rejected: a label is a cell id, 0 being
    the background.
    """
    if data.size and int(data.min()) < 0:
        raise ValueError(f"{path} has negative label values: cell ids must be 0 or more")
    if data.dtype.itemsize <= 4:
        return data.dtype
    if data.size and int(data.max()) > _UINT32_MAX:
        raise ValueError(
            f"{path} has label values above {_UINT32_MAX}: the viewer reads at most 32-bit ids"
        )
    return np.dtype(np.uint32)


def labels_pyramid(data: np.ndarray, min_side: int = LABELS_MIN_SIDE) -> list[np.ndarray]:
    """Level 0 first, each next level every second pixel of the previous one."""
    levels = [data]
    while max(levels[-1].shape) > min_side:
        levels.append(np.ascontiguousarray(levels[-1][::2, ::2]))
    return levels


def _zarray(shape: tuple[int, ...], dtype: np.dtype, chunk: int) -> dict[str, Any]:
    return {
        "chunks": [chunk, chunk],
        "compressor": {"id": "zlib", "level": LABELS_ZLIB_LEVEL},
        "dimension_separator": "/",
        # Little-endian always: the bytes are written with that order.
        "dtype": dtype.newbyteorder("<").str,
        "fill_value": 0,
        "filters": None,
        "order": "C",
        "shape": list(shape),
        "zarr_format": 2,
    }


def _write_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _write_level(level_dir: str, data: np.ndarray, chunk: int) -> int:
    """Chunk files of one level; returns how many were written (non-empty ones)."""
    os.makedirs(level_dir, exist_ok=True)
    little = data.astype(data.dtype.newbyteorder("<"), copy=False)
    _write_json(os.path.join(level_dir, ".zarray"), _zarray(data.shape, data.dtype, chunk))
    height, width = data.shape
    written = 0
    for iy in range((height + chunk - 1) // chunk):
        for ix in range((width + chunk - 1) // chunk):
            block = little[iy * chunk : (iy + 1) * chunk, ix * chunk : (ix + 1) * chunk]
            if not block.any():
                continue
            # zarr v2 edge chunks are full-size, padded with the fill value.
            padded = np.zeros((chunk, chunk), dtype=little.dtype)
            padded[: block.shape[0], : block.shape[1]] = block
            row_dir = os.path.join(level_dir, str(iy))
            os.makedirs(row_dir, exist_ok=True)
            with open(os.path.join(row_dir, str(ix)), "wb") as fh:
                fh.write(zlib.compress(padded.tobytes(order="C"), LABELS_ZLIB_LEVEL))
            written += 1
    return written


def write_labels_ome_zarr(
    data: np.ndarray,
    store_path: str,
    name: str,
    *,
    chunk: int = LABELS_CHUNK,
    min_side: int = LABELS_MIN_SIDE,
) -> str:
    """Write ``data`` (2D integer) as an NGFF 0.4 multiscale labels image at ``store_path``."""
    if data.ndim != 2:
        raise ValueError(f"labels must be 2D (y, x), got shape {data.shape}")
    levels = labels_pyramid(data, min_side)
    os.makedirs(store_path, exist_ok=True)
    _write_json(os.path.join(store_path, ".zgroup"), {"zarr_format": 2})
    datasets = [
        {
            "path": str(i),
            "coordinateTransformations": [{"type": "scale", "scale": [2.0**i, 2.0**i]}],
        }
        for i in range(len(levels))
    ]
    _write_json(
        os.path.join(store_path, ".zattrs"),
        {
            "multiscales": [
                {
                    "version": "0.4",
                    "name": name,
                    "axes": [{"name": "y", "type": "space"}, {"name": "x", "type": "space"}],
                    "datasets": datasets,
                    "type": "nearest",
                    "metadata": {
                        "description": "2x nearest-neighbour downsampling of y and x per level",
                        "method": "depictio labels TIFF conversion",
                        "version": LABELS_CONVERSION_VERSION,
                    },
                }
            ],
            "image-label": {"version": "0.4"},
        },
    )
    for i, level in enumerate(levels):
        _write_level(os.path.join(store_path, str(i)), level, chunk)
    return store_path


def convert_labels_tiff(tiff_path: str, store_path: str, name: str) -> str:
    """Read the mask at ``tiff_path`` and write its labels store at ``store_path``."""
    return write_labels_ome_zarr(read_labels_tiff(tiff_path), store_path, name)
