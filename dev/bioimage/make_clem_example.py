"""Generate the CLEM example of ``projects/init/bioimage_examples``.

Correlative light and electron microscopy of one HeLa cell, from the CLEM-Reg
paper (Krentzel et al., Nature Methods 2025), all public and CC0:

* the EM volume, FIB-SEM at 5 nm isotropic (EMPIAR-10819, 965 x 7000 x 5938),
  which the dashboard reads in place from the BioImage Archive and never copies;
* the light microscopy of the same cell, four channels (DAPI, mitochondria,
  Golgi, lysosomes) imaged before the EM (BioImage Archive S-BIAD4355);
* the 150 landmark pairs the authors placed in BigWarp between the two
  (S-BSST707), 145 of them enabled.

What this script writes, under ``<out>/clem/``:

* ``lm_in_em.zarr``: the four LM channels resampled into the EM frame by the
  affine the enabled landmarks fit, on a coarse grid covering exactly the EM
  volume (19 x 437 x 371, 0.25 x 0.08 x 0.08 um), uint8, OME-Zarr NGFF 0.4.
  The bioimage viewer lays it over the EM tile as an overlay, stretched to the
  EM's extent.
* ``clem_landmarks.csv``: one row per landmark: its position in both images (um,
  and EM level-0 pixels), whether it was used for the fit or held out (the 5
  landmarks the authors disabled), and its residual after the affine. A held-out
  landmark's residual is the honest error; a fitted one's is optimistic.

The affine is refitted here by least squares (EM = A . LM + b) rather than read
from the paper, which used a non-linear warp: an affine is what a viewer can
apply, and its residuals are part of what the dashboard shows.

Run from the repo root with throwaway dependencies. The LM zips (134 MB) and
the landmarks CSV are downloaded into ``--cache`` when missing:

    uv run --no-project --python 3.12 --with numpy --with scipy \\
        --with "zarr<3" --with "numcodecs<0.16" \\
        python -I dev/bioimage/make_clem_example.py --cache /tmp/clem \\
        --out depictio/projects/init/bioimage_examples/data
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import zarr
from numcodecs import Blosc, GZip
from scipy import ndimage

LM_BASE = "https://ftp.ebi.ac.uk/pub/databases/biostudies/S-BIAD/355/S-BIAD4355/Files/clemreg_ome_zarr"
LANDMARKS_URL = (
    "https://ftp.ebi.ac.uk/biostudies/fire/S-BSST/707/S-BSST707/Files/"
    "EM04468_2_8T_landmarks_4%20local.csv"
)
#: The EM volume the dashboard reads in place (level 0: z, y, x at 5 nm).
EM_URL = "https://uk1s3.embassy.ebi.ac.uk/bia-integrator-data/EMPIAR-10819/IM1/IM1.zarr"
EM_SHAPE_ZYX = (965, 7000, 5938)
EM_PIXEL_UM = 0.005
#: LM level 0 voxel size (z, y, x), from the stores' own metadata.
LM_SCALE_ZYX = (0.13, 0.03527398325741549, 0.03527398325741549)
#: The overlay grid: the EM extent at about 0.08 um in plane (the EM's level 4)
#: and 0.25 um in depth, near the LM's optical section.
OVERLAY_SHAPE_ZYX = (19, 437, 371)
CHANNELS = [
    ("lm_dapi", "DAPI", "3D7FFF"),
    ("lm_mito", "Mitochondria", "FF2BD6"),
    ("lm_golgi", "Golgi", "35E05A"),
    ("lm_lyso", "Lysosomes", "FFB000"),
]
COMPRESSOR = Blosc(cname="zstd", clevel=7, shuffle=Blosc.BITSHUFFLE)
NGFF = "0.4"


def fetch(url: str, path: Path) -> Path:
    if not path.exists():
        print(f"downloading {url}")
        tmp = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(url) as response, open(tmp, "wb") as fh:
            shutil.copyfileobj(response, fh)
        tmp.rename(path)
    return path


def read_lm(zip_path: Path, name: str) -> np.ndarray:
    """Level ``s0`` of an LM store zip (z, y, x, big-endian uint16, gzip chunks)."""
    archive = zipfile.ZipFile(zip_path)
    root = f"{name}.ome.zarr/s0"
    meta = json.loads(archive.read(f"{root}/.zarray"))
    shape, chunks = meta["shape"], meta["chunks"]
    out = np.zeros(shape, dtype=np.float32)
    codec = GZip()
    for zi in range(0, shape[0], chunks[0]):
        for yi in range(0, shape[1], chunks[1]):
            for xi in range(0, shape[2], chunks[2]):
                key = f"{root}/{zi // chunks[0]}/{yi // chunks[1]}/{xi // chunks[2]}"
                try:
                    raw = codec.decode(archive.read(key))
                except KeyError:
                    continue  # an absent chunk is fill_value (0)
                block = np.frombuffer(raw, dtype=meta["dtype"]).reshape(chunks)
                target = out[zi : zi + chunks[0], yi : yi + chunks[1], xi : xi + chunks[2]]
                target[...] = block[: target.shape[0], : target.shape[1], : target.shape[2]]
    return out


def read_landmarks(path: Path) -> list[dict]:
    """BigWarp landmarks: name, enabled, moving (LM) x y z, fixed (EM) x y z, in um."""
    rows = []
    for row in csv.reader(open(path, newline="")):
        if len(row) < 8:
            continue
        rows.append(
            {
                "name": row[0],
                "enabled": row[1].strip().lower() == "true",
                "lm": [float(v) for v in row[2:5]],
                "em": [float(v) for v in row[5:8]],
            }
        )
    return rows


def fit_affine(landmarks: list[dict]) -> np.ndarray:
    """The 4 x 4 affine mapping LM um (x, y, z) to EM um, fitted on enabled landmarks."""
    used = [lm for lm in landmarks if lm["enabled"]]
    moving = np.array([lm["lm"] for lm in used])
    fixed = np.array([lm["em"] for lm in used])
    design = np.c_[moving, np.ones(len(moving))]
    solution, *_ = np.linalg.lstsq(design, fixed, rcond=None)
    affine = np.eye(4)
    affine[:3, :] = solution.T
    return affine


def resample(lm: np.ndarray, em_from_lm: np.ndarray, spacing_zyx: tuple[float, ...]) -> np.ndarray:
    """``lm`` (z, y, x) on the overlay grid of the EM frame."""
    lm_from_em = np.linalg.inv(em_from_lm)
    nz, ny, nx = OVERLAY_SHAPE_ZYX
    zz, yy, xx = np.meshgrid(
        (np.arange(nz) + 0.5) * spacing_zyx[0],
        (np.arange(ny) + 0.5) * spacing_zyx[1],
        (np.arange(nx) + 0.5) * spacing_zyx[2],
        indexing="ij",
    )
    em = np.stack([xx, yy, zz, np.ones_like(xx)]).reshape(4, -1)
    x, y, z = (lm_from_em @ em)[:3]
    coords = np.stack([z / LM_SCALE_ZYX[0], y / LM_SCALE_ZYX[1], x / LM_SCALE_ZYX[2]])
    return ndimage.map_coordinates(lm, coords, order=1, cval=0.0).reshape(OVERLAY_SHAPE_ZYX)


def to_uint8(volume: np.ndarray) -> np.ndarray:
    """0-255 between the 0.5 and 99.9 percentiles of the signal (zeros are outside the LM)."""
    signal = volume[volume > 0]
    lo, hi = (np.percentile(signal, [0.5, 99.9]) if signal.size else (0.0, 1.0))
    return np.clip((volume - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)


def write_overlay(path: Path, volume: np.ndarray, spacing_zyx: tuple[float, ...]) -> None:
    shutil.rmtree(path, ignore_errors=True)
    group = zarr.open_group(str(path), mode="w")
    group.create_dataset(
        "0",
        data=volume,
        chunks=(1, 1, *volume.shape[2:]),
        compressor=COMPRESSOR,
        dimension_separator="/",
        overwrite=True,
    )
    axes = [{"name": "c", "type": "channel"}] + [
        {"name": n, "type": "space", "unit": "micrometer"} for n in "zyx"
    ]
    windows = []
    for plane in volume:
        hi = float(np.percentile(plane[plane > 0], 99.5)) if (plane > 0).any() else 255.0
        windows.append((10.0, max(hi, 11.0)))
    group.attrs.update(
        {
            "multiscales": [
                {
                    "version": NGFF,
                    "name": "lm_in_em",
                    "axes": axes,
                    "datasets": [
                        {
                            "path": "0",
                            "coordinateTransformations": [
                                {"type": "scale", "scale": [1.0, *spacing_zyx]}
                            ],
                        }
                    ],
                }
            ],
            "omero": {
                "channels": [
                    {
                        "label": label,
                        "color": color,
                        # Two channels first: four colours added over the EM
                        # blur into one another.
                        "active": i < 2,
                        "window": {"start": w[0], "end": w[1], "min": 0, "max": 255},
                    }
                    for i, ((_, label, color), w) in enumerate(zip(CHANNELS, windows))
                ],
                "rdefs": {"model": "color", "defaultZ": OVERLAY_SHAPE_ZYX[0] // 2},
            },
        }
    )


def write_landmarks(path: Path, landmarks: list[dict], em_from_lm: np.ndarray) -> None:
    fields = [
        "landmark",
        "set",
        "lm_x_um",
        "lm_y_um",
        "lm_z_um",
        "em_x_um",
        "em_y_um",
        "em_z_um",
        "em_x_px",
        "em_y_px",
        "em_z_px",
        "residual_um",
    ]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for lm in landmarks:
            mapped = em_from_lm @ np.r_[lm["lm"], 1.0]
            residual = float(np.linalg.norm(mapped[:3] - np.array(lm["em"])))
            writer.writerow(
                {
                    "landmark": lm["name"],
                    "set": "fit" if lm["enabled"] else "held out",
                    **{f"lm_{a}_um": round(v, 4) for a, v in zip("xyz", lm["lm"])},
                    **{f"em_{a}_um": round(v, 4) for a, v in zip("xyz", lm["em"])},
                    **{f"em_{a}_px": round(v / EM_PIXEL_UM, 1) for a, v in zip("xyz", lm["em"])},
                    "residual_um": round(residual, 4),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cache", type=Path, required=True, help="where the downloads go")
    parser.add_argument("--out", type=Path, required=True, help="the example's data folder")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    out = args.out / "clem"
    out.mkdir(parents=True, exist_ok=True)

    landmarks = read_landmarks(fetch(LANDMARKS_URL, args.cache / "landmarks.csv"))
    em_from_lm = fit_affine(landmarks)
    extent_zyx = [n * EM_PIXEL_UM for n in EM_SHAPE_ZYX]
    spacing = tuple(e / n for e, n in zip(extent_zyx, OVERLAY_SHAPE_ZYX))

    channels = []
    for name, label, _ in CHANNELS:
        zip_path = fetch(f"{LM_BASE}/{name}.ome.zarr.zip", args.cache / f"{name}.ome.zarr.zip")
        channels.append(to_uint8(resample(read_lm(zip_path, name), em_from_lm, spacing)))
        print(f"{label}: resampled")
    write_overlay(out / "lm_in_em.zarr", np.stack(channels), spacing)
    write_landmarks(out / "clem_landmarks.csv", landmarks, em_from_lm)

    used = [lm for lm in landmarks if lm["enabled"]]
    print(f"affine fitted on {len(used)} of {len(landmarks)} landmarks (EM um from LM um):")
    print(np.array2string(em_from_lm[:3], precision=5, suppress_small=True))


if __name__ == "__main__":
    main()
