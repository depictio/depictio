"""Write the NGFF 0.5 (sharded) example store of ``projects/init/bioimage_examples``.

Kept apart from ``make_examples.py`` because it needs zarr 3, while the NGFF 0.4
stores there are written with zarr 2. ``make_examples.py`` runs this script in
its own throwaway environment (``uv run --with zarr==...``) and records what it
returns in the manifest; it can also be run on its own:

    uv run --no-project --python 3.12 \\
        --with "zarr==3.4.0" --with "ome-zarr>=0.12" --with scikit-image --with pooch \\
        python dev/bioimage/make_ngff05_example.py \\
        --out depictio/projects/init/bioimage_examples/data

The store is ``skimage.data.lily`` (a lily of the valley stem section): a
512 x 512 crop of its lower left part, with vascular bundles and the stem's
outer ring (the OME-TIFF example shows the middle 480 x 480), three of its four
channels kept at their full 12-bit depth (uint16), with a 3-level pyramid.
It is written as NGFF 0.5:

* zarr v3, a ``zarr.json`` per node, the OME metadata under
  ``attributes.ome`` (``version: "0.5"``, ``multiscales``, ``omero``) and
  ``dimension_names`` on every array;
* every array SHARDED (``sharding_indexed`` codec): one shard file per channel
  and ``--shard`` x ``--shard`` pixels holds ``--chunk`` x ``--chunk`` chunks,
  zstd-compressed (gzip would stamp the time into every chunk), with the shard
  index (and its crc32c) at the end of the file. A reader fetches the index
  with an HTTP Range request, then each chunk it needs by byte range.

The cells table follows the OME-TIFF example (``lily_stem``): the dark lumens
between the bright walls, segmented on all three channels, with a heuristic
wall type.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_examples import (  # noqa: E402
    LILY_XY_UM,
    build_pyramid,
    channel_window,
    segment_plant_cells,
    to_uint8,
    write_csv,
)

NGFF_VERSION = "0.5"
STORE = "lily_sharded"
# lily's channels carry no documented stain (see make_examples.LILY_CHANNELS).
# Ch3 is left out: it is a dimmer copy of Ch2.
CHANNELS = [
    {"index": 0, "label": "Ch1 (cell walls)", "short": "ch1", "color": "FF00FF"},
    {"index": 1, "label": "Ch2 (thick walls)", "short": "ch2", "color": "00FF00"},
    {"index": 3, "label": "Ch4 (cell walls)", "short": "ch4", "color": "00FFFF"},
]
# The repository's check-added-large-files hook caps one file at 500 kB; a
# shard is one file, so every shard stays under this.
MAX_FILE_BYTES = 480_000


def make_store(out: Path, args: argparse.Namespace) -> dict:
    import zarr
    from skimage import data, filters, measure
    from zarr.codecs import ZstdCodec

    if args.shard % args.chunk:
        raise SystemExit("--shard must be a multiple of --chunk")
    lily = data.lily()  # (y, x, 4) uint16, 12-bit
    y0, x0 = args.crop_origin
    crop = args.crop
    if y0 + crop > lily.shape[0] or x0 + crop > lily.shape[1]:
        raise SystemExit("--crop-origin + --crop leaves the lily image")
    window = lily[y0 : y0 + crop, x0 : x0 + crop, [c["index"] for c in CHANNELS]]
    image = np.ascontiguousarray(window.transpose(2, 0, 1))  # (c, y, x) uint16

    store = out / f"{STORE}.zarr"
    if store.exists():
        shutil.rmtree(store)
    axes = [
        {"name": "c", "type": "channel"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]
    root = zarr.open_group(store, mode="w", zarr_format=3)
    pyramid = build_pyramid(image, args.levels)
    datasets = []
    for level, arr in enumerate(pyramid):
        shards = (1, args.shard, args.shard)
        root.create_array(
            str(level),
            shape=arr.shape,
            dtype=arr.dtype,
            chunks=(1, args.chunk, args.chunk),
            shards=shards,
            compressors=ZstdCodec(level=args.clevel),
            fill_value=0,
            dimension_names=[a["name"] for a in axes],
        )[...] = arr
        px = LILY_XY_UM * (2**level)
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [{"type": "scale", "scale": [1.0, px, px]}],
            }
        )
    root.update_attributes(
        {
            "ome": {
                "version": NGFF_VERSION,
                "multiscales": [
                    {
                        "name": STORE,
                        "axes": axes,
                        "datasets": datasets,
                        "type": "local_mean",
                        "metadata": {
                            "description": "2x mean downsampling of y and x per level",
                            "method": "skimage.transform.downscale_local_mean",
                        },
                    }
                ],
                "omero": {
                    "id": 1,
                    "name": STORE,
                    "channels": [
                        {
                            "active": True,
                            "coefficient": 1,
                            "color": ch["color"],
                            "family": "linear",
                            "inverted": False,
                            "label": ch["label"],
                            "window": channel_window(image[i], image.dtype),
                        }
                        for i, ch in enumerate(CHANNELS)
                    ],
                    "rdefs": {"defaultT": 0, "defaultZ": 0, "model": "color"},
                },
            }
        }
    )
    # zarr writes its JSON metadata without a final newline, which the repo's
    # end-of-file-fixer hook would add on commit; adding it here keeps a
    # regenerated store identical to the committed one.
    for meta in store.rglob("zarr.json"):
        text = meta.read_text()
        if not text.endswith("\n"):
            meta.write_text(text + "\n")
    shard_files = _check_store(store, pyramid, args)

    # Cells: the lily_stem recipe (make_examples.segment_plant_cells) on the
    # brightest wall signal of the three channels, each scaled to its own
    # 0.5 / 99.8 percentiles.
    scaled = np.stack([to_uint8(ch, *np.percentile(ch, [0.5, 99.8])) for ch in image]).astype(
        np.float32
    )
    rings = segment_plant_cells(scaled.max(axis=0) / 255, args.min_cell, args.max_cell)
    props = measure.regionprops(rings, intensity_image=image.transpose(1, 2, 0))
    means = np.array([p.intensity_mean for p in props], dtype=float)
    # "Thick-walled" as in lily_stem: the Ch2 ring intensity, on the scale of
    # its own 99th percentile, above the Otsu cut of all cells.
    ch2 = means[:, 1] / np.percentile(image[1], 99)
    ch2_cut = filters.threshold_otsu(ch2)
    rows = []
    for i, (p, m, c2) in enumerate(zip(props, means, ch2, strict=True), start=1):
        y, x = p.centroid
        rows.append(
            [
                f"lsh_{i:04d}",
                STORE,
                round(float(x), 2),
                round(float(y), 2),
                int(p.area),
                round(float(p.area) * LILY_XY_UM**2, 2),
                *(round(float(v), 1) for v in m),
                "thick-walled" if c2 > ch2_cut else "thin-walled",
            ]
        )
    write_csv(
        out / f"{STORE}_cells.csv",
        [
            "cell_id",
            "sample",
            "x",
            "y",
            "area_px",
            "area_um2",
            *(f"mean_{c['short']}" for c in CHANNELS),
            "wall_type",
        ],
        rows,
    )
    files = [f for f in store.rglob("*") if f.is_file()]
    return {
        "store": f"{STORE}.zarr",
        "ngff_version": NGFF_VERSION,
        "chunk": args.chunk,
        "shard": args.shard,
        "shard_files": shard_files,
        "largest_file_bytes": max(f.stat().st_size for f in files),
        "bytes": sum(f.stat().st_size for f in files),
        "rows": len(rows),
        "zarr_version": zarr.__version__,
    }


def _check_store(store: Path, pyramid: list[np.ndarray], args: argparse.Namespace) -> int:
    """Zarr v3 + NGFF 0.5, every array sharded, pixels read back, files under the cap.

    Returns the number of shard files written.
    """
    import zarr

    if any(p.name in {".zattrs", ".zgroup", ".zarray"} for p in store.rglob(".z*")):
        raise RuntimeError(f"{store}: zarr v2 metadata written")
    meta = json.loads((store / "zarr.json").read_text())
    ome = meta["attributes"]["ome"]
    if meta["zarr_format"] != 3 or ome["version"] != NGFF_VERSION:
        raise RuntimeError(f"{store}: expected zarr v3 / NGFF {NGFF_VERSION}, got {meta}")
    root = zarr.open_group(store, mode="r")
    for level, (ds, expected) in enumerate(zip(ome["multiscales"][0]["datasets"], pyramid)):
        arr = root[ds["path"]]
        codec = json.loads((store / ds["path"] / "zarr.json").read_text())["codecs"][0]
        config = codec.get("configuration", {})
        if codec["name"] != "sharding_indexed" or config.get("index_location", "end") != "end":
            raise RuntimeError(f"{store}/{ds['path']}: not sharded with the index at the end")
        # zarrita (the viewer's zarr reader) strips a 4-byte checksum off the
        # index, so the index must end in crc32c.
        if [c["name"] for c in config["index_codecs"]] != ["bytes", "crc32c"]:
            raise RuntimeError(f"{store}/{ds['path']}: index codecs {config['index_codecs']}")
        if arr.shards != (1, args.shard, args.shard) or not np.array_equal(arr[...], expected):
            raise RuntimeError(f"{store}/{ds['path']}: level {level} does not read back")
    big = [f for f in store.rglob("*") if f.is_file() and f.stat().st_size > MAX_FILE_BYTES]
    if big:
        raise RuntimeError(f"{store}: files over {MAX_FILE_BYTES} bytes: {big}")
    _check_with_ome_zarr(store, len(pyramid))
    return sum(1 for f in store.rglob("*") if f.is_file() and f.name != "zarr.json")


def _check_with_ome_zarr(store: Path, levels: int) -> None:
    """Read the store back with ome-zarr-py when it is installed (0.12+ reads NGFF 0.5)."""
    try:
        from ome_zarr.io import parse_url
        from ome_zarr.reader import Multiscales, Reader
    except ImportError:
        print("  (ome-zarr not installed: skipping read-back validation)", file=sys.stderr)
        return
    location = parse_url(str(store))
    if location is None:
        raise RuntimeError(f"{store} is not a readable zarr location")
    image = list(Reader(location)())[0]
    if not any(isinstance(spec, Multiscales) for spec in image.specs):
        raise RuntimeError(f"{store}: no multiscales found by ome-zarr")
    if len(image.data) != levels:
        raise RuntimeError(f"{store}: {len(image.data)} levels, expected {levels}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, required=True, help="Output data directory")
    p.add_argument("--levels", type=int, default=3, help="Pyramid levels")
    p.add_argument("--chunk", type=int, default=128, help="Chunk edge along y and x")
    p.add_argument("--shard", type=int, default=256, help="Shard edge along y and x")
    p.add_argument("--clevel", type=int, default=19, help="zstd level of the chunks")
    p.add_argument("--crop", type=int, default=512, help="lily crop edge in pixels")
    p.add_argument("--crop-origin", type=int, nargs=2, default=(410, 0), metavar=("Y", "X"))
    p.add_argument("--min-cell", type=int, default=15, help="Smallest cell, in pixels")
    p.add_argument("--max-cell", type=int, default=4000, help="Largest cell, in pixels")
    p.add_argument(
        "--json", action="store_true", help="Print the result as one JSON line (for the caller)"
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    result = make_store(args.out, args)
    if args.json:
        print(json.dumps(result))
    else:
        print(
            f"  {result['store']:<34} {result['bytes'] / 1e6:6.2f} MB  {result['rows']:5d} "
            f"cells, {result['shard_files']} shard files, largest file "
            f"{result['largest_file_bytes'] / 1e3:.0f} kB (zarr {result['zarr_version']})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
