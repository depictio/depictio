"""Generate the "two magnifications" example of ``projects/init/bioimage_examples``.

HeLa cells from the MoBIE clem-example-project (https://github.com/mobie/clem-example-project,
``data/hela``): an EM overview of the whole section (34 nm per pixel, already OME-Zarr on
``s3.embl.de``, which the dashboard reads in place) and six high-magnification electron
tomograms (1.56 nm per pixel, 2024 x 2024 x 90-108 voxels each) acquired at known spots of it.
The tomograms exist only as BigDataViewer N5 on the same bucket.

What this script writes, under ``<out>/hela_tomo/``:

* ``tomo_<n>.zarr`` for three tomograms: OME-Zarr NGFF 0.4, axes z, y, x in micrometre, uint8,
  chunks (1, 256, 256), Blosc zstd, three levels (2x in y and x each). Each volume is the
  source N5 level 0 binned 4x in y and x (mean) and 4x in z (mean), so voxels are isotropic
  (6.23 nm), cut to the 18 central binned slices (72 of the 90-108 source slices, about
  110 nm of depth). More slices would not fit the size budget: binned noise barely compresses.
  Grey levels are stretched from the 0.5 and 99.5
  percentiles of the binned volume to 0-255, and the omero window spans the 1st and 99th
  percentile of the stretched data. The store keeps the tomogram's own pixel orientation.
* ``tomograms.csv``: one row for each of the six tomograms, converted or not, with where its
  footprint sits on the overview (centre and axis-aligned box, in overview level-0 pixels),
  the in-plane rotation of the footprint, and two numbers measured on the binned volume
  before the stretch, so they compare across tomograms.

Where a tomogram sits. MoBIE keeps every transform of a view as 3 x 4 affine matrices,
row-major, in micrometre, applied in the order the view lists them. The ``affine0`` of a
tomogram in ``dataset.json`` equals the BigDataViewer XML's own registration divided by the
voxel size (checked in ``footprint``, which stops when they differ), so a tomogram pixel
goes to the global frame by ``affine0 . diag(voxel size)`` and then by the view's manual
transforms. The MoBIE spec says view transforms apply "in addition to" the XML, which read
literally would apply the registration twice; this reading is the one that puts every
tomogram inside the overview, and ``--png`` renders the proof. The overview goes to the same
frame from its own micrometre frame by the view's MapScaleMat, Translation and manual shift.
A tomogram's footprint in overview pixels is therefore the inverse overview chain applied to
the tomogram's four corners, divided by the overview's 0.03412 um per pixel. The views used
are ``area3-tomos_37-41_54`` and ``area2-tomo_53`` of ``dataset.json``, the ones that show the
overview and the tomograms together. Half a pixel of origin convention (about 17 nm on the
overview) is ignored.

Run from the repo root with throwaway dependencies. ``dataset.json`` and the XMLs are
downloaded into ``--cache`` when missing, along with the binned volumes (about 0.5 GB of
N5 blocks is read for each tomogram, not kept). ``--png`` also renders the overview with the
boxes and a crop around each converted one next to its tomogram, which needs pillow and scipy:

    uv run --no-project --python 3.12 --with numpy --with scipy --with pillow \\
        --with "zarr<3" --with "numcodecs<0.16" \\
        python -I dev/bioimage/make_hela_tomograms.py --cache /tmp/hela \\
        --out depictio/projects/init/bioimage_examples/data --png /tmp/hela/check.png
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import shutil
import struct
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import zarr
from numcodecs import Blosc

RAW = "https://raw.githubusercontent.com/mobie/clem-example-project/main/data/hela"
BUCKET = "https://s3.embl.de/yeast-clem/hela/images"
OVERVIEW_URL = f"{BUCKET}/ome-zarr/em-overview.ome.zarr"
#: Overview level 0: shape (y, x) and micrometre per pixel, from its .zattrs / .zarray.
OVERVIEW_SHAPE_YX = (12040, 26112)
OVERVIEW_PIXEL_UM = 0.03412
#: The view of dataset.json that shows each tomogram together with the overview.
VIEWS = {
    37: "area3-tomos_37-41_54",
    38: "area3-tomos_37-41_54",
    40: "area3-tomos_37-41_54",
    41: "area3-tomos_37-41_54",
    54: "area3-tomos_37-41_54",
    53: "area2-tomo_53",
}
#: The three tomograms written as stores: a crowded cytoplasm of vesicles (40), fibres and
#: a multivesicular body (41), lipid droplets and organelles (53), picked from the middle
#: slices. 53 sits far from the others on the overview.
CONVERTED = (40, 41, 53)
BIN_XY = 4
BIN_Z = 4
#: 18 binned slices keep a store near 5.6 MB: the binned noise barely compresses, so size
#: grows linearly with depth (24 slices were 7.4 MB).
SLICES = 18
CHUNKS = (1, 256, 256)
LEVELS = 3
COMPRESSOR = Blosc(cname="zstd", clevel=9, shuffle=Blosc.BITSHUFFLE)
NGFF = "0.4"
N5_BLOCKS = (192, 192, 32)


def fetch(url: str, path: Path) -> bytes:
    """``url`` into ``path`` once; a 403 or 404 is an absent object and comes back empty."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = download(url)
        except urllib.error.HTTPError as err:
            if err.code not in (403, 404):
                raise
            data = b""
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.rename(path)
    return path.read_bytes()


