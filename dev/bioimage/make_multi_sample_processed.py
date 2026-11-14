"""The multi-sample crops after preprocessing: the same field in a second state.

Each ``multi_sample/sample_X.zarr`` (one DNA channel, uint8) is processed the
way a nucleus image often is before segmentation, and written next to it as
``multi_sample/processed/sample_X_processed.zarr``:

1. background subtraction with a rolling ball (``skimage.restoration.rolling_ball``),
2. non-local means denoising (``skimage.restoration.denoise_nl_means``), with
   ``h`` set from the noise level ``estimate_sigma`` measures.

Same size, same pixel size, same frame as the original, so the Multi-sample tab
links the two tiles: pan or zoom one, the other shows the same nuclei, and the
reader sees what the preprocessing changed. The parameters are written into
each store's ``multiscales[0].metadata``.

Run from the repo root:

    uv run --no-project --python 3.12 --with scikit-image --with PyWavelets --with "zarr<3" \
        python dev/bioimage/make_multi_sample_processed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import zarr
from skimage import restoration

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_examples import (  # noqa: E402
    MITOSIS_XY_UM_NOMINAL,
    channel_window,
    make_compressor,
    write_ngff_store,
)

FOLDER = Path("depictio/projects/init/bioimage_examples/data/multi_sample")
SAMPLES = ("sample_A", "sample_B", "sample_C")
ROLLING_BALL_RADIUS = 25
NLM_PATCH_SIZE = 5
NLM_PATCH_DISTANCE = 6
# Filtering strength as a multiple of the measured noise sigma (scikit-image's
# own example uses 0.8 with fast_mode).
NLM_H_FACTOR = 0.8


def process(image: np.ndarray) -> tuple[np.ndarray, dict]:
    """Background-subtract then denoise one uint8 plane; return it as uint8."""
    plane = image.astype(np.float32)
    background = restoration.rolling_ball(plane, radius=ROLLING_BALL_RADIUS)
    flat = np.clip(plane - background, 0, None) / 255.0
    sigma = float(restoration.estimate_sigma(flat))
    denoised = restoration.denoise_nl_means(
        flat,
        h=NLM_H_FACTOR * sigma,
        sigma=sigma,
        patch_size=NLM_PATCH_SIZE,
        patch_distance=NLM_PATCH_DISTANCE,
        fast_mode=True,
    )
    out = np.clip(np.rint(denoised * 255.0), 0, 255).astype(np.uint8)
    params = {
        "rolling_ball_radius_px": ROLLING_BALL_RADIUS,
        "nl_means": {
            "patch_size": NLM_PATCH_SIZE,
            "patch_distance": NLM_PATCH_DISTANCE,
            "h": round(NLM_H_FACTOR * sigma, 5),
            "sigma_estimated": round(sigma, 5),
        },
    }
    return out, params


def main() -> int:
    out_dir = FOLDER / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    axes = [
        {"name": "c", "type": "channel"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]
    processed = {}
    params = {}
    for sample in SAMPLES:
        raw = zarr.open(str(FOLDER / f"{sample}.zarr" / "0"), mode="r")[:]
        processed[sample], params[sample] = process(raw[0])
    # One window for the three, as for the originals, so they read comparably.
    window = channel_window(np.stack(list(processed.values())), np.dtype(np.uint8))
    for sample in SAMPLES:
        path = out_dir / f"{sample}_processed.zarr"
        write_ngff_store(
            path,
            processed[sample][None],
            axes,
            [1.0, MITOSIS_XY_UM_NOMINAL, MITOSIS_XY_UM_NOMINAL],
            [{"label": "DNA (processed)", "color": "FFFFFF"}],
            f"{sample}_processed",
            levels=3,
            chunk=256,
            compressor=make_compressor("zlib", 5),
            windows=[window],
        )
        group = zarr.open_group(str(path), mode="r+")
        attrs = group.attrs.asdict()
        attrs["multiscales"][0]["metadata"]["processing"] = {
            "steps": ["skimage.restoration.rolling_ball", "skimage.restoration.denoise_nl_means"],
            **params[sample],
        }
        group.attrs.put(attrs)
        zattrs = path / ".zattrs"
        if not zattrs.read_text().endswith("\n"):
            zattrs.write_text(zattrs.read_text() + "\n")
        print(f"{path}: {params[sample]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
