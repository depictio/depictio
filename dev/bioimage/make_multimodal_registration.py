"""Generate the multimodal registration example of ``projects/init/bioimage_examples``.

Two techniques, one tissue core: bright field (BF, an H&E-stained section, RGB)
and second-harmonic generation (SHG, the collagen fibres, one channel), from the
Eliceiri multimodal registration dataset (Zenodo 3874362, CC BY 4.0, test set).
Each core of the test set comes as a reference BF image and an SHG image that
was rotated (up to 30 degrees) and shifted (up to 100 px); the corners of the
displaced image are given in the reference frame (``metadata.csv``), the ground
truth a registration is scored against.

For each picked core this runs elastix (itk-elastix) to bring the SHG image into
the BF frame, with mutual information as the metric (the two techniques share no
intensities), in the steps a user would try one after the other:

1. ``raw``: the SHG image as acquired, uncorrected.
2. ``rigid_intensity``: a rigid (Euler) fit of the SHG on the BF brightness. BF
   brightness says little about collagen, so this mostly fails.
3. ``rigid_stroma``: the same fit on what the stain says of the stroma: eosin
   minus haematoxylin from an H&E colour deconvolution (Ruifrok and Johnston
   2001; eosin stains collagen pink, haematoxylin the nuclei around it), both
   images smoothed (Gaussian, 3 px) so the fit follows the fibre bundles rather
   than single fibres. Started from seven rotations (-30 to 30 degrees) and kept
   at the start with the highest mutual information: one start does not reach a
   30 degree rotation.
4. ``affine``: an affine fit started from step 3, on the same channel.

Of the three cores, two land within a few pixels of the truth and one
(``1B_J2``, the largest displacement) does not: ``corner_err_px`` says so.

It writes, under ``multimodal/``:

* ``{core}_bf.zarr``: the BF reference, RGB as three channels (CYX), the fixed
  image of every step.
* ``{core}_{step}.zarr``: the SHG image in the BF frame after that step.
* ``multimodal_steps.csv``: one row per core and step; ``corner_err_px`` (mean
  distance between where the step puts the four corners of the SHG image and
  where they truly are, in reference pixels; for ``raw`` it is the dataset's own
  ``Displacement``), ``nmi`` (normalised mutual information of the stroma channel
  of step 3 and the resampled SHG, Studholme's (H(A) + H(B)) / H(A, B), over the pixels the
  SHG image covers), ``rotation_deg`` (the rotation the step recovered),
  ``runtime_s`` (measured) and the elastix parameters it ran with.

All OME-Zarr NGFF 0.4, two pyramid levels. Nothing is simulated: the outputs
and the metrics are what elastix produced on the machine that ran this.

Run from the repo root with throwaway dependencies, the archive extracted in its
own folder:

    uv run --no-project --python 3.12 --with itk-elastix --with tifffile \\
        --with scikit-image --with numpy --with "zarr<3" \\
        python -I dev/bioimage/make_multimodal_registration.py \\
        --testset <dir>/TestSet --metadata <dir>/metadata.csv \\
        --out depictio/projects/init/bioimage_examples/data
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import time
from pathlib import Path

import itk
import numpy as np
import tifffile
import zarr
from numcodecs import Blosc
from scipy import ndimage
from skimage.color import rgb2hed

NGFF = "0.4"
COMPRESSOR = Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)
AXES = [
    {"name": "c", "type": "channel"},
    {"name": "y", "type": "space"},
    {"name": "x", "type": "space"},
]
BF_CHANNELS = [("Red", "FF0000"), ("Green", "00FF00"), ("Blue", "0000FF")]
SHG_CHANNELS = [("SHG", "FF00FF")]
#: Cores across the test set's range of displacement (small, middle, large).
CORES = ["1B_B8", "2B_E4", "1B_J2"]
STEPS = ["raw", "rigid_intensity", "rigid_stroma", "affine"]
LABELS = {
    "raw": "As acquired",
    "rigid_intensity": "Rigid, BF brightness",
    "rigid_stroma": "Rigid, stroma, 7 starts",
    "affine": "Affine, stroma",
}
TRANSFORM = {
    "raw": "none",
    "rigid_intensity": "rigid",
    "rigid_stroma": "rigid",
    "affine": "affine",
}
#: Where the multi-start rigid step begins, in degrees.
STARTS_DEG = [-30, -20, -10, 0, 10, 20, 30]
#: Gaussian smoothing of both images for the stroma fit, in pixels.
SMOOTH_PX = 3.0
STROMA = "eosin minus haematoxylin (H&E colour deconvolution)"

RIGID = {
    "Transform": "EulerTransform",
    "Metric": "AdvancedMattesMutualInformation",
    "NumberOfHistogramBins": 32,
    "Optimizer": "AdaptiveStochasticGradientDescent",
    "NumberOfResolutions": 4,
    "MaximumNumberOfIterations": 500,
    "AutomaticTransformInitialization": "true",
    "AutomaticTransformInitializationMethod": "CenterOfGravity",
}
AFFINE = {
    "Transform": "AffineTransform",
    "Metric": "AdvancedMattesMutualInformation",
    "NumberOfHistogramBins": 32,
    "Optimizer": "AdaptiveStochasticGradientDescent",
    "NumberOfResolutions": 3,
    "MaximumNumberOfIterations": 500,
    # It starts from the rigid fit: no re-centring on top of it.
    "AutomaticTransformInitialization": "false",
}
#: What each step ran with, as the history shows it: the elastix parameter-map
#: keys it set on the default map, and what it was fitted on.
PARAMETERS: dict[str, dict] = {
    "raw": {},
    "rigid_intensity": {"FixedImage": "BF brightness (inverted)", **RIGID},
    "rigid_stroma": {
        "FixedImage": STROMA,
        "SmoothingPx": SMOOTH_PX,
        "StartRotationsDeg": STARTS_DEG,
        "KeptStart": "highest mutual information",
        **RIGID,
    },
    "affine": {
        "FixedImage": STROMA,
        "SmoothingPx": SMOOTH_PX,
        "InitialTransform": "rigid, stroma",
        **AFFINE,
    },
}


# ---- Writing ------------------------------------------------------------------


def write_image(path: Path, arr: np.ndarray, channels: list[tuple[str, str]]) -> None:
    """An NGFF 0.4 multiscale CYX uint8 image at ``path``: two levels, halving y and x."""
    shutil.rmtree(path, ignore_errors=True)
    group = zarr.open_group(str(path), mode="w")
    datasets = []
    level = arr
    for i in range(2):
        group.create_dataset(
            str(i),
            data=level,
            chunks=(1, 256, 256),
            compressor=COMPRESSOR,
            dimension_separator="/",
            overwrite=True,
        )
        datasets.append(
            {
                "path": str(i),
                "coordinateTransformations": [
                    {"type": "scale", "scale": [1.0, float(2**i), float(2**i)]}
                ],
            }
        )
        level = level[:, ::2, ::2]
    windows = []
    for plane in arr:
        lo, hi = float(np.percentile(plane, 0.5)), float(np.percentile(plane, 99.8))
        windows.append((lo, hi if hi > lo else lo + 1))
    group.attrs.update(
        {
            "multiscales": [
                {"version": NGFF, "name": path.stem, "axes": AXES, "datasets": datasets}
            ],
            "omero": {
                "channels": [
                    {
                        "label": label,
                        "color": color,
                        "active": True,
                        "window": {"start": w[0], "end": w[1], "min": 0, "max": 255},
                    }
                    for (label, color), w in zip(channels, windows)
                ],
                "rdefs": {"model": "color"},
            },
        }
    )


# ---- Registration ---------------------------------------------------------------


def parameter_map(kind: str, keys: dict) -> dict:
    """elastix's default ``kind`` map with the elastix keys of ``keys`` set."""
    pmap = itk.ParameterObject.GetDefaultParameterMap(kind, keys["NumberOfResolutions"])
    for key, value in keys.items():
        pmap[key] = [str(value)]
    pmap["FinalBSplineInterpolationOrder"] = ["1"]
    pmap["ResultImagePixelType"] = ["float"]
    return pmap


