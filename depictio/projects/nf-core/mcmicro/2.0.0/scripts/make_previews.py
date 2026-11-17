#!/usr/bin/env python3
"""Write PNG previews of an nf-core/mcmicro run for the template's Image collection.

Maintainer helper, run at fetch time by ``download_test_data.sh`` (the recipe
layer reads tables and cannot write images). Depictio has no OME-TIFF / zarr /
pyramid viewer yet, so the template shows the run's images as downscaled PNGs:

* one grey preview per channel of the registered image
  (``registration/ashlar/<sample>.ome.tif``), named by the marker sheet when it
  lists as many channels;
* one colour composite of the registered image: the first channel (the nuclear
  stain of cycle 1) in blue, the first two other non-nuclear channels in green
  and red;
* one outline preview per segmentation mask
  (``segmentation/<tool>/<sample>*.tif``): the mask boundaries in yellow over the
  nuclear stain.

Each preview is at most ``--max-px`` pixels on its long side (1024 by default),
downscaled with Lanczos from the full-resolution image; the mask is downscaled
with nearest-neighbour so its labels survive, then outlined. Intensities are
stretched to the 0.5th and 99.5th percentiles of the channel's non-zero pixels.

The manifest ``previews/previews.tsv`` holds one row per PNG: ``preview_id``,
``sample``, ``stage``, ``channel``, ``channel_index``, ``image_path`` (relative
to ``previews/``), the preview's ``width`` and ``height``, the full-resolution
``full_width`` and ``full_height``, ``scale`` (preview pixels per
full-resolution pixel) and ``underlay_sample``: the sample on the one row per
image (its first channel) that the template's ``spatial_cells`` tile draws under
the cells. The underlay is placed on the full-resolution frame of the
centroids (``full_width`` x ``full_height``), so the preview may be any size.

TODO(bioimage): replace the PNG previews with an OME-TIFF/zarr pyramid viewer (viv/deck.gl) once bioimage lands

Needs numpy, tifffile and Pillow (maintainer tools, not depictio runtime
dependencies). Illumination profiles (``illumination_correction/``) are not
previewed: BaSiCPy writes them with a floating-point predictor that tifffile
decodes only with ``imagecodecs``.

Usage: python make_previews.py DATA_ROOT [--markers input/markers.csv] [--max-px 1024]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import numpy as np

try:
    import tifffile
    from PIL import Image
except ImportError as exc:  # pragma: no cover - maintainer environment
    sys.exit(f"make_previews.py needs tifffile and Pillow ({exc}); install them and re-run")

SEGMENTER_LABELS = {
    "mesmer": "Mesmer",
    "deepcell_mesmer": "Mesmer",
    "cellpose": "Cellpose",
    "mccellpose": "MCCellpose",
}
NUCLEAR_RE = re.compile(r"^(dna|dapi|hoechst|hoe|nuclei|nuclear|h33342|draq5|syto)", re.I)
STAGE_SUFFIX_RE = re.compile(r"(?:\.ome)?(?:_backsub|_cp_masks|_mask|_masks)+$")
COLUMNS = [
    "preview_id",
    "sample",
    "stage",
    "channel",
    "channel_index",
    "image_path",
    "width",
    "height",
    "full_width",
    "full_height",
    "scale",
    "underlay_sample",
]
OUTLINE_RGB = (255, 214, 10)


def strip_stage(stem: str) -> str:
    previous = None
    while previous != stem:
        previous = stem
        stem = STAGE_SUFFIX_RE.sub("", stem)
    return stem


def sample_of(path: Path) -> str:
    """``TEST1`` for TEST1.ome.tif, TEST1_mask.tif and TEST1_backsub.ome_cp_masks.tif."""
    stem = re.sub(r"\.(ome\.)?tiff?$", "", path.name, flags=re.I)
    return strip_stage(stem) or stem


def safe(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()


def read_markers(path: Path | None) -> list[str]:
    """Marker names in channel order, every channel of the sheet (removed ones too)."""
    if path is None or not path.is_file():
        return []
    with path.open(newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        dialect = "excel-tab" if "\t" in sample.splitlines()[0] else "excel"
        rows = list(csv.DictReader(handle, dialect=dialect))

    def order(row: dict) -> int:
        try:
            return int(row.get("channel_number") or 0)
        except ValueError:
            return 0

    return [str(r.get("marker_name") or "").strip() for r in sorted(rows, key=order)]


def read_image(path: Path) -> np.ndarray:
    """The full-resolution level of an OME-TIFF as (channels, y, x)."""
    with tifffile.TiffFile(path) as tif:
        series = tif.series[0]
        data = series.levels[0].asarray() if series.levels else series.asarray()
        axes = series.axes
    if data.ndim == 2:
        return data[np.newaxis]
    if axes.endswith("YX") and data.ndim == 3:
        return data
    return data.reshape((-1, *data.shape[-2:]))


def stretch(channel: np.ndarray) -> np.ndarray:
    """uint8 of a channel, stretched to the 0.5-99.5th percentiles of its signal."""
    values = channel[channel > 0]
    if values.size == 0:
        return np.zeros(channel.shape, dtype=np.uint8)
    lo, hi = np.percentile(values, [0.5, 99.5])
    if hi <= lo:
        hi = lo + 1
    scaled = (channel.astype(np.float64) - lo) / (hi - lo)
    return (np.clip(scaled, 0, 1) * 255).astype(np.uint8)


def preview_size(width: int, height: int, max_px: int) -> tuple[int, int, float]:
    scale = min(1.0, max_px / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale)), scale


def resize(array: np.ndarray, size: tuple[int, int], nearest: bool = False) -> np.ndarray:
    if array.shape[1] == size[0] and array.shape[0] == size[1]:
        return array
    mode = Image.Resampling.NEAREST if nearest else Image.Resampling.LANCZOS
    if nearest:
        # Labels can exceed 8 bits: resize an index map, never the values.
        image = Image.fromarray(array.astype(np.int32), mode="I")
        return np.asarray(image.resize(size, mode)).astype(array.dtype)
    return np.asarray(Image.fromarray(array).resize(size, mode))


def outlines(labels: np.ndarray) -> np.ndarray:
    """Boolean boundary of every label: a labelled pixel next to another label."""
    edge = np.zeros(labels.shape, dtype=bool)
    edge[:-1, :] |= labels[:-1, :] != labels[1:, :]
    edge[1:, :] |= labels[1:, :] != labels[:-1, :]
    edge[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    edge[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    return edge & (labels > 0)


def channel_names(n_channels: int, markers: list[str]) -> list[str]:
    if len(markers) == n_channels and all(markers):
        return markers
    return [f"Channel {i + 1}" for i in range(n_channels)]


def composite_channels(names: list[str]) -> tuple[int, list[int]]:
    """The nuclear channel (blue) and up to two others (green, red)."""
    nuclear = next((i for i, n in enumerate(names) if NUCLEAR_RE.match(n)), 0)
    others = [i for i, n in enumerate(names) if i != nuclear and not NUCLEAR_RE.match(n)]
    return nuclear, others[:2]


def write_png(array: np.ndarray, path: Path) -> None:
    Image.fromarray(array).save(path, optimize=True)


def make_previews(root: Path, markers_path: Path | None, max_px: int) -> list[dict]:
    out_dir = root / "previews"
    out_dir.mkdir(parents=True, exist_ok=True)
    markers = read_markers(markers_path)
    rows: list[dict] = []
    masks: dict[str, list[tuple[str, Path]]] = {}
    for mask in sorted((root / "segmentation").glob("*/*.tif*")):
        tool = SEGMENTER_LABELS.get(mask.parent.name.lower(), mask.parent.name)
        masks.setdefault(sample_of(mask), []).append((tool, mask))

    for image_path in sorted((root / "registration").glob("*/*.tif*")):
        sample = sample_of(image_path)
        image = read_image(image_path)
        n_channels, full_h, full_w = image.shape
        width, height, _ = preview_size(full_w, full_h, max_px)
        scale = round(width / full_w, 6)
        names = channel_names(n_channels, markers)
        grey = [resize(stretch(image[c]), (width, height)) for c in range(n_channels)]

        def add(
            stage: str, channel: str, index: int, array: np.ndarray, underlay: bool = False
        ) -> None:
            name = f"{safe(sample)}_{safe(stage)}_{safe(channel)}.png"
            write_png(array, out_dir / name)
            rows.append(
                {
                    "preview_id": f"{sample}|{stage}|{channel}",
                    "sample": sample,
                    "stage": stage,
                    "channel": channel,
                    "channel_index": index,
                    "image_path": name,
                    "width": width,
                    "height": height,
                    "full_width": full_w,
                    "full_height": full_h,
                    "scale": scale,
                    "underlay_sample": sample if underlay else "",
                }
            )

        nuclear, others = composite_channels(names)
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        rgb[..., 2] = grey[nuclear]
        for slot, index in zip((1, 0), others, strict=False):
            rgb[..., slot] = grey[index]
        add("Registered", "Composite", 0, rgb)
        for c in range(n_channels):
            add("Registered", names[c], c + 1, grey[c], underlay=c == nuclear)
        for tool, mask_path in masks.get(sample, []):
            labels = tifffile.imread(mask_path)
            labels = labels.reshape(labels.shape[-2:])
            if labels.shape != (full_h, full_w):
                print(f"skip {mask_path}: {labels.shape} is not the image's {(full_h, full_w)}")
                continue
            edge = outlines(resize(labels, (width, height), nearest=True))
            base = (grey[nuclear].astype(np.float64) * 0.8).astype(np.uint8)
            over = np.stack([base, base, base], axis=-1)
            over[edge] = OUTLINE_RGB
            add("Segmentation", f"{tool} outlines", 0, over)

    with (out_dir / "previews.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("data_root", type=Path, help="the run's output directory (DATA_ROOT)")
    parser.add_argument(
        "--markers",
        type=Path,
        default=None,
        help="marker sheet naming the channels (default: DATA_ROOT/input/markers.csv)",
    )
    parser.add_argument("--max-px", type=int, default=1024, help="long side of a preview")
    args = parser.parse_args(argv)
    root = args.data_root.expanduser().resolve()
    markers = args.markers or root / "input" / "markers.csv"
    rows = make_previews(root, markers, args.max_px)
    samples = sorted({r["sample"] for r in rows})
    print(f"{len(rows)} preview(s) of {len(samples)} image(s) in {root / 'previews'}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