def download(url: str, tries: int = 4) -> bytes:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except OSError:
            if attempt == tries - 1:
                raise
    raise AssertionError("unreachable")


# --- geometry -----------------------------------------------------------------------------


def matrix(parameters: list[float]) -> np.ndarray:
    """A MoBIE / BigDataViewer 3 x 4 row-major affine as a 4 x 4 matrix."""
    out = np.eye(4)
    out[:3, :] = np.asarray(parameters, dtype=float).reshape(3, 4)
    return out


def view_chain(dataset: dict, view: str, source: str) -> np.ndarray:
    """All the affines a view lists for ``source``, composed in the order listed."""
    out = np.eye(4)
    for transform in dataset["views"][view]["sourceTransforms"]:
        affine = transform.get("affine")
        if affine and source in affine["sources"]:
            out = matrix(affine["parameters"]) @ out
    return out


def read_setup(xml_path: Path) -> dict:
    """Size (x, y, z), voxel size (um) and registration of the tomogram's BDV XML."""
    text = xml_path.read_text()

    def numbers(tag: str) -> list[float]:
        found = re.search(rf"<{tag}>([^<]+)</{tag}>", text)
        if not found:
            raise SystemExit(f"{xml_path.name}: no <{tag}>")
        return [float(v) for v in found.group(1).split()]

    voxel = re.search(r"<voxelSize>.*?<size>([^<]+)</size>", text, re.S)
    return {
        "size": [int(v) for v in numbers("size")],
        "voxel_um": [float(v) for v in voxel.group(1).split()],
        "affine": matrix(numbers("affine")),
    }


