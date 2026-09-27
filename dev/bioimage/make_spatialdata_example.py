"""Write the SpatialData example store of ``projects/init/bioimage_examples``.

Kept apart from ``make_examples.py`` because it needs the ``spatialdata``
library, which pulls zarr 3, while the OME-Zarr stores there are written with
zarr 2. ``make_examples.py`` runs this script in its own throwaway environment
(``uv run --with spatialdata==...``) and records what it returns in the
manifest; it can also be run on its own:

    uv run --no-project --python 3.12 \\
        --with "spatialdata==0.8.0" --with pooch \\
        python dev/bioimage/make_spatialdata_example.py \\
        --out depictio/projects/init/bioimage_examples/data

The store holds:

* ``images/he``: ``skimage.data.skin``, an H&E-stained skin section (RGB,
  cropped), with a 3-level pyramid;
* ``shapes/spots``: Visium-like circles on a hex grid over the tissue;
* ``points/nuclei``: nuclei centres, detected on the hematoxylin channel;
* ``tables/table``: an AnnData annotating ``spots`` (synthetic counts of four
  genes, a cluster, the number of nuclei under each spot).

Everything is written in the SpatialData 0.1 on-disk formats: zarr v2 and an
NGFF 0.4 image under ``images/he``. spatialdata 0.8 writes zarr v3 / NGFF 0.5
by default, which Depictio does not read yet, so the formats are passed
explicitly. The spot table is also exported to ``<store>_spots.csv``: that is
what Depictio reads, the AnnData stays in the store for SpatialData users.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_examples import kmeans, write_csv  # noqa: E402

STORE = "skin_spatialdata"
IMAGE = "he"
RGB_CHANNELS = [
    {"label": "Red", "color": "FF0000"},
    {"label": "Green", "color": "00FF00"},
    {"label": "Blue", "color": "0000FF"},
]


def make_store(out: Path, args: argparse.Namespace) -> dict:
    import anndata as ad
    import geopandas as gpd
    import pandas as pd
    import spatialdata as sd
    import spatialdata._io.format as sdf
    import zarr
    from shapely.geometry import Point
    from skimage import color, data, feature, filters
    from spatialdata.models import Image2DModel, PointsModel, ShapesModel, TableModel
    from spatialdata.transformations import Identity

    rng = np.random.default_rng(args.seed)
    skin = data.skin()  # (960, 1280, 3) uint8, H&E
    y0, x0 = args.crop_origin
    h, w = args.crop_size
    rgb = np.ascontiguousarray(skin[y0 : y0 + h, x0 : x0 + w])
    if rgb.shape[:2] != (h, w):
        raise SystemExit("--crop-origin + --crop-size leaves the skin image")

    # Colour deconvolution: hematoxylin (nuclei) and eosin (cytoplasm, collagen).
    hed = color.rgb2hed(rgb)
    hema = filters.gaussian(hed[..., 0], sigma=2)
    eosin = filters.gaussian(hed[..., 1], sigma=2)
    brightness = filters.gaussian(color.rgb2gray(rgb), sigma=2)
    tissue = brightness < args.tissue_threshold

    # Nuclei: local maxima of the smoothed hematoxylin signal inside tissue.
    peaks = feature.peak_local_max(
        filters.gaussian(hed[..., 0], sigma=args.nucleus_sigma),
        min_distance=args.nucleus_min_distance,
        threshold_abs=float(np.percentile(hema[tissue], args.nucleus_percentile)),
        labels=tissue.astype(np.int32),
    )
    peaks = peaks[np.lexsort((peaks[:, 1], peaks[:, 0]))]  # row-major, deterministic
    nuclei_xy = peaks[:, ::-1].astype(float)

    # Visium-like spots: hex grid, disk diameter 55 % of the pitch, kept when at
    # least half the disk is tissue.
    spacing = args.spot_spacing
    radius = max(2, int(round(spacing * 0.275)))
    yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    disk = (yy**2 + xx**2) <= radius**2
    spots = []
    for r, y in enumerate(np.arange(radius, h - radius, spacing * np.sqrt(3) / 2)):
        offset = spacing / 2 if r % 2 else 0.0
        for x in np.arange(radius + offset, w - radius, spacing):
            yi, xi = int(round(y)), int(round(x))
            window = (slice(yi - radius, yi + radius + 1), slice(xi - radius, xi + radius + 1))
            if tissue[window][disk].mean() < 0.5:
                continue
            spots.append((x, y, hema[window][disk].mean(), eosin[window][disk].mean()))
    arr = np.array(spots)
    spot_xy = arr[:, :2]

    # Nuclei under each spot (centre within the disk radius).
    dist = np.sqrt(((spot_xy[:, None, :] - nuclei_xy[None, :, :]) ** 2).sum(axis=2))
    n_nuclei = (dist <= radius).sum(axis=1)
    # Local nuclear density (per spot neighbourhood of one pitch) for clustering:
    # the disk count alone is too small to separate layers.
    density = (dist <= spacing).sum(axis=1)

    assign = kmeans(np.column_stack([arr[:, 2], arr[:, 3], density]), args.clusters, rng)
    # C1 is the most hematoxylin-rich group (epidermis and nevus nests).
    order = np.argsort([-arr[assign == j, 2].mean() for j in range(args.clusters)])
    rank = {int(j): i + 1 for i, j in enumerate(order)}
    clusters = [f"C{rank[int(a)]}" for a in assign]

    def norm(v: np.ndarray) -> np.ndarray:
        lo, hi = np.percentile(v, [2, 98])
        return np.clip((v - lo) / (hi - lo + 1e-9), 0, 1)

    h_n, e_n, d_n = norm(arr[:, 2]), norm(arr[:, 3]), norm(density.astype(float))
    depth = spot_xy[:, 1] / h
    genes = {
        "gene_A": rng.poisson(1 + 30 * h_n),  # follows hematoxylin
        "gene_B": rng.poisson(1 + 25 * e_n),  # follows eosin
        "gene_C": rng.poisson(1 + 20 * d_n),  # follows nuclear density
        "gene_D": rng.poisson(2 + 10 * depth),  # a top-to-bottom gradient, stain-independent
    }
    counts = np.column_stack(list(genes.values())).astype(np.int32)
    spot_ids = [f"spot_{i:04d}" for i in range(1, len(arr) + 1)]

    # --- SpatialData elements, all in the pixel frame of the image ------------
    identity = {"global": Identity()}
    image = Image2DModel.parse(
        rgb.transpose(2, 0, 1),
        dims=("c", "y", "x"),
        c_coords=[c["label"] for c in RGB_CHANNELS],
        scale_factors=[2] * (args.levels - 1),
        chunks=(1, args.chunk, args.chunk),
        transformations=identity,
    )
    shapes = ShapesModel.parse(
        gpd.GeoDataFrame(
            {"radius": np.full(len(arr), float(radius))},
            geometry=[Point(float(x), float(y)) for x, y in spot_xy],
            index=pd.Index(spot_ids, name="spot_id"),
        ),
        transformations=identity,
    )
    points = PointsModel.parse(
        pd.DataFrame({"x": nuclei_xy[:, 0], "y": nuclei_xy[:, 1]}),
        transformations=identity,
    )
    obs = pd.DataFrame(
        {
            "region": pd.Categorical(["spots"] * len(arr)),
            "spot_id": spot_ids,
            "cluster": pd.Categorical(clusters),
            "n_nuclei": n_nuclei.astype(np.int32),
        },
        index=pd.Index(spot_ids),
    )
    adata = ad.AnnData(
        X=counts,
        obs=obs,
        var=pd.DataFrame(index=pd.Index(list(genes))),
        obsm={"spatial": spot_xy.astype(np.float64)},
    )
    table = TableModel.parse(adata, region="spots", region_key="region", instance_key="spot_id")
    sdata = sd.SpatialData(
        images={IMAGE: image},
        shapes={"spots": shapes},
        points={"nuclei": points},
        tables={"table": table},
    )

    store = out / f"{STORE}.zarr"
    if store.exists():
        shutil.rmtree(store)
    sdata.write(
        store,
        consolidate_metadata=False,
        sdata_formats=[
            sdf.SpatialDataContainerFormatV01(),
            sdf.RasterFormatV01(),
            sdf.PointsFormatV01(),
            sdf.ShapesFormatV02(),
            sdf.TablesFormatV01(),
        ],
    )
    # spatialdata writes channel labels only. Colours and contrast windows are
    # standard NGFF 0.4 `omero` fields a viewer reads to draw RGB as RGB.
    group = zarr.open_group(store / "images" / IMAGE, mode="r+")
    group.attrs["omero"] = {
        "channels": [
            {
                "active": True,
                "coefficient": 1,
                "color": ch["color"],
                "family": "linear",
                "inverted": False,
                "label": ch["label"],
                "window": {"start": 0.0, "end": 255.0, "min": 0.0, "max": 255.0},
            }
            for ch in RGB_CHANNELS
        ],
        "rdefs": {"model": "color"},
    }
    sdata.write_consolidated_metadata()
    # zarr writes its JSON metadata without a final newline, which the repo's
    # end-of-file-fixer hook would add on commit; adding it here keeps a
    # regenerated store identical to the committed one.
    for meta in store.rglob(".z*"):
        text = meta.read_text()
        if not text.endswith("\n"):
            meta.write_text(text + "\n")
    _check_store(store, args.levels)

    write_csv(
        out / f"{STORE}_spots.csv",
        [
            "spot_id",
            "sample",
            "x",
            "y",
            "cluster",
            "n_nuclei",
            "total_counts",
            *genes,
        ],
        [
            [
                sid,
                STORE,
                round(float(x), 2),
                round(float(y), 2),
                cl,
                int(n),
                int(row.sum()),
                *(int(v) for v in row),
            ]
            for sid, (x, y), cl, n, row in zip(
                spot_ids, spot_xy, clusters, n_nuclei, counts, strict=True
            )
        ],
    )
    size = sum(f.stat().st_size for f in store.rglob("*") if f.is_file())
    return {
        "store": f"{STORE}.zarr",
        "image_path": f"images/{IMAGE}",
        "bytes": size,
        "rows": len(arr),
        "nuclei": len(nuclei_xy),
        "spatialdata_version": sd.__version__,
        "zarr_version": zarr.__version__,
    }


def _check_store(store: Path, levels: int) -> None:
    """Zarr v2 + NGFF 0.4 under images/he, and readable back by spatialdata."""
    import spatialdata as sd

    if any(store.rglob("zarr.json")):
        raise RuntimeError(f"{store}: zarr v3 metadata written (zarr.json)")
    attrs = json.loads((store / "images" / IMAGE / ".zattrs").read_text())
    ms = attrs["multiscales"][0]
    if ms["version"] != "0.4" or len(ms["datasets"]) != levels:
        raise RuntimeError(f"{store}: expected NGFF 0.4 with {levels} levels, got {ms}")
    with warnings.catch_warnings():
        # Reading a 0.1-format store warns that it is not the current format:
        # that is the point here.
        warnings.filterwarnings("ignore", message="SpatialData is not stored in the most current")
        back = sd.read_zarr(store)
    if set(back.images) != {IMAGE} or "spots" not in back.shapes or "table" not in back.tables:
        raise RuntimeError(f"{store}: unexpected elements after read-back: {back}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, required=True, help="Output data directory")
    p.add_argument("--seed", type=int, default=1086, help="RNG seed (clusters, counts)")
    p.add_argument("--levels", type=int, default=3, help="Pyramid levels of the image")
    p.add_argument("--chunk", type=int, default=256, help="Chunk edge along y and x")
    p.add_argument("--crop-origin", type=int, nargs=2, default=(192, 64), metavar=("Y", "X"))
    p.add_argument("--crop-size", type=int, nargs=2, default=(640, 896), metavar=("H", "W"))
    p.add_argument("--spot-spacing", type=float, default=32.0, help="Spot pitch in pixels")
    p.add_argument("--clusters", type=int, default=4, help="Spot clusters")
    p.add_argument(
        "--tissue-threshold",
        type=float,
        default=0.8,
        help="Grey level under which a pixel counts as tissue",
    )
    p.add_argument("--nucleus-sigma", type=float, default=2.0, help="Smoothing before detection")
    p.add_argument("--nucleus-min-distance", type=int, default=4, help="px between nuclei")
    p.add_argument(
        "--nucleus-percentile",
        type=float,
        default=75.0,
        help="Hematoxylin percentile (over tissue) a nucleus centre must exceed",
    )
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
            f"spots, {result['nuclei']} nuclei (spatialdata {result['spatialdata_version']})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