def rotation_start(shape: tuple[int, int], degrees: float) -> "itk.ParameterObject":
    """A fixed Euler transform about the image centre: where a rigid fit starts."""
    h, w = shape
    obj = itk.ParameterObject.New()
    obj.AddParameterMap(
        {
            "Transform": ["EulerTransform"],
            "NumberOfParameters": ["3"],
            "TransformParameters": [str(math.radians(degrees)), "0", "0"],
            "CenterOfRotationPoint": [str((w - 1) / 2), str((h - 1) / 2)],
            "InitialTransformParametersFileName": ["NoInitialTransform"],
            "HowToCombineTransforms": ["Compose"],
            "FixedImageDimension": ["2"],
            "MovingImageDimension": ["2"],
            "FixedInternalImagePixelType": ["float"],
            "MovingInternalImagePixelType": ["float"],
            "Size": [str(w), str(h)],
            "Index": ["0", "0"],
            "Spacing": ["1", "1"],
            "Origin": ["0", "0"],
            "Direction": ["1", "0", "0", "1"],
            "UseDirectionCosines": ["true"],
            "ResampleInterpolator": ["FinalLinearInterpolator"],
            "Resampler": ["DefaultResampler"],
            "DefaultPixelValue": ["0"],
            "ResultImagePixelType": ["float"],
        }
    )
    return obj


