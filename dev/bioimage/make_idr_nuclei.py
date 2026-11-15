"""Per-nucleus table for the remote IDR example, one z plane of its label image.

The remote tab's viewer draws its points on one plane (the one it opens on),
so the table holds the nuclei that plane cuts. Each row is one label of
`labels/0`, with its in-plane centroid and area, and the mean LaminB1 and Dapi
intensity under it.

Run from the repository root (the store is read over HTTPS, nothing is written
to it):

    uv run --no-project --python 3.12 --with "zarr<3" --with fsspec \
        --with aiohttp --with numpy \
        python dev/bioimage/make_idr_nuclei.py \
        --out depictio/projects/init/bioimage_examples/data/idr_laminb1_nuclei.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import zarr

STORE = "https://uk1s3.embassy.ebi.ac.uk/idr/zarr/v0.4/idr0062A/6001240.zarr"
# The plane the viewer opens on: `omero.rdefs.defaultZ` in the store (0-based).
DEFAULT_Z = 118
# Channel order in the store's omero block: LaminB1, then Dapi.
LAMIN, DAPI = 0, 1


def build_rows(z: int) -> list[dict[str, float | int]]:
    image = zarr.open_array(zarr.storage.FSStore(f"{STORE}/0", mode="r"))
    labels = zarr.open_array(zarr.storage.FSStore(f"{STORE}/labels/0/0", mode="r"))
    # Label array is (t, z, y, x); image is (c, z, y, x). Both at level 0.
    plane_labels = np.asarray(labels[0, z]).astype(np.int64)
    lamin = np.asarray(image[LAMIN, z]).astype(np.float64)
    dapi = np.asarray(image[DAPI, z]).astype(np.float64)

    ids = np.unique(plane_labels)
    ids = ids[ids != 0]
    rows: list[dict[str, float | int]] = []
    rows_idx, cols_idx = np.indices(plane_labels.shape)
    for nucleus in ids:
        mask = plane_labels == nucleus
        area = int(mask.sum())
        rows.append(
            {
                "nucleus_id": int(nucleus),
                "x": round(float(cols_idx[mask].mean()), 2),
                "y": round(float(rows_idx[mask].mean()), 2),
                "area_px": area,
                "lamin_b1_mean": round(float(lamin[mask].mean()), 2),
                "dapi_mean": round(float(dapi[mask].mean()), 2),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--z", type=int, default=DEFAULT_Z, help="0-based plane index")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = build_rows(args.z)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} nuclei on z={args.z} -> {args.out}")


if __name__ == "__main__":
    main()
