"""Generate the HCS plate and the shape gallery of ``projects/init/bioimage_examples``.

Both are synthetic and small, made to exercise the viewer rather than to look
like a real screen:

* ``hcs_plate.zarr``: an OME-Zarr NGFF 0.4 plate, 2 rows x 3 columns, one field
  per well, two channels (DNA, GFP). The cell count falls and the GFP signal
  rises with the dose a column gets, so a well picked in the plate table shows
  a visibly different image. ``hcs_wells.csv`` holds one row per well,
  ``hcs_cells.csv`` one row per cell with its well, centroid and intensities.
* ``shapes/shape_*.zarr``: one NGFF 0.4 store per axis layout the viewer reads
  (YX, ZYX, TYX, TCZYX, float32 CYX, 8 channels), plus one it does not
  (``shape_yxc``: channel axis last, off the spec), which the ingest's NGFF check
  flags and the viewer refuses with its axes named. ``shapes/shapes.csv`` is the
  sample sheet a filter picks a store from.

Run from the repo root with throwaway dependencies:

    uv run --no-project --python 3.12 --with numpy --with "zarr<3" \\
        python dev/bioimage/make_plate_and_shapes.py \\
        --out depictio/projects/init/bioimage_examples/data

Output is deterministic for a given ``--seed``.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import numpy as np
import zarr
from numcodecs import Blosc

NGFF = "0.4"
COMPRESSOR = Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)
PIXEL_UM = 0.65

ROWS = ["A", "B"]
COLUMNS = ["1", "2", "3"]
# Dose per column: the plate's one experimental factor.
DOSE_UM = {"1": 0.0, "2": 1.0, "3": 10.0}
TREATMENT = {"1": "DMSO", "2": "drug 1 uM", "3": "drug 10 uM"}
CELLS_PER_DOSE = {"1": 42, "2": 28, "3": 14}
FIELD = 192

AXES = {
    "t": {"name": "t", "type": "time", "unit": "second"},
    "c": {"name": "c", "type": "channel"},
    "z": {"name": "z", "type": "space", "unit": "micrometer"},
    "y": {"name": "y", "type": "space", "unit": "micrometer"},
    "x": {"name": "x", "type": "space", "unit": "micrometer"},
}


def _scale(axes: str, factor: int) -> list[float]:
    return [PIXEL_UM * factor if a in "yx" else 1.0 for a in axes]


def _downsample(arr: np.ndarray, axes: str) -> np.ndarray:
    """Every other pixel along y and x."""
    index = tuple(slice(None, None, 2) if a in "yx" else slice(None) for a in axes)
    return arr[index]


def write_image(
    group: zarr.Group,
    arr: np.ndarray,
    axes: str,
    *,
    channels: list[tuple[str, str]] | None = None,
    levels: int = 2,
    axes_meta: list[dict] | None = None,
) -> None:
    """An NGFF 0.4 multiscale image at ``group``: ``levels`` levels, halving y and x."""
    datasets = []
    level = arr
    for i in range(levels):
        chunks = tuple(min(s, 64) if a in "yx" else 1 for a, s in zip(axes, level.shape))
        group.create_dataset(
            str(i),
            data=level,
            chunks=chunks,
            compressor=COMPRESSOR,
            dimension_separator="/",
            overwrite=True,
        )
        datasets.append(
            {
                "path": str(i),
                "coordinateTransformations": [{"type": "scale", "scale": _scale(axes, 2**i)}],
            }
        )
        if i + 1 < levels:
            level = _downsample(level, axes)
    attrs: dict = {
        "multiscales": [
            {
                "version": NGFF,
                "name": group.basename or "image",
                "axes": axes_meta or [AXES[a] for a in axes],
                "datasets": datasets,
            }
        ]
    }
    if channels:
        c = axes.index("c") if "c" in axes else None
        windows = []
        for ci in range(len(channels)):
            plane = arr.take(ci, axis=c) if c is not None else arr
            lo, hi = float(np.percentile(plane, 1)), float(np.percentile(plane, 99.5))
            windows.append((lo, hi if hi > lo else lo + 1, float(plane.min()), float(plane.max())))
        attrs["omero"] = {
            "channels": [
                {
                    "label": label,
                    "color": color,
                    "active": True,
                    "window": {"start": w[0], "end": w[1], "min": w[2], "max": w[3]},
                }
                for (label, color), w in zip(channels, windows)
            ],
            "rdefs": {"model": "color"},
        }
    group.attrs.update(attrs)


def _blob(shape: tuple[int, int], cy: float, cx: float, r: float) -> np.ndarray:
    yy, xx = np.mgrid[: shape[0], : shape[1]]
    return np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * r**2)))


# ---- HCS plate --------------------------------------------------------------


def make_plate(out: Path, rng: np.random.Generator) -> None:
    path = out / "hcs_plate.zarr"
    shutil.rmtree(path, ignore_errors=True)
    root = zarr.open_group(str(path), mode="w")
    wells_meta = []
    well_rows: list[dict] = []
    cell_rows: list[dict] = []
    cell_id = 0
    for ri, row in enumerate(ROWS):
        for ci, col in enumerate(COLUMNS):
            wells_meta.append({"path": f"{row}/{col}", "rowIndex": ri, "columnIndex": ci})
            well = root.require_group(row).require_group(col)
            well.attrs["well"] = {"version": NGFF, "images": [{"path": "0", "acquisition": 0}]}
            n = CELLS_PER_DOSE[col] + int(rng.integers(-3, 4))
            dna = np.zeros((FIELD, FIELD), float)
            gfp = np.zeros((FIELD, FIELD), float)
            gfp_level = 0.25 + 0.06 * DOSE_UM[col]
            name = f"{row}{col}"
            for _ in range(n):
                cy, cx = rng.uniform(12, FIELD - 12, 2)
                r = rng.uniform(3.5, 6.0)
                nucleus = _blob((FIELD, FIELD), cy, cx, r)
                cyto = _blob((FIELD, FIELD), cy, cx, r * 2.2)
                dna += nucleus * rng.uniform(0.7, 1.0)
                g = gfp_level * rng.uniform(0.7, 1.3)
                gfp += cyto * g
                cell_id += 1
                cell_rows.append(
                    {
                        "cell_id": cell_id,
                        "well": name,
                        "x": round(float(cx), 1),
                        "y": round(float(cy), 1),
                        "area_px": int(round(np.pi * (r * 1.6) ** 2)),
                        "dna_mean": round(float(rng.uniform(0.7, 1.0) * 3000), 1),
                        "gfp_mean": round(float(g * 4000), 1),
                    }
                )
            noise = rng.normal(0, 0.02, (2, FIELD, FIELD))
            stack = np.stack([dna, gfp]) + noise
            img = np.clip(stack * 3000 + 200, 0, 65535).astype(np.uint16)
            write_image(
                well.require_group("0"),
                img,
                "cyx",
                channels=[("DNA", "0000FF"), ("GFP", "00FF00")],
            )
            well_rows.append(
                {
                    "well": name,
                    "row": row,
                    "column": int(col),
                    "treatment": TREATMENT[col],
                    "dose_um": DOSE_UM[col],
                    "n_cells": n,
                    "gfp_mean": round(
                        float(np.mean([c["gfp_mean"] for c in cell_rows if c["well"] == name])), 1
                    ),
                }
            )
    root.attrs["plate"] = {
        "version": NGFF,
        "name": "demo plate",
        "rows": [{"name": r} for r in ROWS],
        "columns": [{"name": c} for c in COLUMNS],
        "wells": wells_meta,
        "field_count": 1,
        "acquisitions": [{"id": 0, "name": "demo"}],
    }
    _write_csv(out / "hcs_wells.csv", well_rows)
    _write_csv(out / "hcs_cells.csv", cell_rows)


# ---- Shape gallery ------------------------------------------------------------


def make_shapes(out: Path, rng: np.random.Generator) -> None:
    folder = out / "shapes"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    n = 96
    yy, xx = np.mgrid[:n, :n]
    rings = (np.sin(np.hypot(yy - n / 2, xx - n / 2) / 3) + 1) / 2
    sheet: list[dict] = []

    def store(name: str, arr: np.ndarray, axes: str, note: str, **kw) -> None:
        group = zarr.open_group(str(folder / f"{name}.zarr"), mode="w")
        write_image(group, arr, axes, **kw)
        sheet.append(
            {
                "sample": name,
                "axes": axes.upper(),
                "shape": "x".join(str(s) for s in arr.shape),
                "dtype": str(arr.dtype),
                "note": note,
            }
        )

    store("shape_yx", (rings * 255).astype(np.uint8), "yx", "one plane, no channel axis")
    sphere = np.stack(
        [
            (np.hypot(yy - n / 2, xx - n / 2) < 6 + 2.5 * abs(z - 8)).astype(np.uint8) * 200
            for z in range(16)
        ]
    )
    store("shape_zyx", sphere, "zyx", "a 16-plane stack: Z slider")
    moving = np.stack([_blob((n, n), n / 2, 10 + 5 * t, 6) for t in range(15)])
    store("shape_tyx", (moving * 4000).astype(np.uint16), "tyx", "15 time points: Time slider and play")
    tczyx = np.stack(
        [
            np.stack(
                [
                    np.stack([_blob((64, 64), 32, 16 + 8 * t, 3 + abs(z - 4)) for z in range(8)]),
                    np.stack([_blob((64, 64), 16 + 8 * t, 32, 3 + abs(z - 4)) for z in range(8)]),
                ]
            )
            for t in range(4)
        ]
    )
    store(
        "shape_tczyx",
        (tczyx * 3000).astype(np.uint16),
        "tczyx",
        "every axis: 4 times, 2 channels, 8 planes",
        channels=[("moving x", "FF00FF"), ("moving y", "00FFFF")],
    )
    phase = np.stack([np.sin(xx / 7) * np.cos(yy / 9), np.cos(np.hypot(yy, xx) / 6)])
    store(
        "shape_float32",
        phase.astype(np.float32),
        "cyx",
        "float32 values in [-1, 1]: contrast from the data range",
        channels=[("phase", "FFFFFF"), ("ripple", "FFFF00")],
    )
    colours = ["0000FF", "00FF00", "FF0000", "FF00FF", "00FFFF", "FFFF00", "FF8800", "8800FF"]
    eight = np.stack(
        [
            _blob((n, n), n / 2 + 30 * np.sin(k * np.pi / 4), n / 2 + 30 * np.cos(k * np.pi / 4), 9)
            for k in range(8)
        ]
    )
    store(
        "shape_8ch",
        (eight * 3000).astype(np.uint16),
        "cyx",
        "8 channels: at most 6 show at once, the rest wait their turn",
        channels=[(f"marker {k + 1}", colours[k]) for k in range(8)],
    )
    # Off the spec on purpose: the channel axis after the spatial ones.
    yxc = np.stack([rings, rings[::-1]], axis=-1)
    store(
        "shape_yxc",
        (yxc * 255).astype(np.uint8),
        "yxc",
        "channel axis last: off the NGFF spec, flagged at ingest and refused by the viewer",
    )
    _write_csv(folder / "shapes.csv", sheet)


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    make_plate(args.out, rng)
    make_shapes(args.out, rng)
    print(json.dumps({"plate": "hcs_plate.zarr", "shapes": "shapes/"}))


if __name__ == "__main__":
    main()