def footprint(dataset: dict, number: int, setup: dict) -> dict:
    """Where tomogram ``number`` sits on the overview, in overview level-0 pixels."""
    view, source = VIEWS[number], f"tomo_{number}_hm"
    voxel = setup["voxel_um"]
    # affine0 of dataset.json is the XML's registration over the voxel size: the two must agree.
    pixel_to_global = view_chain(dataset, view, source) @ np.diag([*voxel, 1.0])
    xml_only = _manual_part(dataset, view, source) @ setup["affine"]
    if not np.allclose(pixel_to_global, xml_only, rtol=1e-6, atol=1e-9):
        raise SystemExit(f"{source}: dataset.json affine0 and the XML registration disagree")
    to_overview_um = np.linalg.inv(view_chain(dataset, view, "em-overview")) @ pixel_to_global
    nx, ny = setup["size"][:2]
    corners = np.array([[-0.5, -0.5], [nx - 0.5, -0.5], [nx - 0.5, ny - 0.5], [-0.5, ny - 0.5]]).T
    px = (to_overview_um[:2, :2] @ corners + to_overview_um[:2, 3:4]) / OVERVIEW_PIXEL_UM
    linear = to_overview_um[:2, :2]
    return {
        "to_overview_um": to_overview_um,
        "corners_px": px,
        "x_px": px[0].mean(),
        "y_px": px[1].mean(),
        "box_w_px": np.ptp(px[0]),
        "box_h_px": np.ptp(px[1]),
        # Angle of the tomogram's +x axis in the overview's pixel frame (y down, so positive
        # is clockwise on screen). A negative determinant would mean a mirror image.
        "rotation_deg": float(np.degrees(np.arctan2(linear[1, 0], linear[0, 0]))),
        "mirrored": bool(np.linalg.det(linear) < 0),
        "side_um": float(np.hypot(*(linear @ [nx, 0.0]))),
    }


def _manual_part(dataset: dict, view: str, source: str) -> np.ndarray:
    """The view's transforms for ``source`` after its own ``affine0``."""
    out = np.eye(4)
    seen = False
    for transform in dataset["views"][view]["sourceTransforms"]:
        affine = transform.get("affine")
        if affine and source in affine["sources"]:
            if affine["name"] == "affine0":
                seen = True
            elif seen:
                out = matrix(affine["parameters"]) @ out
    return out


# --- N5 -----------------------------------------------------------------------------------


def n5_block(name: str, level: int, gx: int, gy: int, gz: int) -> np.ndarray | None:
    """One gzip N5 block as (z, y, x): a big-endian header, then the compressed data."""
    url = f"{BUCKET}/bdv-n5/{name}.n5/setup0/timepoint0/s{level}/{gx}/{gy}/{gz}"
    try:
        raw = download(url)
    except urllib.error.HTTPError as err:
        if err.code in (403, 404):
            return None  # an absent block is zeros
        raise
    mode, ndim = struct.unpack(">HH", raw[:4])
    dims = struct.unpack(">" + "I" * ndim, raw[4 : 4 + 4 * ndim])
    if mode != 0:
        raise SystemExit(f"{name}: variable length N5 block, not handled")
    data = np.frombuffer(gzip.decompress(raw[4 + 4 * ndim :]), dtype=np.uint8)
    return data.reshape(dims[::-1])  # N5 lists x first and x varies fastest


