"""The annotated crops of OpenOrganelle's jrc_hela-2, as a table, from metadata only.

jrc_hela-2 is a whole HeLa cell imaged by FIB-SEM (Janelia COSEM / OpenOrganelle,
CC BY 4.0): 12000 x 1600 x 6368 voxels (x, y, z) at 4 x 4 x 5.24 nm, about
122 GB of uint8, an OME-Zarr 0.4 pyramid of six levels on a public S3 bucket.
The Deep zoom tab reads it in place; nothing is copied.

Experts annotated organelles in small crops of it (2 nm voxels). Each crop is a
group under ``recon-1/labels/groundtruth/cropN/`` with one array per class;
each class array's ``.zattrs`` carries ``complement_counts`` (voxels where the
class is absent, or unknown). So the volume share of every organelle in every
crop is read from a few hundred small JSON files, without a single voxel.

Writes ``data/cosem/hela2_crops.csv``: one row per crop, its position and size
in the EM's level-0 pixels (to draw it as a box on the cell), its depth range,
and the share of the crop each organelle class fills.

Run from the repo root (stdlib only; it reads public JSON over https):

    python3 -I dev/bioimage/make_cosem_crops.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = "https://janelia-cosem-datasets.s3.amazonaws.com"
ROOT = "jrc_hela-2/jrc_hela-2.zarr/recon-1"
GROUNDTRUTH = f"{ROOT}/labels/groundtruth/"
# The EM's level-0 voxel size, nm (z, y, x), from its multiscales metadata.
EM_VOXEL_NM = (5.24, 4.0, 4.0)
# Organelle classes summarised per crop (CellMap class names). The full list
# has 63 classes, many of them parts (``mito_mem``, ``mito_lum``) of these.
CLASSES = {
    "mito": "Mitochondria",
    "er": "Endoplasmic reticulum",
    "nuc": "Nucleus",
    "golgi": "Golgi",
    "ves": "Vesicles",
    "endo": "Endosomes",
    "lyso": "Lysosomes",
    "ld": "Lipid droplets",
    "perox": "Peroxisomes",
    "mt": "Microtubules",
    "ecs": "Extracellular space",
}
OUT = Path("depictio/projects/init/bioimage_examples/data/cosem/hela2_crops.csv")


def get_json(path: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{BUCKET}/{path}", timeout=30) as res:  # noqa: S310
            return json.load(res)
    except Exception:
        return None


def list_prefixes(prefix: str) -> list[str]:
    url = f"{BUCKET}/?list-type=2&delimiter=/&prefix={prefix}"
    with urllib.request.urlopen(url, timeout=30) as res:  # noqa: S310
        text = res.read().decode()
    found = re.findall(r"<Prefix>([^<]*)</Prefix>", text)
    return [p for p in found if p != prefix]


def crop_row(crop_prefix: str) -> dict | None:
    crop = crop_prefix.rstrip("/").rsplit("/", 1)[1]
    present = {p.rstrip("/").rsplit("/", 1)[1] for p in list_prefixes(crop_prefix)}
    geometry = None
    shares: dict[str, float | None] = {}
    for cls in CLASSES:
        if cls not in present:
            shares[cls] = None
            continue
        attrs = get_json(f"{crop_prefix}{cls}/.zattrs")
        level = get_json(f"{crop_prefix}{cls}/s0/.zattrs")
        array = get_json(f"{crop_prefix}{cls}/s0/.zarray")
        if not attrs or not level or not array:
            shares[cls] = None
            continue
        if geometry is None:
            ds = attrs["multiscales"][0]["datasets"][0]["coordinateTransformations"]
            scale = next(t["scale"] for t in ds if t["type"] == "scale")
            translation = next(t["translation"] for t in ds if t["type"] == "translation")
            geometry = (array["shape"], scale, translation)
        counts = level["cellmap"]["annotation"].get("complement_counts") or {}
        total = 1
        for n in array["shape"]:
            total *= n
        unknown = counts.get("unknown", 0)
        known = total - unknown
        shares[cls] = None if known <= 0 else round(100 * (known - counts.get("absent", 0)) / known, 3)
    if geometry is None:
        return None
    (sz, sy, sx), (vz, vy, vx), (tz, ty, tx) = geometry
    ez, ey, ex = EM_VOXEL_NM
    row = {
        "crop": crop,
        # Box centre and size in the EM's level-0 pixels (4 nm).
        "x": round((tx + sx * vx / 2) / ex, 1),
        "y": round((ty + sy * vy / 2) / ey, 1),
        "box_w": round(sx * vx / ex, 1),
        "box_h": round(sy * vy / ey, 1),
        # The planes the crop spans (a crop can start a fraction of a plane
        # before the volume), and its middle plane.
        "z_first": max(0, int(tz // ez)),
        "z_last": int((tz + sz * vz) // ez),
        "z": max(0, int((tz + sz * vz / 2) // ez)),
        "width_um": round(sx * vx / 1000, 3),
        "height_um": round(sy * vy / 1000, 3),
        "depth_um": round(sz * vz / 1000, 3),
        "classes_annotated": len(present),
    }
    for cls, share in shares.items():
        row[f"{cls}_pct"] = share
    known = {c: s for c, s in shares.items() if s is not None and c != "ecs"}
    # The organelle filling most of the crop; a crop of background only (the
    # annotators' negative examples) is named for it.
    if known and max(known.values()) > 0:
        row["main_organelle"] = CLASSES[max(known, key=known.get)]
    else:
        row["main_organelle"] = CLASSES["ecs"] if shares.get("ecs") else "None annotated"
    return row


def main() -> int:
    crops = list_prefixes(GROUNDTRUTH)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(crop_row, crops) if r]
    rows.sort(key=lambda r: int(re.sub(r"\D", "", r["crop"]) or 0))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{OUT}: {len(rows)} crops of {len(crops)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