def to_itk(arr: np.ndarray) -> "itk.Image":
    return itk.image_from_array(np.ascontiguousarray(arr, dtype=np.float32))


def register(fixed: np.ndarray, moving: np.ndarray, maps: list[dict], start=None):
    """elastix on ``fixed`` / ``moving``, the ``maps`` run one after the other (each
    started from the one before, and the first from ``start``). The transform it
    returns holds every map, ``start`` first; and the moving image resampled into
    the fixed frame."""
    obj = itk.ParameterObject.New()
    for pmap in maps:
        obj.AddParameterMap(pmap)
    kwargs = {"initial_transform_parameter_object": start} if start is not None else {}
    result, params = itk.elastix_registration_method(
        to_itk(fixed), to_itk(moving), parameter_object=obj, log_to_console=False, **kwargs
    )
    return params, itk.array_from_image(result)


def resample(moving: np.ndarray, params: "itk.ParameterObject") -> np.ndarray:
    """``moving`` through a fitted transform, into the fixed frame (transformix)."""
    return itk.array_from_image(itk.transformix_filter(to_itk(moving), params))


def multi_start(fixed: np.ndarray, moving: np.ndarray, pmap: dict):
    """The rigid fit from every start of ``STARTS_DEG``, kept where it agrees best."""
    best = None
    for degrees in STARTS_DEG:
        params, resampled = register(fixed, moving, [pmap], rotation_start(fixed.shape, degrees))
        score = nmi(fixed, resampled, resampled > 0)
        if best is None or score > best[0]:
            best = (score, params, resampled)
    assert best is not None
    return best[1], best[2]


def transform_points(params: "itk.ParameterObject", points: np.ndarray) -> np.ndarray:
    """Map fixed-frame (x, y) points through every map of ``params`` (elastix composes
    an initial transform first), the way transformix would."""
    out = points.astype(float).copy()
    # Each map has the one before as its initial transform, composed the
    # elastix way: T(p) = T_1(T_0(p)), the first map applied first.
    for i in range(params.GetNumberOfParameterMaps()):
        pmap = params.GetParameterMap(i)
        out = np.array([_apply(pmap, p) for p in out])
    return out


def _apply(pmap, p: np.ndarray) -> np.ndarray:
    kind = pmap["Transform"][0]
    tp = [float(v) for v in pmap["TransformParameters"]]
    c = np.array([float(v) for v in pmap["CenterOfRotationPoint"]])
    if kind == "EulerTransform":
        theta, tx, ty = tp
        a = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
        t = np.array([tx, ty])
    elif kind == "AffineTransform":
        a = np.array(tp[:4]).reshape(2, 2)
        t = np.array(tp[4:6])
    else:
        raise ValueError(kind)
    return a @ (p - c) + c + t


def rotation_deg(params: "itk.ParameterObject" | None) -> float:
    if params is None:
        return 0.0
    m = transform_points(params, np.array([[0.0, 0.0], [1.0, 0.0]]))
    d = m[1] - m[0]
    return math.degrees(math.atan2(d[1], d[0]))


def nmi(a: np.ndarray, b: np.ndarray, mask: np.ndarray, bins: int = 32) -> float:
    """Studholme's normalised mutual information, (H(A) + H(B)) / H(A, B)."""
    joint, _, _ = np.histogram2d(a[mask], b[mask], bins=bins)
    p = joint / joint.sum()

    def h(q: np.ndarray) -> float:
        q = q[q > 0]
        return float(-(q * np.log(q)).sum())

    return (h(p.sum(1)) + h(p.sum(0))) / h(p)


# ---- One core --------------------------------------------------------------------


def corners_truth(meta: dict) -> tuple[np.ndarray, np.ndarray]:
    """The displaced image's own corners (its pixel frame) and where they truly lie
    in the reference frame, both (x, y)."""
    own = np.array([[meta[f"X{i}_Ref"], meta[f"Y{i}_Ref"]] for i in range(1, 5)], float)
    truth = np.array([[meta[f"X{i}_Trans"], meta[f"Y{i}_Trans"]] for i in range(1, 5)], float)
    return own, truth