def read_slab(name: str, shape_xyz: tuple[int, int, int], z0: int, z1: int) -> np.ndarray:
    """Level 0 slices ``z0:z1`` of a tomogram as a (z, y, x) uint8 array."""
    nx, ny, _ = shape_xyz
    bx, by, bz = N5_BLOCKS
    out = np.zeros((z1 - z0, ny, nx), np.uint8)
    jobs = [
        (gx, gy, gz)
        for gz in range(z0 // bz, (z1 - 1) // bz + 1)
        for gy in range(-(-ny // by))
        for gx in range(-(-nx // bx))
    ]
    with ThreadPoolExecutor(8) as pool:
        blocks = list(pool.map(lambda job: n5_block(name, 0, *job), jobs))
    for (gx, gy, gz), block in zip(jobs, blocks):
        if block is None:
            continue
        lo, hi = max(gz * bz, z0), min(gz * bz + block.shape[0], z1)
        out[
            lo - z0 : hi - z0,
            gy * by : gy * by + block.shape[1],
            gx * bx : gx * bx + block.shape[2],
        ] = block[lo - gz * bz : hi - gz * bz]
    return out


def binned_volume(name: str, shape_xyz: tuple[int, int, int], cache: Path) -> np.ndarray:
    """The central binned slices (z, y, x), at most ``SLICES``, float32, mean binning."""
    path = cache / f"{name}_binned.npy"
    if path.exists():
        return np.load(path)
    nx, ny, nz = shape_xyz
    slices = min(
        SLICES, nz // BIN_Z
    )  # every tomogram has at least 90 source slices, so 18 binned ones
    z0 = (nz - slices * BIN_Z) // 2
    if nx % BIN_XY or ny % BIN_XY:
        raise SystemExit(f"{name}: {shape_xyz} does not bin by {BIN_XY} in y and x")
    print(f"{name}: reading level 0, slices {z0}-{z0 + slices * BIN_Z}")
    slab = read_slab(name, shape_xyz, z0, z0 + slices * BIN_Z)
    out = np.empty((slices, ny // BIN_XY, nx // BIN_XY), np.float32)
    for i in range(slices):  # one binned slice at a time keeps the float copy small
        group = slab[i * BIN_Z : (i + 1) * BIN_Z].astype(np.float32).mean(axis=0)
        out[i] = group.reshape(ny // BIN_XY, BIN_XY, nx // BIN_XY, BIN_XY).mean(axis=(1, 3))
    np.save(path, out)
    return out


# --- OME-Zarr -----------------------------------------------------------------------------


def to_uint8(volume: np.ndarray) -> np.ndarray:
    """0-255 between the 0.5 and 99.5 percentiles of the volume."""
    lo, hi = np.percentile(volume, [0.5, 99.5])
    return np.clip((volume - lo) / max(hi - lo, 1e-6) * 255 + 0.5, 0, 255).astype(np.uint8)


def halve(volume: np.ndarray) -> np.ndarray:
    """Mean of 2 x 2 blocks in y and x (the last row or column repeated when odd)."""
    z, y, x = volume.shape
    padded = np.pad(volume.astype(np.float32), ((0, 0), (0, y % 2), (0, x % 2)), mode="edge")
    half = padded.reshape(z, padded.shape[1] // 2, 2, padded.shape[2] // 2, 2).mean(axis=(2, 4))
    return np.clip(half + 0.5, 0, 255).astype(np.uint8)


def write_store(path: Path, volume: np.ndarray, voxel_um: float) -> None:
    shutil.rmtree(path, ignore_errors=True)
    group = zarr.open_group(str(path), mode="w")
    datasets = []
    level = volume
    for index in range(LEVELS):
        group.create_dataset(
            str(index),
            data=level,
            chunks=tuple(min(c, s) for c, s in zip(CHUNKS, level.shape)),
            compressor=COMPRESSOR,
            dimension_separator="/",
            overwrite=True,
        )
        factor = 2.0**index
        datasets.append(
            {
                "path": str(index),
                "coordinateTransformations": [
                    {"type": "scale", "scale": [voxel_um, voxel_um * factor, voxel_um * factor]}
                ],
            }
        )
        if index < LEVELS - 1:
            level = halve(level)
    window = np.percentile(volume, [1, 99])
    group.attrs.update(
        {
            "multiscales": [
                {
                    "version": NGFF,
                    "name": path.stem,
                    "axes": [{"name": n, "type": "space", "unit": "micrometer"} for n in "zyx"],
                    "datasets": datasets,
                }
            ],
            "omero": {
                "channels": [
                    {
                        "label": "EM",
                        "color": "FFFFFF",
                        "active": True,
                        "window": {
                            "start": float(window[0]),
                            "end": float(window[1]),
                            "min": 0,
                            "max": 255,
                        },
                    }
                ],
                "rdefs": {"model": "greyscale", "defaultZ": volume.shape[0] // 2},
            },
        }
    )


def disk_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


# --- check image --------------------------------------------------------------------------


def overview_region(level: int, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
    """Overview ``level`` (zlib chunks, uint16, '/'-separated keys) over a pixel window."""
    meta = json.loads(download(f"{OVERVIEW_URL}/s{level}/.zarray"))
    cy_size, cx_size = meta["chunks"]
    out = np.zeros((y1 - y0, x1 - x0), np.uint16)
    for cy in range(y0 // cy_size, (y1 - 1) // cy_size + 1):
        for cx in range(x0 // cx_size, (x1 - 1) // cx_size + 1):
            try:
                raw = download(f"{OVERVIEW_URL}/s{level}/{cy}/{cx}")
            except urllib.error.HTTPError:
                continue
            tile = np.frombuffer(zlib.decompress(raw), dtype="<u2").reshape(cy_size, cx_size)
            ys, xs = cy * cy_size, cx * cx_size
            ya, yb = max(ys, y0), min(ys + cy_size, y1)
            xa, xb = max(xs, x0), min(xs + cx_size, x1)
            out[ya - y0 : yb - y0, xa - x0 : xb - x0] = tile[ya - ys : yb - ys, xa - xs : xb - xs]
    return out


def grey(plane: np.ndarray, low: float, high: float) -> np.ndarray:
    return np.clip((plane.astype(np.float32) - low) / (high - low) * 255, 0, 255).astype(np.uint8)


def render_check(path: Path, rows: list[dict], volumes: dict[int, np.ndarray]) -> None:
    from PIL import Image, ImageDraw
    from scipy import ndimage

    level = 5  # 32x: the whole overview in 377 x 816 pixels
    whole = overview_region(
        level, 0, -(-OVERVIEW_SHAPE_YX[0] // 32), 0, -(-OVERVIEW_SHAPE_YX[1] // 32)
    )
    low, high = np.percentile(whole[whole > 0], [1, 99.5])
    scale = 2
    base = Image.fromarray(grey(whole, low, high)).convert("RGB")
    base = base.resize((base.width * scale, base.height * scale), Image.NEAREST)
    draw = ImageDraw.Draw(base)
    for row in rows:
        cx, cy = row["x_px"] / 32 * scale, row["y_px"] / 32 * scale
        half = 7
        color = (255, 60, 60) if row["converted"] else (80, 160, 255)
        draw.rectangle([cx - half, cy - half, cx + half, cy + half], outline=color, width=2)
        draw.text((cx + half + 3, cy - half), f"{row['tomogram'][5:]}", fill=color)

    # A crop of the overview at level 0 around each converted box, beside the tomogram's
    # middle slice resampled into the overview's frame at the same pixel size.
    half = 110
    panels = []
    for row in rows:
        if not row["converted"]:
            continue
        number = int(row["tomogram"][5:])
        cx, cy = int(round(row["x_px"])), int(round(row["y_px"]))
        crop = overview_region(0, cy - half, cy + half, cx - half, cx + half)
        crop_img = Image.fromarray(grey(crop, 290, 23000)).convert("RGB")
        marked = crop_img.copy()
        corners = [(x - (cx - half), y - (cy - half)) for x, y in row["corners_px"].T]
        ImageDraw.Draw(marked).polygon(corners, outline=(255, 60, 60))
        # Overview crop pixel (u, v) -> overview um -> tomogram binned pixel (x, y).
        rows_y, cols_x = np.meshgrid(
            np.arange(2 * half) + cy - half, np.arange(2 * half) + cx - half, indexing="ij"
        )
        um = np.stack(
            [
                cols_x * OVERVIEW_PIXEL_UM,
                rows_y * OVERVIEW_PIXEL_UM,
                np.zeros_like(rows_y),
                np.ones_like(rows_y),
            ]
        )
        back = np.linalg.inv(row["to_overview_um"]) @ um.reshape(4, -1)
        px = (back[:2] + 0.5) / BIN_XY - 0.5  # level-0 tomogram pixel -> binned pixel
        middle = volumes[number][volumes[number].shape[0] // 2]
        sampled = ndimage.map_coordinates(middle, [px[1], px[0]], order=1, cval=0.0)
        sampled = sampled.reshape(2 * half, 2 * half)
        inside = sampled > 0
        shown = grey(sampled, *np.percentile(middle, [0.5, 99.5]))
        shown[~inside] = 0
        panels.append((marked, crop_img, Image.fromarray(shown).convert("RGB"), number))

    zoom = 3
    cell = 2 * half * zoom
    sheet = Image.new(
        "RGB", (max(base.width, 3 * cell + 40), base.height + 20 + len(panels) * (cell + 24))
    )
    sheet.paste(base, (0, 0))
    y = base.height + 20
    for marked, plain, tomo, number in panels:
        for i, image in enumerate((marked, plain, tomo)):
            sheet.paste(image.resize((cell, cell), Image.NEAREST), (i * (cell + 20), y + 14))
        ImageDraw.Draw(sheet).text(
            (0, y),
            f"tomo_{number}: overview with footprint, overview, tomogram in the overview frame",
            fill=(255, 255, 255),
        )
        y += cell + 24
    sheet.save(path)
    print(f"check image: {path}")


# --- main ---------------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cache", type=Path, required=True, help="where the downloads go")
    parser.add_argument("--out", type=Path, required=True, help="the example's data folder")
    parser.add_argument("--png", type=Path, help="also render a check image of the boxes")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    out = args.out / "hela_tomo"
    out.mkdir(parents=True, exist_ok=True)

    dataset = json.loads(fetch(f"{RAW}/dataset.json", args.cache / "dataset.json"))
    rows, volumes = [], {}
    for number in sorted(VIEWS):
        name = f"tomo_{number}_hm"
        xml_path = args.cache / f"{name}.xml"
        fetch(f"{BUCKET}/bdv-n5-s3/{name}.xml", xml_path)
        setup = read_setup(xml_path)
        where = footprint(dataset, number, setup)
        if where["mirrored"]:
            raise SystemExit(f"{name}: footprint is mirrored on the overview")
        for key in ("x_px", "y_px"):  # a footprint off the overview would draw nowhere
            limit = OVERVIEW_SHAPE_YX[1 if key == "x_px" else 0]
            if not 0 <= where[key] < limit:
                raise SystemExit(f"{name}: footprint centre outside the overview")
        binned = binned_volume(name, tuple(setup["size"]), args.cache)
        volumes[number] = binned
        voxel_um = setup["voxel_um"][0] * BIN_XY
        converted = number in CONVERTED
        if converted:
            store = out / f"tomo_{number}.zarr"
            write_store(store, to_uint8(binned), voxel_um)
            print(f"tomo_{number}.zarr: {disk_mb(store):.2f} MB on disk")
        rows.append(
            {
                "tomogram": f"tomo_{number}",
                "x_px": round(where["x_px"], 1),
                "y_px": round(where["y_px"], 1),
                "box_w_px": round(where["box_w_px"], 1),
                "box_h_px": round(where["box_h_px"], 1),
                "pixel_nm": round(voxel_um * 1000, 3) if converted else "",
                "source_pixel_nm": round(setup["voxel_um"][0] * 1000, 4),
                "slices": binned.shape[0] if converted else "",
                "rotation_deg": round(where["rotation_deg"], 1),
                "footprint_um": round(where["side_um"], 2),
                "mean_intensity": round(float(binned.mean()), 1),
                "contrast_std": round(float(binned.std()), 1),
                "converted": str(converted).lower(),
                # not written: the check image needs them
                "corners_px": where["corners_px"],
                "to_overview_um": where["to_overview_um"],
            }
        )

    fields = [
        "tomogram",
        "x_px",
        "y_px",
        "box_w_px",
        "box_h_px",
        "pixel_nm",
        "source_pixel_nm",
        "slices",
        "rotation_deg",
        "footprint_um",
        "mean_intensity",
        "contrast_std",
        "converted",
    ]
    with open(out / "tomograms.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"tomograms.csv: {len(rows)} rows")

    if args.png:
        for row in rows:
            row["converted"] = row["converted"] == "true"
        render_check(args.png, rows, volumes)


if __name__ == "__main__":
    main()
