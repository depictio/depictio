"""Generate the registration example of ``projects/init/bioimage_examples``.

A synthetic image registration, written the way elastix or ANTs leave one: for
each of two samples, the fixed image and the moving image resampled into the
fixed frame after each step (no correction, rigid, affine, B-spline), plus a
table with one row per sample and step holding the quality metrics.

* ``registration/{sample}_fixed.zarr``: a tissue-like image, 384 x 384, two
  channels (nuclei: blobs, membranes: the ridges between neighbouring cells),
  OME-Zarr NGFF 0.4 with two pyramid levels. Different for each sample.
* ``registration/{sample}_{raw,rigid,affine,bspline}.zarr``: the moving image
  in the fixed frame after that step. The moving image is the fixed one under a
  known transform (a 10 to 15 degree rotation, a translation, anisotropic
  scale and shear, and a smooth non-linear displacement of up to about 12 px).
  Each step corrects more of it, so a step store is the fixed image warped by
  what that step left over (its *residual* transform), which is also what the
  metrics are computed from. Every store of a sample shares the fixed image's
  contrast window, so steps compare at a glance.
* ``registration/registration_steps.csv``: ``ncc`` (normalised
  cross-correlation of channel 0 against the fixed one), ``tre_px`` (mean target
  registration error over 20 landmarks, from the residual transform),
  ``folding_pct`` (share of pixels where the Jacobian determinant of the
  residual displacement is <= 0; 0 for the steps that are not B-spline) and a
  synthetic ``runtime_s``.

``embryo_b`` is a failed case: its affine step gets the shear the wrong way
round, which leaves it further from the fixed image than the rigid step, and
its B-spline step recovers only part of that and folds the image in one place.

Run from the repo root with throwaway dependencies:

    uv run --no-project --python 3.12 --with numpy --with scipy --with "zarr<3" \\
        python dev/bioimage/make_registration_example.py \\
        --out depictio/projects/init/bioimage_examples/data

Output is deterministic for a given ``--seed``.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zarr
from numcodecs import Blosc
from scipy import ndimage
from scipy.spatial import cKDTree

NGFF = "0.4"
COMPRESSOR = Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)
PIXEL_UM = 0.5
SIZE = 384
BACKGROUND = 200.0
CHANNELS = [("Nuclei", "00FFFF"), ("Membranes", "FFFF00")]
STEPS = ["raw", "rigid", "affine", "bspline"]
TRANSFORM = {"raw": "none", "rigid": "rigid", "affine": "affine", "bspline": "bspline"}
AXES = [
    {"name": "c", "type": "channel"},
    {"name": "y", "type": "space", "unit": "micrometer"},
    {"name": "x", "type": "space", "unit": "micrometer"},
]
CENTER = np.array([(SIZE - 1) / 2, (SIZE - 1) / 2])


@dataclass
class Sample:
    name: str
    seed: int
    n_cells: int
    ellipse: tuple[float, float, float]  # semi-axis y, semi-axis x, tilt (rad)
    theta_deg: float  # rotation of the moving image
    shift: tuple[float, float]  # translation (y, x), px
    scale: tuple[float, float]  # anisotropic scale (y, x)
    shear: float  # y += shear * x
    shear_error: float  # shear the affine step believes in (the true one when fine)
    bumps: list[tuple[float, float, float, float, float]]  # y, x, sigma, amp_y, amp_x
    bspline_leak: float  # share of the affine error the B-spline step cannot undo
    fold: tuple[float, float, float, float] | None  # y, x, sigma, amp_x: a fold-making bump


SAMPLES = [
    Sample(
        name="embryo_a",
        seed=11,
        n_cells=150,
        ellipse=(140.0, 165.0, 0.25),
        theta_deg=12.0,
        shift=(-17.0, 22.0),
        scale=(1.10, 0.90),
        shear=0.12,
        shear_error=0.12,
        bumps=[
            (150, 130, 45, 6.0, -4.0),
            (240, 250, 55, -5.0, 7.0),
            (120, 270, 38, 4.0, 3.0),
            (260, 120, 50, -3.0, -6.0),
        ],
        bspline_leak=0.0,
        fold=None,
    ),
    Sample(
        name="embryo_b",
        seed=23,
        n_cells=135,
        ellipse=(155.0, 135.0, -0.35),
        theta_deg=-14.0,
        shift=(20.0, 11.0),
        scale=(0.91, 1.09),
        shear=0.14,
        # Wrong sign: the affine step shears the image the other way.
        shear_error=-0.14,
        bumps=[
            (130, 150, 50, -7.0, 6.0),
            (230, 120, 42, 8.0, 3.0),
            (200, 260, 60, -4.0, -7.0),
            (110, 250, 36, 5.0, -4.0),
        ],
        bspline_leak=0.35,
        fold=(205.0, 175.0, 7.0, 18.0),
    ),
]


# ---- Writing -----------------------------------------------------------------


def _downsample(arr: np.ndarray) -> np.ndarray:
    return arr[:, ::2, ::2]


def write_image(
    path: Path, arr: np.ndarray, windows: list[tuple[float, float, float, float]]
) -> None:
    """An NGFF 0.4 multiscale CYX image at ``path``: two levels, halving y and x."""
    shutil.rmtree(path, ignore_errors=True)
    group = zarr.open_group(str(path), mode="w")
    datasets = []
    level = arr
    for i in range(2):
        group.create_dataset(
            str(i),
            data=level,
            chunks=(1, 64, 64),
            compressor=COMPRESSOR,
            dimension_separator="/",
            overwrite=True,
        )
        datasets.append(
            {
                "path": str(i),
                "coordinateTransformations": [
                    {"type": "scale", "scale": [1.0, PIXEL_UM * 2**i, PIXEL_UM * 2**i]}
                ],
            }
        )
        level = _downsample(level)
    group.attrs.update(
        {
            "multiscales": [
                {
                    "version": NGFF,
                    "name": path.stem,
                    "axes": AXES,
                    "datasets": datasets,
                }
            ],
            "omero": {
                "channels": [
                    {
                        "label": label,
                        "color": color,
                        "active": True,
                        "window": {"start": w[0], "end": w[1], "min": w[2], "max": w[3]},
                    }
                    for (label, color), w in zip(CHANNELS, windows)
                ],
                "rdefs": {"model": "color"},
            },
        }
    )


def window_of(arr: np.ndarray) -> list[tuple[float, float, float, float]]:
    out = []
    for plane in arr:
        lo, hi = float(np.percentile(plane, 1)), float(np.percentile(plane, 99.5))
        out.append((lo, hi if hi > lo else lo + 1, float(plane.min()), float(plane.max())))
    return out


# ---- The fixed image ----------------------------------------------------------


def make_fixed(sample: Sample, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """The fixed image (2, SIZE, SIZE) as floats, and the cell centres (n, 2) as (y, x)."""
    yy, xx = np.mgrid[:SIZE, :SIZE].astype(float)
    ay, ax, tilt = sample.ellipse
    dy, dx = yy - CENTER[0], xx - CENTER[1]
    u = dy * np.cos(tilt) + dx * np.sin(tilt)
    v = -dy * np.sin(tilt) + dx * np.cos(tilt)
    inside = (u / ay) ** 2 + (v / ax) ** 2
    tissue = 1.0 / (1.0 + np.exp((inside - 1.0) * 14.0))

    # Cell centres by rejection sampling inside the tissue, at least 12 px apart.
    seeds: list[tuple[float, float]] = []
    while len(seeds) < sample.n_cells:
        cy, cx = rng.uniform(20, SIZE - 20, 2)
        if tissue[int(cy), int(cx)] < 0.9:
            continue
        if seeds and np.min(np.hypot(*(np.array(seeds) - [cy, cx]).T)) < 12:
            continue
        seeds.append((cy, cx))
    centres = np.array(seeds)

    # Channel 0: one nucleus per cell, with its own size and brightness.
    nuclei = np.zeros((SIZE, SIZE))
    for cy, cx in centres:
        r = rng.uniform(2.8, 4.2)
        amp = rng.uniform(0.6, 1.0)
        y0, y1 = max(0, int(cy - 4 * r)), min(SIZE, int(cy + 4 * r) + 1)
        x0, x1 = max(0, int(cx - 4 * r)), min(SIZE, int(cx + 4 * r) + 1)
        gy, gx = np.mgrid[y0:y1, x0:x1]
        nuclei[y0:y1, x0:x1] += amp * np.exp(-(((gy - cy) ** 2 + (gx - cx) ** 2) / (2 * r**2)))

    # Channel 1: membranes, the ridges where two neighbouring cells are equally close.
    tree = cKDTree(centres)
    d, _ = tree.query(np.column_stack([yy.ravel(), xx.ravel()]), k=2)
    gap = (d[:, 1] - d[:, 0]).reshape(SIZE, SIZE)
    membranes = np.exp(-((gap / 1.6) ** 2)) * np.exp(-d[:, 0].reshape(SIZE, SIZE) / 14.0)
    membranes = ndimage.gaussian_filter(membranes, 0.8)

    # A slow intensity modulation, so a misregistration also shows in the shading.
    shade = ndimage.gaussian_filter(rng.normal(0, 1, (SIZE, SIZE)), 40)
    shade = 1.0 + 0.25 * shade / np.abs(shade).max()

    fixed = np.stack(
        [
            (nuclei * 2800 + 150 * membranes) * tissue * shade,
            (membranes * 2200 + 250 * nuclei) * tissue * shade,
        ]
    )
    fixed = fixed + BACKGROUND + rng.normal(0, 22, fixed.shape)
    return np.clip(fixed, 0, 65535), centres


# ---- Transforms ---------------------------------------------------------------
#
# Each step is a map from a pixel p of the fixed frame to the place Res(p) of the
# fixed image its output shows there. A perfect registration is the identity, so
# Res(p) - p is the displacement the step left over.


def _rot(deg: float) -> np.ndarray:
    t = np.deg2rad(deg)
    return np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])


def _affine_matrix(scale: tuple[float, float], shear: float) -> np.ndarray:
    return np.diag(scale) @ np.array([[1.0, shear], [0.0, 1.0]])


def _bumps(
    shape_points: np.ndarray, bumps: list[tuple[float, float, float, float, float]]
) -> np.ndarray:
    """Smooth non-linear displacement (n, 2): a sum of gaussian bumps."""
    out = np.zeros_like(shape_points)
    for cy, cx, sigma, ay, ax in bumps:
        w = np.exp(
            -(((shape_points[:, 0] - cy) ** 2 + (shape_points[:, 1] - cx) ** 2) / (2 * sigma**2))
        )
        out[:, 0] += ay * w
        out[:, 1] += ax * w
    return out


def residuals(
    sample: Sample, points: np.ndarray, rng: np.random.Generator
) -> dict[str, np.ndarray]:
    """``Res_k(points)`` for each step: where in the fixed image the step looks."""
    rel = points - CENTER
    k_true = _affine_matrix(sample.scale, sample.shear)
    # The estimate is never exact: a percent off in scale and shear.
    k_est = _affine_matrix(
        (sample.scale[0] * 1.01, sample.scale[1] * 0.99), sample.shear_error + 0.01
    )
    # What the affine step leaves of the linear part: K corrected by the K it estimated.
    k_left = k_true @ np.linalg.inv(k_est)
    u = _bumps(points, sample.bumps)

    out: dict[str, np.ndarray] = {}
    out["raw"] = CENTER + rel @ (_rot(sample.theta_deg) @ k_true).T + np.array(sample.shift) + u
    # The rigid step undoes the rotation and the translation, up to a little error.
    out["rigid"] = CENTER + rel @ (_rot(0.4) @ k_true).T + np.array([0.6, -0.4]) + u
    out["affine"] = CENTER + rel @ (_rot(0.15) @ k_left).T + np.array([0.3, 0.2]) + u

    # The B-spline step fits the non-linear field to a few tenths of it, and a
    # share of whatever the affine step got wrong. A smooth random field stands
    # for what a coarse grid cannot represent.
    grid = ndimage.gaussian_filter(rng.normal(0, 1, (2, SIZE, SIZE)), 18, axes=(1, 2))
    grid *= 1.2 / np.abs(grid).max()
    noise = np.stack(
        [ndimage.map_coordinates(grid[i], points.T, order=1, mode="nearest") for i in range(2)],
        axis=1,
    )
    affine_left = out["affine"] - points - u
    m = 0.12 * u + noise + sample.bspline_leak * affine_left
    if sample.fold:
        fy, fx, sigma, amp = sample.fold
        w = np.exp(-(((points[:, 0] - fy) ** 2 + (points[:, 1] - fx) ** 2) / (2 * sigma**2)))
        m[:, 1] += amp * w
    out["bspline"] = points + m
    return out


def warp(fixed: np.ndarray, res_grid: np.ndarray) -> np.ndarray:
    """The fixed image sampled at ``res_grid`` (SIZE, SIZE, 2), bilinear."""
    coords = np.moveaxis(res_grid, -1, 0)
    return np.stack(
        [
            ndimage.map_coordinates(ch, coords, order=1, mode="constant", cval=BACKGROUND)
            for ch in fixed
        ]
    )


# ---- Metrics -----------------------------------------------------------------


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a.ravel() - a.mean()
    b = b.ravel() - b.mean()
    return float(a @ b / np.sqrt((a @ a) * (b @ b)))


def folding_pct(res_grid: np.ndarray) -> float:
    """% of pixels whose Jacobian determinant is <= 0, for the displacement Res(p) - p."""
    yy, xx = np.mgrid[:SIZE, :SIZE].astype(float)
    ry, rx = res_grid[..., 0] - yy, res_grid[..., 1] - xx
    dry_dy, dry_dx = np.gradient(ry)
    drx_dy, drx_dx = np.gradient(rx)
    det = (1 + dry_dy) * (1 + drx_dx) - dry_dx * drx_dy
    return float(100.0 * np.mean(det <= 0))


# ---- Driver ------------------------------------------------------------------


def make_sample(out: Path, sample: Sample, rng: np.random.Generator) -> list[dict]:
    fixed, centres = make_fixed(sample, rng)
    windows = window_of(fixed)
    write_image(out / f"{sample.name}_fixed.zarr", np.round(fixed).astype(np.uint16), windows)

    yy, xx = np.mgrid[:SIZE, :SIZE].astype(float)
    grid_points = np.column_stack([yy.ravel(), xx.ravel()])
    # The residual transforms are random-field dependent: draw the field once for
    # the grid and read the landmarks from the same one.
    landmark_idx = rng.choice(len(centres), size=20, replace=False)
    landmarks = centres[landmark_idx]
    state = rng.bit_generator.state
    res_grid = residuals(sample, grid_points, rng)
    rng.bit_generator.state = state
    res_lm = residuals(sample, landmarks, rng)

    rows = []
    runtimes = {
        "raw": 0.0,
        "rigid": round(float(rng.uniform(3.0, 8.0)), 1),
        "affine": round(float(rng.uniform(10.0, 25.0)), 1),
        "bspline": round(float(rng.uniform(70.0, 140.0)), 1),
    }
    noise_rng = np.random.default_rng(sample.seed + 1000)
    for i, step in enumerate(STEPS):
        grid = res_grid[step].reshape(SIZE, SIZE, 2)
        img = warp(fixed, grid)
        img = img + noise_rng.normal(0, 14, img.shape)
        write_image(
            out / f"{sample.name}_{step}.zarr",
            np.round(np.clip(img, 0, 65535)).astype(np.uint16),
            windows,
        )
        rows.append(
            {
                "sample": sample.name,
                "step": step,
                "step_order": i,
                "transform": TRANSFORM[step],
                "store": f"{sample.name}_{step}.zarr",
                "fixed_store": f"{sample.name}_fixed.zarr",
                "ncc": f"{ncc(img[0], fixed[0]):.3f}",
                "tre_px": f"{np.mean(np.hypot(*(res_lm[step] - landmarks).T)):.2f}",
                "folding_pct": f"{folding_pct(grid) if step == 'bspline' else 0.0:.2f}",
                "runtime_s": f"{runtimes[step]:.1f}",
            }
        )
    return rows


def check_story(rows: list[dict]) -> None:
    """The data must say what the dashboard says: b fails at the affine step, a does not."""
    by = {(r["sample"], r["step"]): r for r in rows}
    for name in ("embryo_a", "embryo_b"):
        tre = [float(by[name, s]["tre_px"]) for s in STEPS]
        ncc_ = [float(by[name, s]["ncc"]) for s in STEPS]
        assert tre[0] > tre[1], (name, tre)
        if name == "embryo_a":
            assert tre == sorted(tre, reverse=True) and ncc_ == sorted(ncc_), (tre, ncc_)
            assert float(by[name, "bspline"]["folding_pct"]) == 0.0
        else:
            assert tre[2] > tre[1] and ncc_[2] < ncc_[1], (tre, ncc_)
            assert tre[3] < tre[2] and float(by[name, "bspline"]["folding_pct"]) > 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    folder = args.out / "registration"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    rows: list[dict] = []
    for sample in SAMPLES:
        rng = np.random.default_rng([args.seed, sample.seed])
        rows += make_sample(folder, sample, rng)
    check_story(rows)
    with (folder / "registration_steps.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"registration": "registration/", "rows": len(rows)}))


if __name__ == "__main__":
    main()
