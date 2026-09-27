"""Generate the example images and tables of ``projects/init/bioimage_examples``.

Every image comes from a scikit-image sample dataset with a permissive licence
(see the README this script writes next to the data). The tables are derived
from the pixels: nuclei are segmented, Visium-like spots are laid on a hex grid
over the tissue, and their clusters and "expression" follow the stain
intensities, so what the viewer overlays lines up with what it draws.

Nothing here is a runtime dependency of Depictio. Run it from the repo root with
throwaway dependencies:

    uv run --no-project --python 3.12 \\
        --with scikit-image --with "zarr<3" --with "ome-zarr<0.11" --with pooch \\
        python dev/bioimage/make_examples.py \\
        --out depictio/projects/init/bioimage_examples/data

``pooch`` downloads the datasets scikit-image does not bundle (``kidney``,
``human_mitosis``, ``lily``, ``skin``) into its cache on first use.

The SpatialData example needs the ``spatialdata`` library, which requires zarr 3,
so it lives in ``make_spatialdata_example.py`` and this script runs it through
``uv run --with spatialdata==<--spatialdata-version>`` in a second throwaway
environment (``uv`` must be on PATH; ``--no-spatialdata`` skips that step and
keeps the store and manifest entry already there). The NGFF 0.5 (sharded)
example needs zarr 3 too: ``make_ngff05_example.py``, run the same way with
``--with zarr==<--zarr3-version>`` (``--no-ngff05`` skips it).

The OME-TIFF example is written with ``tifffile``, which scikit-image depends
on: a tiled, zlib-compressed pyramid whose reduced levels are SubIFDs of the
full-resolution planes, with channel names, colours and the physical pixel
size in the OME-XML.

The OME-Zarr stores written here are NGFF 0.4: zarr v2, ``/`` dimension
separator, a ``multiscales`` block with physical ``scale`` transforms and an
``omero`` block with channel names, colours and contrast windows. Output is
deterministic for a given ``--seed`` and library versions.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import numpy as np
import zarr
from numcodecs import Blosc, Zlib
from scipy import ndimage as ndi
from skimage import color, data, feature, filters, measure, segmentation, transform

NGFF_VERSION = "0.4"

# Physical pixel sizes, in micrometres. kidney's are the acquisition values
# scikit-image documents; the other two images ship without a calibration, so
# theirs are nominal (typical of a 20x brightfield slide and a 10x high-content
# screen) and flagged as such in the README.
KIDNEY_XY_UM = 1.24
KIDNEY_Z_UM = 1.25
IHC_XY_UM_NOMINAL = 0.5
MITOSIS_XY_UM_NOMINAL = 0.65
# skimage.data.lily documents 1.24 um pixels.
LILY_XY_UM = 1.24

# The SpatialData store is written by this pinned version (see the README), in
# its default on-disk formats: zarr v3, an NGFF 0.5 image.
SPATIALDATA_VERSION = "0.8.0"
# The NGFF 0.5 (sharded) store is written by this pinned zarr-python release.
ZARR3_VERSION = "3.4.0"

KIDNEY_CHANNELS = [
    # scikit-image: emission wavelengths 450, 515 and 605 nm.
    {"label": "Em 450 nm (nuclei)", "color": "0000FF"},
    {"label": "Em 515 nm", "color": "00FF00"},
    {"label": "Em 605 nm", "color": "FF00FF"},
]
# lily's four channels carry no documented stain; the labels say what each
# channel shows. Two are kept: Ch3 is a dimmer copy of Ch2 and Ch4 looks much
# like Ch1, and every extra channel costs file size (see example_ome_tiff).
LILY_CHANNELS = [
    {"index": 0, "label": "Ch1 (cell walls)", "short": "ch1", "color": "FF00FF"},
    {"index": 1, "label": "Ch2 (thick walls)", "short": "ch2", "color": "00FF00"},
]
RGB_CHANNELS = [
    {"label": "Red", "color": "FF0000"},
    {"label": "Green", "color": "00FF00"},
    {"label": "Blue", "color": "0000FF"},
]


# ---------------------------------------------------------------------------
# NGFF writing
# ---------------------------------------------------------------------------


def make_compressor(name: str, level: int):
    if name == "zlib":
        return Zlib(level=level)
    cname = name.split("-", 1)[1]
    return Blosc(cname=cname, clevel=level, shuffle=Blosc.BITSHUFFLE)


def build_pyramid(image: np.ndarray, levels: int) -> list[np.ndarray]:
    """Level 0 plus ``levels - 1`` 2x mean-downsamplings of the last two (y, x) axes."""
    pyramid = [image]
    factors = (1,) * (image.ndim - 2) + (2, 2)
    for _ in range(levels - 1):
        prev = pyramid[-1]
        if min(prev.shape[-2:]) < 2:
            break
        down = transform.downscale_local_mean(prev.astype(np.float32), factors)
        if np.issubdtype(image.dtype, np.integer):
            down = np.clip(np.rint(down), 0, np.iinfo(image.dtype).max)
        pyramid.append(down.astype(image.dtype))
    return pyramid


def channel_window(values: np.ndarray, dtype: np.dtype) -> dict:
    """Contrast window from the 0.5 / 99.5 percentiles, full dtype range as bounds."""
    lo, hi = np.percentile(values, [0.5, 99.5])
    if hi <= lo:
        hi = lo + 1
    info = np.iinfo(dtype)
    return {"start": float(lo), "end": float(hi), "min": float(info.min), "max": float(info.max)}


def write_ngff_store(
    path: Path,
    image: np.ndarray,
    axes: list[dict],
    scale: list[float],
    channels: list[dict],
    name: str,
    *,
    levels: int,
    chunk: int,
    compressor,
    windows: list[dict] | None = None,
) -> int:
    """Write one multiscale NGFF 0.4 store and return its size in bytes."""
    if path.exists():
        shutil.rmtree(path)
    axis_names = [a["name"] for a in axes]
    c_axis = axis_names.index("c")
    spatial = {"y", "x"}

    store = zarr.DirectoryStore(str(path), dimension_separator="/")
    root = zarr.group(store=store, overwrite=True)
    pyramid = build_pyramid(image, levels)
    datasets = []
    for level, arr in enumerate(pyramid):
        chunks = tuple(
            min(chunk, size) if axis_names[i] in spatial else 1 for i, size in enumerate(arr.shape)
        )
        root.create_dataset(
            str(level),
            data=arr,
            chunks=chunks,
            compressor=compressor,
            dimension_separator="/",
            overwrite=True,
        )
        level_scale = [
            s * (2**level) if axis_names[i] in spatial else s for i, s in enumerate(scale)
        ]
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [{"type": "scale", "scale": level_scale}],
            }
        )

    if windows is None:
        windows = [
            channel_window(np.take(image, ci, axis=c_axis), image.dtype)
            for ci in range(image.shape[c_axis])
        ]
    z_size = image.shape[axis_names.index("z")] if "z" in axis_names else 1
    root.attrs.put(
        {
            "multiscales": [
                {
                    "version": NGFF_VERSION,
                    "name": name,
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
                "name": name,
                "version": NGFF_VERSION,
                "channels": [
                    {
                        "active": True,
                        "coefficient": 1,
                        "color": ch["color"],
                        "family": "linear",
                        "inverted": False,
                        "label": ch["label"],
                        "window": win,
                    }
                    for ch, win in zip(channels, windows, strict=True)
                ],
                "rdefs": {"defaultT": 0, "defaultZ": z_size // 2, "model": "color"},
            },
        }
    )
    # zarr writes its JSON metadata without a final newline, which the repo's
    # end-of-file-fixer hook would add on commit; adding it here keeps a
    # regenerated store identical to the committed one.
    for meta in path.rglob(".z*"):
        text = meta.read_text()
        if not text.endswith("\n"):
            meta.write_text(text + "\n")
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def validate_store(path: Path, expected_levels: int) -> None:
    """Read the store back with ome-zarr-py when it is installed."""
    try:
        from ome_zarr.io import parse_url
        from ome_zarr.reader import Multiscales, Reader
    except ImportError:
        print("  (ome-zarr not installed: skipping read-back validation)")
        return
    location = parse_url(str(path))
    if location is None:
        raise RuntimeError(f"{path} is not a readable zarr location")
    nodes = list(Reader(location)())
    image = nodes[0]
    if not any(isinstance(spec, Multiscales) for spec in image.specs):
        raise RuntimeError(f"{path}: no multiscales found by ome-zarr")
    if len(image.data) != expected_levels:
        raise RuntimeError(f"{path}: {len(image.data)} levels, expected {expected_levels}")


# ---------------------------------------------------------------------------
# Image analysis helpers
# ---------------------------------------------------------------------------


def to_uint8(image: np.ndarray, lo: float, hi: float) -> np.ndarray:
    scaled = (image.astype(np.float32) - lo) / max(hi - lo, 1e-6)
    return np.clip(np.rint(scaled * 255), 0, 255).astype(np.uint8)


def drop_small(labels: np.ndarray, min_size: int) -> np.ndarray:
    """Zero out labelled objects under ``min_size`` pixels.

    Done by hand because ``remove_small_objects`` renamed its size argument in
    scikit-image 0.26 and this script should run on either side of that.
    """
    counts = np.bincount(labels.ravel())
    small = counts < min_size
    small[0] = False
    out = labels.copy()
    out[small[labels]] = 0
    return out


def segment_nuclei(channel: np.ndarray, min_size: int, min_distance: int) -> np.ndarray:
    """Otsu foreground, split touching nuclei with a distance-transform watershed."""
    smooth = filters.gaussian(channel.astype(np.float32), sigma=1)
    mask = drop_small(measure.label(smooth > filters.threshold_otsu(smooth)), min_size) > 0
    distance = ndi.distance_transform_edt(mask)
    footprint = np.ones((3,) * channel.ndim, dtype=bool)
    peaks = feature.peak_local_max(
        distance, min_distance=min_distance, labels=measure.label(mask), footprint=footprint
    )
    markers = np.zeros(channel.shape, dtype=np.int32)
    markers[tuple(peaks.T)] = np.arange(1, len(peaks) + 1)
    labels = segmentation.watershed(-distance, markers, mask=mask)
    return drop_small(labels, min_size)


def segment_plant_cells(wall: np.ndarray, min_cell: int, max_cell: int) -> np.ndarray:
    """Plant cells of a section whose walls are bright, as labels.

    Cells are the dark lumens between the walls: the same threshold + watershed
    as the nuclei, run on the inverted wall signal (``wall`` scaled to 0-1), so
    lumens that touch through a gap in a wall are still split. Lumens over
    ``max_cell`` pixels (background, vessels) are dropped. Each label is the
    lumen grown by 2 px, so the wall around it counts towards its intensities.
    """
    lumens = segment_nuclei(1 - wall, min_size=min_cell, min_distance=4)
    counts = np.bincount(lumens.ravel())
    lumens[(counts > max_cell)[lumens]] = 0
    lumens, _, _ = segmentation.relabel_sequential(lumens)
    return segmentation.expand_labels(lumens, 2)


def kmeans(features: np.ndarray, k: int, rng: np.random.Generator, iters: int = 50) -> np.ndarray:
    """Plain Lloyd k-means on standardised features (no scikit-learn needed)."""
    z = (features - features.mean(axis=0)) / (features.std(axis=0) + 1e-9)
    centres = z[rng.choice(len(z), size=k, replace=False)]
    assign = np.zeros(len(z), dtype=int)
    for _ in range(iters):
        dist = ((z[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        new_assign = dist.argmin(axis=1)
        if np.array_equal(new_assign, assign):
            break
        assign = new_assign
        for j in range(k):
            if np.any(assign == j):
                centres[j] = z[assign == j].mean(axis=0)
    return assign


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------


def example_multichannel_2d(out: Path, args, comp) -> dict:
    """Maximum projection of scikit-image ``kidney`` (3 channels, 512 x 512)."""
    name = "kidney_2d"
    kidney = data.kidney()  # (z, y, x, c) uint16, 12-bit
    mip = kidney.max(axis=0).transpose(2, 0, 1)  # (c, y, x)
    axes = [
        {"name": "c", "type": "channel"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]
    size = write_ngff_store(
        out / f"{name}.zarr",
        mip,
        axes,
        [1.0, KIDNEY_XY_UM, KIDNEY_XY_UM],
        KIDNEY_CHANNELS,
        name,
        levels=args.levels,
        chunk=args.chunk,
        compressor=comp,
    )

    labels = segment_nuclei(mip[0], min_size=12, min_distance=3)
    props = measure.regionprops(labels, intensity_image=mip.transpose(1, 2, 0))
    # Per-channel 99th percentile, so the dominant channel is read on comparable scales.
    norms = np.percentile(mip.reshape(3, -1), 99, axis=1)
    short = ["em450", "em515", "em605"]
    rows = []
    for i, p in enumerate(props, start=1):
        means = np.asarray(p.intensity_mean, dtype=float)
        dominant = short[int(np.argmax(means / norms))]
        y, x = p.centroid
        rows.append(
            [
                f"k2d_{i:04d}",
                name,
                round(float(x), 2),
                round(float(y), 2),
                int(p.area),
                round(float(p.area) * KIDNEY_XY_UM**2, 2),
                *(round(float(m), 1) for m in means),
                dominant,
            ]
        )
    write_csv(
        out / f"{name}_cells.csv",
        [
            "cell_id",
            "sample",
            "x",
            "y",
            "area_px",
            "area_um2",
            "mean_em450",
            "mean_em515",
            "mean_em605",
            "dominant_channel",
        ],
        rows,
    )
    return {"store": f"{name}.zarr", "bytes": size, "rows": len(rows)}


def example_spatial(out: Path, args, comp, rng: np.random.Generator) -> dict:
    """``immunohistochemistry`` as an RGB tissue image plus Visium-like spots."""
    name = "ihc_spatial"
    rgb = data.immunohistochemistry()  # (y, x, 3) uint8
    image = rgb.transpose(2, 0, 1)
    axes = [
        {"name": "c", "type": "channel"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]
    full_range = [{"start": 0.0, "end": 255.0, "min": 0.0, "max": 255.0}] * 3
    size = write_ngff_store(
        out / f"{name}.zarr",
        image,
        axes,
        [1.0, IHC_XY_UM_NOMINAL, IHC_XY_UM_NOMINAL],
        RGB_CHANNELS,
        name,
        levels=args.levels,
        chunk=args.chunk,
        compressor=comp,
        windows=full_range,
    )

    # Colour deconvolution into hematoxylin (nuclei) and DAB (the FHL2 stain).
    hed = color.rgb2hed(rgb)
    hema = filters.gaussian(hed[..., 0], sigma=2)
    dab = filters.gaussian(hed[..., 2], sigma=2)
    brightness = filters.gaussian(color.rgb2gray(rgb), sigma=2)
    tissue = brightness < args.tissue_threshold

    spacing = args.spot_spacing
    radius = max(2, int(round(spacing * 0.275)))  # Visium: 55 um spots, 100 um apart
    height, width = brightness.shape
    yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    disk = (yy**2 + xx**2) <= radius**2
    spots = []
    row_step = spacing * np.sqrt(3) / 2
    for r, y in enumerate(np.arange(radius, height - radius, row_step)):
        offset = spacing / 2 if r % 2 else 0.0
        for x in np.arange(radius + offset, width - radius, spacing):
            yi, xi = int(round(y)), int(round(x))
            window = (slice(yi - radius, yi + radius + 1), slice(xi - radius, xi + radius + 1))
            if tissue[window][disk].mean() < 0.5:
                continue
            spots.append(
                (x, y, hema[window][disk].mean(), dab[window][disk].mean(), brightness[yi, xi])
            )
    arr = np.array(spots)
    assign = kmeans(arr[:, 2:5], args.clusters, rng)
    # Cluster names ordered by DAB, so C1 is always the most DAB-positive group.
    order = np.argsort([-arr[assign == j, 3].mean() for j in range(args.clusters)])
    rank = {int(j): i + 1 for i, j in enumerate(order)}

    def norm(v: np.ndarray) -> np.ndarray:
        # Percentile bounds: a handful of saturated spots would otherwise squash the rest.
        lo, hi = np.percentile(v, [2, 98])
        return np.clip((v - lo) / (hi - lo + 1e-9), 0, 1)

    h_n, d_n = norm(arr[:, 2]), norm(arr[:, 3])
    x_n = arr[:, 0] / width
    gene_a = rng.poisson(1 + 25 * d_n)  # tracks DAB
    gene_b = rng.poisson(1 + 20 * h_n)  # tracks hematoxylin
    gene_c = rng.poisson(3 + 8 * x_n)  # a left-to-right gradient, stain-independent
    rows = [
        [
            f"spot_{i:04d}",
            name,
            round(float(sx), 2),
            round(float(sy), 2),
            f"C{rank[int(a)]}",
            int(ga),
            int(gb),
            int(gc),
        ]
        for i, (sx, sy, a, ga, gb, gc) in enumerate(
            zip(arr[:, 0], arr[:, 1], assign, gene_a, gene_b, gene_c, strict=True), start=1
        )
    ]
    write_csv(
        out / f"{name}_spots.csv",
        ["spot_id", "sample", "x", "y", "cluster", "gene_A", "gene_B", "gene_C"],
        rows,
    )
    return {"store": f"{name}.zarr", "bytes": size, "rows": len(rows)}


def example_volume_timelapse(out: Path, args, comp) -> dict:
    """A drifting, bleaching crop of ``kidney`` as a (t, c, z, y, x) store."""
    name = "kidney_3d_timelapse"
    kidney = data.kidney().transpose(3, 0, 1, 2)  # (c, z, y, x)
    channels = [int(c) for c in args.volume_channels.split(",")]
    kidney = kidney[channels, :: args.z_step]
    crop, t_n = args.volume_crop, args.timepoints
    drift = np.array(args.drift, dtype=int)
    y0, x0 = args.volume_origin
    max_y, max_x = y0 + crop + drift[0] * (t_n - 1), x0 + crop + drift[1] * (t_n - 1)
    if max_y > kidney.shape[2] or max_x > kidney.shape[3]:
        raise SystemExit("--volume-origin + crop + drift leaves the kidney image")

    # 12-bit -> 8-bit per channel, on the t0 crop's percentiles, so that
    # bleaching reads as a real loss of signal over time.
    first = kidney[:, :, y0 : y0 + crop, x0 : x0 + crop]
    bounds = [np.percentile(first[i], [0.5, 99.8]) for i in range(len(channels))]
    frames = []
    for t in range(t_n):
        dy, dx = drift * t
        window = kidney[:, :, y0 + dy : y0 + dy + crop, x0 + dx : x0 + dx + crop]
        bleach = (1 - args.bleach) ** t
        frames.append(
            np.stack(
                [
                    to_uint8(window[i] * bleach, bounds[i][0], bounds[i][1])
                    for i in range(len(channels))
                ]
            )
        )
    stack = np.stack(frames)  # (t, c, z, y, x) uint8

    axes = [
        {"name": "t", "type": "time", "unit": "second"},
        {"name": "c", "type": "channel"},
        {"name": "z", "type": "space", "unit": "micrometer"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]
    size = write_ngff_store(
        out / f"{name}.zarr",
        stack,
        axes,
        [float(args.frame_interval), 1.0, KIDNEY_Z_UM * args.z_step, KIDNEY_XY_UM, KIDNEY_XY_UM],
        [KIDNEY_CHANNELS[c] for c in channels],
        name,
        levels=args.levels,
        chunk=args.chunk,
        compressor=comp,
    )

    # Nuclei of the first timepoint, segmented in 3D on the nuclear channel.
    nuclear = channels.index(0) if 0 in channels else 0
    labels = segment_nuclei(stack[0, nuclear], min_size=30, min_distance=3)
    props = measure.regionprops(labels, intensity_image=stack[0, nuclear])
    voxel_um3 = KIDNEY_XY_UM**2 * KIDNEY_Z_UM * args.z_step
    # Depth bands split the nuclei, not the stack, into thirds: the deeper planes
    # of this slide are dim, so a stack-based split would leave "bottom" empty.
    z_cuts = np.quantile([p.centroid[0] for p in props], [1 / 3, 2 / 3])
    rows = []
    for i, p in enumerate(props, start=1):
        z, y, x = p.centroid
        band = "upper" if z < z_cuts[0] else ("middle" if z < z_cuts[1] else "lower")
        rows.append(
            [
                f"k3d_{i:04d}",
                name,
                round(float(x), 2),
                round(float(y), 2),
                round(float(z), 2),
                band,
                int(p.area),
                round(float(p.area) * voxel_um3, 1),
                round(float(p.intensity_mean), 1),
            ]
        )
    write_csv(
        out / f"{name}_nuclei.csv",
        [
            "cell_id",
            "sample",
            "x",
            "y",
            "z",
            "depth_band",
            "volume_voxels",
            "volume_um3",
            "mean_intensity",
        ],
        rows,
    )
    return {"store": f"{name}.zarr", "bytes": size, "rows": len(rows)}


def example_multi_sample(out: Path, args, comp) -> list[dict]:
    """Three crops of ``human_mitosis``, one store each, plus cells and samples tables."""
    folder = out / "multi_sample"
    folder.mkdir(parents=True, exist_ok=True)
    mitosis = data.human_mitosis()  # (y, x) uint8
    crop = args.sample_crop
    # (sample, condition, replicate, crop origin). Conditions are labels for the
    # demo, not the conditions of the original screen.
    samples = [
        ("sample_A", "control", 1, (0, 0)),
        ("sample_B", "treated", 1, (0, mitosis.shape[1] - crop)),
        ("sample_C", "treated", 2, (mitosis.shape[0] - crop, 0)),
    ]
    axes = [
        {"name": "c", "type": "channel"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]
    # One window for all three stores, so they are displayed comparably.
    window = channel_window(mitosis, mitosis.dtype)
    results, cell_rows, sample_rows = [], [], []
    for sample, condition, replicate, (y0, x0) in samples:
        tile = mitosis[y0 : y0 + crop, x0 : x0 + crop]
        size = write_ngff_store(
            folder / f"{sample}.zarr",
            tile[None],
            axes,
            [1.0, MITOSIS_XY_UM_NOMINAL, MITOSIS_XY_UM_NOMINAL],
            [{"label": "DNA", "color": "FFFFFF"}],
            sample,
            levels=args.levels,
            chunk=args.chunk,
            compressor=comp,
            windows=[window],
        )
        labels = segment_nuclei(tile, min_size=15, min_distance=4)
        props = measure.regionprops(labels, intensity_image=tile)
        # Mitotic nuclei are condensed: small and bright. A heuristic, not a classifier.
        means = np.array([p.intensity_mean for p in props], dtype=float)
        areas = np.array([p.area for p in props], dtype=float)
        bright_cut = np.percentile(means, 85) if len(means) else 0
        area_cut = np.median(areas) if len(areas) else 0
        n_mitotic = 0
        for i, p in enumerate(props, start=1):
            y, x = p.centroid
            mitotic = p.intensity_mean >= bright_cut and p.area <= area_cut * 1.2
            n_mitotic += int(mitotic)
            cell_rows.append(
                [
                    f"{sample}_{i:04d}",
                    sample,
                    round(float(x), 2),
                    round(float(y), 2),
                    int(p.area),
                    round(float(p.intensity_mean), 1),
                    round(float(p.eccentricity), 3),
                    "mitotic" if mitotic else "interphase",
                ]
            )
        sample_rows.append(
            [
                sample,
                condition,
                replicate,
                "cultured human cells",
                "DNA",
                y0,
                x0,
                len(props),
                round(n_mitotic / max(len(props), 1), 3),
            ]
        )
        results.append({"store": f"multi_sample/{sample}.zarr", "bytes": size, "rows": len(props)})

    write_csv(
        folder / "cells.csv",
        [
            "cell_id",
            "sample",
            "x",
            "y",
            "area_px",
            "mean_intensity",
            "eccentricity",
            "phase",
        ],
        cell_rows,
    )
    write_csv(
        folder / "samples.csv",
        [
            "sample",
            "condition",
            "replicate",
            "tissue",
            "stain",
            "crop_y",
            "crop_x",
            "n_cells",
            "mitotic_fraction",
        ],
        sample_rows,
    )
    return results


def ome_color(hex_rgb: str) -> int:
    """OME-XML ``Color``: RGBA packed in a signed 32-bit integer."""
    value = int(hex_rgb + "FF", 16)
    return value - (1 << 32) if value >= 1 << 31 else value


def example_ome_tiff(out: Path, args) -> dict:
    """A crop of scikit-image ``lily`` as a pyramidal OME-TIFF, plus a cells table."""
    import tifffile

    name = "lily_stem"
    crop = args.tiff_crop
    y0, x0 = args.tiff_origin
    lily = data.lily()  # (y, x, 4) uint16, 12-bit
    if y0 + crop > lily.shape[0] or x0 + crop > lily.shape[1]:
        raise SystemExit("--tiff-origin + --tiff-crop leaves the lily image")
    window = lily[y0 : y0 + crop, x0 : x0 + crop, [c["index"] for c in LILY_CHANNELS]]
    # 12-bit -> 8-bit per channel. A single file cannot be chunked across git
    # objects like a zarr store, and the repo's check-added-large-files hook
    # caps one file at 500 kB: 8 bits, two channels and a 480 px crop fit.
    image = np.stack(
        [
            to_uint8(window[..., i], *np.percentile(window[..., i], [0.5, 99.8]))
            for i in range(len(LILY_CHANNELS))
        ]
    )  # (c, y, x) uint8

    path = out / f"{name}.ome.tif"
    pyramid = build_pyramid(image, args.levels)
    options = {
        "photometric": "minisblack",
        "tile": (args.chunk, args.chunk),
        "compression": "zlib",
        # Level 9, not --clevel: this file has to stay under the 500 kB hook.
        "compressionargs": {"level": 9},
        "resolutionunit": "CENTIMETER",
    }
    with tifffile.TiffWriter(path, bigtiff=False) as tif:
        for level, arr in enumerate(pyramid):
            px_cm = LILY_XY_UM * (2**level) * 1e-4
            extra = (
                {
                    "subifds": len(pyramid) - 1,
                    "metadata": {
                        "axes": "CYX",
                        "Name": name,
                        # A fixed UUID: tifffile draws a random one otherwise,
                        # and the file would change on every run.
                        "UUID": str(uuid.uuid5(uuid.NAMESPACE_URL, f"depictio/{name}")),
                        "Creator": "dev/bioimage/make_examples.py",
                        "PhysicalSizeX": LILY_XY_UM,
                        "PhysicalSizeXUnit": "\N{MICRO SIGN}m",
                        "PhysicalSizeY": LILY_XY_UM,
                        "PhysicalSizeYUnit": "\N{MICRO SIGN}m",
                        "Channel": {
                            "Name": [c["label"] for c in LILY_CHANNELS],
                            "Color": [ome_color(c["color"]) for c in LILY_CHANNELS],
                        },
                    },
                }
                if level == 0
                else {"subfiletype": 1, "metadata": None}
            )
            tif.write(arr, resolution=(1 / px_cm, 1 / px_cm), **options, **extra)
    validate_ome_tiff(path, len(pyramid), image.shape)

    rings = segment_plant_cells(
        image.astype(np.float32).max(axis=0) / 255, args.tiff_min_cell, args.tiff_max_cell
    )
    props = measure.regionprops(rings, intensity_image=image.transpose(1, 2, 0))
    means = np.array([p.intensity_mean for p in props], dtype=float)
    # "Thick-walled" when the Ch2 ring intensity, on the scale of its own 99th
    # percentile, is above the Otsu cut of all cells: the sheaths around the
    # vascular bundles and the stem's outer ring. A heuristic, not a classifier.
    ch2 = means[:, 1] / np.percentile(image[1], 99)
    ch2_cut = filters.threshold_otsu(ch2)
    rows = []
    for i, (p, m, c2) in enumerate(zip(props, means, ch2, strict=True), start=1):
        y, x = p.centroid
        rows.append(
            [
                f"lily_{i:04d}",
                name,
                round(float(x), 2),
                round(float(y), 2),
                int(p.area),
                round(float(p.area) * LILY_XY_UM**2, 2),
                *(round(float(v), 1) for v in m),
                "thick-walled" if c2 > ch2_cut else "thin-walled",
            ]
        )
    write_csv(
        out / f"{name}_cells.csv",
        [
            "cell_id",
            "sample",
            "x",
            "y",
            "area_px",
            "area_um2",
            *(f"mean_{c['short']}" for c in LILY_CHANNELS),
            "wall_type",
        ],
        rows,
    )
    return {"store": path.name, "bytes": path.stat().st_size, "rows": len(rows)}


def validate_ome_tiff(path: Path, levels: int, shape: tuple[int, ...]) -> None:
    """Read the file back the way viv needs it.

    One OME series, tiled, one plane per top-level IFD (not interleaved), and the
    reduced levels as SubIFDs of each plane.
    """
    import tifffile

    with tifffile.TiffFile(path) as tif:
        if not tif.is_ome or len(tif.series) != 1:
            raise RuntimeError(f"{path}: not a single-series OME-TIFF")
        series = tif.series[0]
        # viv expects every level to be exactly level 0 shifted right by n.
        expected = [(*shape[:-2], shape[-2] >> n, shape[-1] >> n) for n in range(levels)]
        if [lv.shape for lv in series.levels] != expected:
            raise RuntimeError(f"{path}: levels {[lv.shape for lv in series.levels]}")
        if len(tif.pages) != shape[0]:
            raise RuntimeError(f"{path}: reduced levels are not SubIFDs ({len(tif.pages)} IFDs)")
        pages = [page.aspage() for page in tif.pages]
        if not all(page.is_tiled and page.samplesperpixel == 1 for page in pages):
            raise RuntimeError(f"{path}: planes must be tiled, single-sample IFDs")


def example_spatialdata(out: Path, args) -> dict:
    """Run make_spatialdata_example.py in its own environment (it needs zarr 3)."""
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv not found: install it, or pass --no-spatialdata")
    script = Path(__file__).resolve().parent / "make_spatialdata_example.py"
    cmd = [
        uv,
        "run",
        "--no-project",
        "--python",
        "3.12",
        "--with",
        f"spatialdata=={args.spatialdata_version}",
        "--with",
        "pooch",
        "python",
        str(script),
        "--out",
        str(out),
        "--seed",
        str(args.seed),
        "--levels",
        str(args.levels),
        "--chunk",
        str(args.chunk),
        "--json",
    ]
    done = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


def example_ngff05(out: Path, args) -> dict:
    """Run make_ngff05_example.py in its own environment (it needs zarr 3)."""
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv not found: install it, or pass --no-ngff05")
    script = Path(__file__).resolve().parent / "make_ngff05_example.py"
    cmd = [
        uv,
        "run",
        "--no-project",
        "--python",
        "3.12",
        "--with",
        f"zarr=={args.zarr3_version}",
        "--with",
        # Only reads the store back (0.12 is the first release that reads NGFF 0.5).
        "ome-zarr>=0.12",
        "--with",
        "scikit-image",
        "--with",
        "pooch",
        "python",
        str(script),
        "--out",
        str(out),
        "--levels",
        str(args.levels),
        "--json",
    ]
    done = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, required=True, help="Output data directory")
    p.add_argument("--seed", type=int, default=1086, help="RNG seed (spot clusters, counts)")
    p.add_argument("--levels", type=int, default=3, help="Pyramid levels per store")
    p.add_argument("--chunk", type=int, default=256, help="Chunk edge along y and x")
    p.add_argument(
        "--compressor",
        choices=["blosc-zstd", "blosc-lz4", "zlib"],
        default="zlib",
        # zlib decodes everywhere (browsers ship it); blosc needs a wasm codec in
        # the viewer and saved nothing measurable on these images.
        help="Chunk codec (blosc variants use bit-shuffle)",
    )
    p.add_argument("--clevel", type=int, default=5, help="Compression level")
    # Spatial example.
    p.add_argument("--spot-spacing", type=float, default=14.0, help="Spot pitch in pixels")
    p.add_argument("--clusters", type=int, default=4, help="Spot clusters")
    p.add_argument(
        "--tissue-threshold",
        type=float,
        default=0.85,
        help="Grey level under which a pixel counts as tissue",
    )
    # Volume / time-lapse example.
    p.add_argument("--timepoints", type=int, default=5)
    p.add_argument("--frame-interval", type=float, default=60.0, help="Seconds between frames")
    p.add_argument("--z-step", type=int, default=2, help="Keep every n-th kidney plane")
    p.add_argument("--volume-crop", type=int, default=192, help="y/x crop edge in pixels")
    p.add_argument("--volume-origin", type=int, nargs=2, default=(96, 96), metavar=("Y", "X"))
    p.add_argument(
        "--drift", type=int, nargs=2, default=(6, 8), metavar=("DY", "DX"), help="px / frame"
    )
    p.add_argument("--bleach", type=float, default=0.08, help="Signal lost per frame (0-1)")
    p.add_argument(
        "--volume-channels", default="0,2", help="kidney channels to keep (0=450, 1=515, 2=605 nm)"
    )
    # Multi-sample example.
    p.add_argument("--sample-crop", type=int, default=256, help="Crop edge per sample store")
    # OME-TIFF example.
    p.add_argument("--tiff-crop", type=int, default=480, help="lily crop edge in pixels")
    p.add_argument("--tiff-origin", type=int, nargs=2, default=(256, 256), metavar=("Y", "X"))
    p.add_argument("--tiff-min-cell", type=int, default=15, help="Smallest cell, in pixels")
    p.add_argument("--tiff-max-cell", type=int, default=4000, help="Largest cell, in pixels")
    # SpatialData example.
    p.add_argument(
        "--spatialdata-version",
        default=SPATIALDATA_VERSION,
        help="spatialdata release the store is written with",
    )
    p.add_argument(
        "--no-spatialdata",
        action="store_true",
        help="Skip the SpatialData store (keeps the one already written and its manifest entry)",
    )
    # NGFF 0.5 (sharded) example.
    p.add_argument(
        "--zarr3-version",
        default=ZARR3_VERSION,
        help="zarr-python 3 release the NGFF 0.5 store is written with",
    )
    p.add_argument(
        "--no-ngff05",
        action="store_true",
        help="Skip the NGFF 0.5 store (keeps the one already written and its manifest entry)",
    )
    p.add_argument("--no-validate", action="store_true", help="Skip ome-zarr read-back")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    comp = make_compressor(args.compressor, args.clevel)

    results = [
        example_multichannel_2d(out, args, comp),
        example_spatial(out, args, comp, rng),
        example_volume_timelapse(out, args, comp),
        *example_multi_sample(out, args, comp),
    ]
    for res in results:
        store = out / res["store"]
        if not args.no_validate:
            validate_store(store, args.levels)
    # Validated as they are written, by their own readers.
    results.append(example_ome_tiff(out, args))
    if args.no_spatialdata:
        results.extend(_previous_entries(out / "manifest.json", "spatialdata_version"))
    else:
        results.append(example_spatialdata(out, args))
    if args.no_ngff05:
        results.extend(_previous_entries(out / "manifest.json", "shard"))
    else:
        results.append(example_ngff05(out, args))
    for res in results:
        print(f"  {res['store']:<34} {res['bytes'] / 1e6:6.2f} MB  {res['rows']:5d} table rows")
    total = sum(r["bytes"] for r in results)
    print(f"  total store size: {total / 1e6:.2f} MB")
    manifest = {
        "generator": "dev/bioimage/make_examples.py",
        # `out` and the `no_*` switches do not change the bytes written; leaving
        # them out keeps the manifest identical wherever the script is run from.
        "args": {
            k: v
            for k, v in vars(args).items()
            if k not in {"out", "no_validate", "no_spatialdata", "no_ngff05"}
        },
        "stores": results,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


def _previous_entries(manifest: Path, key: str) -> list[dict]:
    """Entries of an existing manifest carrying ``key`` (``--no-spatialdata``, ``--no-ngff05``)."""
    if not manifest.exists():
        return []
    stores = json.loads(manifest.read_text()).get("stores", [])
    return [s for s in stores if key in s]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
