"""Generate the whole-slide example of ``projects/init/bioimage_examples``.

A mouse H&E whole slide from the JAX KOMP histopathology collection, converted
to OME-Zarr 0.5 for the OME 2024 NGFF challenge and hosted by JAX (CC BY 4.0,
https://images.jax.org/webclient/?show=image-176894):

    https://storage.googleapis.com/jax-public-ngff/public/42815.zarr

Level 0 is 55296 x 96000 RGB at 0.45 um (about 16 GB uncompressed), in seven
levels. The dashboard reads it in place and never copies it: an overview tile
shows a coarse level, and a detail tile streams full resolution only for the
region picked on the overview.

No cell table is published with the slide, so this script writes a table of
square tissue patches instead, the unit computational pathology usually works
on. ``wsi_patches.csv`` holds one row per patch with tissue in it:

* where it is, in level-0 pixels (centre, width, height) and in micrometres;
* which tissue section it belongs to (connected tissue regions, numbered left
  to right, top to bottom);
* stain measures from colour deconvolution (Ruifrok and Johnston's H&E
  vectors): mean hematoxylin and eosin optical density over the tissue, and
  the fraction of tissue pixels dominated by hematoxylin, a proxy for how
  densely nucleated the patch is.

They are computed on level 3 (3.6 um per pixel). That is too coarse to count
nuclei, which is why the table gives stain densities and not cell counts.

Run from the repo root with throwaway dependencies (the level read is about
250 MB):

    uv run --no-project --python 3.12 --with numpy --with scipy \\
        --with "zarr>=3.1" --with fsspec --with aiohttp --with requests \\
        python -I dev/bioimage/make_wsi_patches.py \\
        --out depictio/projects/init/bioimage_examples/data
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import zarr
from scipy import ndimage

SLIDE_URL = "https://storage.googleapis.com/jax-public-ngff/public/42815.zarr"
#: bioformats2raw layout: the image is series 0.
IMAGE_PATH = "0"
LEVEL = "3"
#: Patch side in micrometres.
PATCH_UM = 500.0
#: A patch is kept when at least this share of it is tissue.
MIN_TISSUE = 0.2
#: Ruifrok and Johnston's stain vectors (rows: hematoxylin, eosin, DAB).
HED = np.array([[0.650, 0.704, 0.286], [0.072, 0.990, 0.105], [0.268, 0.570, 0.776]])


def read_level(url: str) -> tuple[np.ndarray, float, float]:
    """The RGB plane of level ``LEVEL`` (y, x, 3) and its pixel size and level-0 pixel size, in um."""
    group = zarr.open_group(f"{url}/{IMAGE_PATH}", mode="r")
    datasets = group.attrs["ome"]["multiscales"][0]["datasets"]
    scales = {d["path"]: d["coordinateTransformations"][0]["scale"][-1] for d in datasets}
    plane = np.asarray(group[LEVEL][0, :, 0])
    return np.moveaxis(plane, 0, -1), scales[LEVEL], scales["0"]


def optical_density(rgb: np.ndarray) -> np.ndarray:
    """Per-pixel hematoxylin, eosin and residual optical densities."""
    od = -np.log(np.clip(rgb.astype(np.float32), 1, 255) / 255.0)
    return od.reshape(-1, 3) @ np.linalg.inv(HED / np.linalg.norm(HED, axis=1, keepdims=True))


def tissue_mask(rgb: np.ndarray) -> np.ndarray:
    """Tissue against the bright, unsaturated glass background."""
    rgb = rgb.astype(np.float32)
    saturation = rgb.max(-1) - rgb.min(-1)
    mask = (saturation > 25) & (rgb.mean(-1) < 225)
    mask = ndimage.binary_opening(mask, iterations=2)
    return ndimage.binary_fill_holes(ndimage.binary_closing(mask, iterations=3))


def sections(mask: np.ndarray, min_px: int) -> np.ndarray:
    """Connected tissue regions above ``min_px``, numbered by column band then row."""
    labels, n = ndimage.label(ndimage.binary_dilation(mask, iterations=30))
    labels = np.where(mask, labels, 0)
    sizes = ndimage.sum(np.ones_like(labels), labels, index=np.arange(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= min_px]
    centres = ndimage.center_of_mass(np.ones_like(labels), labels, keep)
    width = mask.shape[1]
    # Two slides side by side: left one first, then top to bottom, left to right.
    order = sorted(
        zip(keep, centres),
        key=lambda kc: (kc[1][1] > width / 2, round(kc[1][0] / (mask.shape[0] / 4)), kc[1][1]),
    )
    out = np.zeros_like(labels)
    for number, (label, _) in enumerate(order, start=1):
        out[labels == label] = number
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="the example's data folder")
    parser.add_argument("--url", default=SLIDE_URL)
    args = parser.parse_args()
    out = args.out / "wsi"
    out.mkdir(parents=True, exist_ok=True)

    rgb, pixel_um, level0_um = read_level(args.url)
    print(f"level {LEVEL}: {rgb.shape} at {pixel_um:.3f} um")
    mask = tissue_mask(rgb)
    patch_px = int(round(PATCH_UM / pixel_um))
    section_map = sections(mask, min_px=patch_px * patch_px * 4)
    od = optical_density(rgb).reshape(*rgb.shape[:2], 3)
    ratio = pixel_um / level0_um

    rows = []
    ny, nx = rgb.shape[0] // patch_px, rgb.shape[1] // patch_px
    for r in range(ny):
        for c in range(nx):
            window = np.s_[r * patch_px : (r + 1) * patch_px, c * patch_px : (c + 1) * patch_px]
            tissue = mask[window]
            fraction = float(tissue.mean())
            if fraction < MIN_TISSUE:
                continue
            labels = section_map[window][tissue]
            labels = labels[labels > 0]
            if labels.size == 0:
                continue
            h, e = od[window][..., 0][tissue], od[window][..., 1][tissue]
            x0, y0 = c * patch_px * ratio, r * patch_px * ratio
            side = patch_px * ratio
            rows.append(
                {
                    "patch": f"r{r:03d}_c{c:03d}",
                    "section": f"S{int(np.bincount(labels).argmax()):02d}",
                    "x_px": round(x0 + side / 2, 1),
                    "y_px": round(y0 + side / 2, 1),
                    "box_w_px": round(side, 1),
                    "box_h_px": round(side, 1),
                    "x_um": round((x0 + side / 2) * level0_um, 1),
                    "y_um": round((y0 + side / 2) * level0_um, 1),
                    "tissue_fraction": round(fraction, 3),
                    "hematoxylin_od": round(float(h.mean()), 4),
                    "eosin_od": round(float(e.mean()), 4),
                    "h_dominant_fraction": round(float((h > e).mean()), 3),
                }
            )
    with open(out / "wsi_patches.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    n_sections = len({row["section"] for row in rows})
    print(f"{len(rows)} patches of {PATCH_UM:.0f} um over {n_sections} sections")


if __name__ == "__main__":
    main()
