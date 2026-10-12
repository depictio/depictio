"""Add the segmentation masks of the multi-sample example, without regenerating it.

``make_examples.py`` writes ``multi_sample/labels/<sample>_mask.tif`` and the
``label`` column of ``multi_sample/cells.csv`` as part of a full run. This
script derives the same two things from the stores already on disk (no
download): it reads level 0 of each ``multi_sample/<sample>.zarr``, segments
it with the same ``segment_nuclei`` call, writes the mask through the same
``write_labels_mask`` and adds ``label`` to the cells table. It refuses to
write anything when the nuclei it finds do not match the table row for row
(count, centroid, area), so the mask ids always name the table's cells.

Run it from the repo root with throwaway dependencies:

    uv run --no-project --python 3.12 \\
        --with scikit-image --with tifffile --with "zarr<3" \\
        python dev/bioimage/make_labels_example.py \\
        --out depictio/projects/init/bioimage_examples/data
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from make_examples import segment_nuclei, write_labels_mask  # noqa: E402
from skimage import measure  # noqa: E402


def read_level0(store: Path) -> np.ndarray:
    """Level 0 of a zlib-compressed NGFF 0.4 store (``c, y, x``, ``/`` separator), channel 0."""
    meta = json.loads((store / "0" / ".zarray").read_text())
    assert meta["compressor"]["id"] == "zlib" and meta.get("dimension_separator") == "/"
    _, height, width = meta["shape"]
    _, cy, cx = meta["chunks"]
    dtype = np.dtype(meta["dtype"])
    out = np.zeros((height, width), dtype=dtype)
    for iy in range(-(-height // cy)):
        for ix in range(-(-width // cx)):
            path = store / "0" / "0" / str(iy) / str(ix)
            if not path.exists():
                continue
            block = np.frombuffer(zlib.decompress(path.read_bytes()), dtype=dtype)
            block = block.reshape(cy, cx)
            h = min(cy, height - iy * cy)
            w = min(cx, width - ix * cx)
            out[iy * cy : iy * cy + h, ix * cx : ix * cx + w] = block[:h, :w]
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, required=True, help="bioimage_examples data directory")
    args = p.parse_args(argv)
    folder = args.out / "multi_sample"
    cells_path = folder / "cells.csv"
    with cells_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        header = [c for c in (reader.fieldnames or []) if c != "label"]
        rows = list(reader)

    by_sample: dict[str, list[dict]] = {}
    for row in rows:
        by_sample.setdefault(row["sample"], []).append(row)

    masks = {}
    for sample, sample_rows in sorted(by_sample.items()):
        tile = read_level0(folder / f"{sample}.zarr")
        labels = segment_nuclei(tile, min_size=15, min_distance=4)
        props = measure.regionprops(labels)
        if len(props) != len(sample_rows):
            raise SystemExit(f"{sample}: {len(props)} nuclei, table has {len(sample_rows)}")
        for i, (prop, row) in enumerate(zip(props, sample_rows), start=1):
            y, x = prop.centroid
            if (
                row["cell_id"] != f"{sample}_{i:04d}"
                or abs(float(row["x"]) - x) > 0.01
                or abs(float(row["y"]) - y) > 0.01
                or int(row["area_px"]) != prop.area
            ):
                raise SystemExit(f"{sample}: nucleus {i} does not match {row['cell_id']}")
        masks[sample] = labels

    # Labels run across samples in table order, as make_examples numbers them.
    offsets: dict[str, int] = {}
    for n, row in enumerate(rows, start=1):
        offsets.setdefault(row["sample"], n - 1)
        row["label"] = str(n)
    for sample, labels in masks.items():
        path, _ = write_labels_mask(folder, sample, labels, offset=offsets[sample])
        print(f"  {path.relative_to(args.out)}  {path.stat().st_size / 1e3:6.1f} kB")

    out_header = [header[0], "label", *header[1:]]
    with cells_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {cells_path.relative_to(args.out)}  label column added")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