def make_core(testset: Path, out: Path, core: str, meta: dict) -> list[dict]:
    bf = tifffile.imread(testset / f"R_{core}_BF.tif")  # (y, x, 3) uint8
    shg = tifffile.imread(testset / f"T_{core}_SHG.tif").astype(np.float32)  # (y, x)
    write_image(out / f"{core}_bf.zarr", np.moveaxis(bf, -1, 0), BF_CHANNELS)
    # BF brightness, inverted (dense tissue is dark in BF, collagen bright in
    # SHG), and the stroma channel, what an H&E stain shows of collagen.
    brightness = 255.0 - bf.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    hed = rgb2hed(bf)
    stroma = ndimage.gaussian_filter((hed[..., 1] - hed[..., 0]).astype(np.float32), SMOOTH_PX)
    shg_smooth = ndimage.gaussian_filter(shg, SMOOTH_PX)
    own, truth = corners_truth(meta)

    rigid = parameter_map("rigid", RIGID)
    rows: list[dict] = []
    kept = None
    for i, step in enumerate(STEPS):
        start = time.perf_counter()
        if step == "raw":
            params, resampled = None, shg
        elif step == "rigid_intensity":
            params, resampled = register(brightness, shg, [rigid])
        elif step == "rigid_stroma":
            params, _ = multi_start(stroma, shg_smooth, rigid)
            resampled = resample(shg, params)
            kept = params
        else:
            params, _ = register(
                stroma, shg_smooth, [parameter_map("affine", AFFINE)], start=kept
            )
            resampled = resample(shg, params)
        runtime = time.perf_counter() - start
        if params is None:
            # Identity: the displaced image's corners sit at its own frame's corners.
            err = float(np.mean(np.hypot(*(own - truth).T)))
        else:
            # elastix maps fixed (BF) points to moving (SHG) points: the true
            # corners in the BF frame should land on the SHG image's corners.
            err = float(np.mean(np.hypot(*(transform_points(params, truth) - own).T)))
        img = np.clip(np.round(resampled), 0, 255).astype(np.uint8)
        write_image(out / f"{core}_{step}.zarr", img[None], SHG_CHANNELS)
        rows.append(
            {
                "core": core,
                "step": LABELS[step],
                "step_order": i,
                "transform": TRANSFORM[step],
                "store": f"{core}_{step}.zarr",
                "fixed_store": f"{core}_bf.zarr",
                "corner_err_px": f"{err:.2f}",
                "nmi": f"{nmi(stroma, resampled, resampled > 0):.4f}",
                "rotation_deg": f"{rotation_deg(params):.2f}",
                "displacement_px": f"{float(meta['Displacement']):.2f}",
                "runtime_s": f"{runtime:.1f}" if params is not None else "0.0",
                "tool": "input image" if params is None else f"itk-elastix {itk.__version__}",
                "duration": "" if params is None else f"{runtime:.1f} s",
                "parameters": json.dumps(PARAMETERS[step]) if PARAMETERS[step] else "",
            }
        )
    return rows


def check_story(rows: list[dict]) -> None:
    """The data must say what the dashboard says: the stroma fit brings 1B_B8 and
    2B_E4 onto the BF image, the brightness fit does not, and 1B_J2 stays off."""
    err = {(r["core"], r["step"]): float(r["corner_err_px"]) for r in rows}
    raw, naive, stroma = LABELS["raw"], LABELS["rigid_intensity"], LABELS["rigid_stroma"]
    for core in ("1B_B8", "2B_E4"):
        assert err[core, stroma] < err[core, raw] / 10 < err[core, naive] / 10, core
    assert err["1B_J2", stroma] > err["1B_J2", raw] / 10, "1B_J2"


def read_metadata(path: Path) -> dict[str, dict]:
    with path.open() as fh:
        return {
            row["Filename"].rstrip("_"): {k: float(v) for k, v in row.items() if k != "Filename"}
            for row in csv.DictReader(fh, delimiter=";")
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--testset", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cores", nargs="+", default=CORES)
    args = parser.parse_args()
    meta = read_metadata(args.metadata)
    folder = args.out / "multimodal"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    rows: list[dict] = []
    for core in args.cores:
        rows += make_core(args.testset, folder, core, meta[core])
    if args.cores == CORES:
        check_story(rows)
    with (folder / "multimodal_steps.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for r in rows:
        print(r["core"], r["step"], r["corner_err_px"], r["nmi"], r["rotation_deg"], r["runtime_s"])


if __name__ == "__main__":
    main()
