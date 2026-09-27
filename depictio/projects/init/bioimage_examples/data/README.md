# OME-Zarr example data

Small NGFF 0.4 image stores and the tables derived from them, for the
`bioimage_examples` project. Every image comes from a scikit-image sample
dataset under a permissive licence; every table is computed from those pixels
by `dev/bioimage/make_examples.py`. Nothing here is an experimental result.

## Files

| Path | What it is | Source image |
| --- | --- | --- |
| `kidney_2d.zarr` | 3-channel fluorescence, 512 x 512, uint16, `c,y,x` | `skimage.data.kidney`, maximum projection over z |
| `kidney_2d_cells.csv` | One row per segmented nucleus: centroid, area, mean intensity per channel, dominant channel | derived |
| `ihc_spatial.zarr` | RGB brightfield tissue, 512 x 512, uint8, `c,y,x` (one channel per colour) | `skimage.data.immunohistochemistry` |
| `ihc_spatial_spots.csv` | Visium-like spots on a hex grid over the tissue: cluster and three synthetic gene counts | derived |
| `kidney_3d_timelapse.zarr` | 2 channels x 8 z-planes x 5 timepoints, 192 x 192, uint8, `t,c,z,y,x` | `skimage.data.kidney`, cropped |
| `kidney_3d_timelapse_nuclei.csv` | Nuclei of the first timepoint, segmented in 3D: centroid, depth band, volume | derived |
| `multi_sample/sample_{A,B,C}.zarr` | One DNA channel, 256 x 256, uint8, `c,y,x` | `skimage.data.human_mitosis`, three crops |
| `multi_sample/cells.csv` | One row per nucleus of the three samples, with a heuristic `phase` | derived |
| `multi_sample/samples.csv` | Sample sheet. `sample` equals the store name without `.zarr` | derived |
| `manifest.json` | Generator arguments and store sizes | derived |

All `x` / `y` columns are level-0 pixel coordinates of the matching store
(column, row), so a viewer overlays them with `points_scale: 1`.

## Stores

- NGFF 0.4, zarr v2, `dimension_separator: "/"`, zlib-compressed chunks of at
  most 256 x 256 in y/x (one plane per chunk on the other axes).
- Three pyramid levels, each a 2x mean downsampling of y and x
  (`coordinateTransformations` scale doubles per level; z, c and t are not
  downsampled).
- An `omero` block names and colours every channel and sets its contrast
  window from the 0.5 / 99.5 percentiles (RGB and the three samples use one
  fixed window so they display alike).

Physical pixel sizes:

- `kidney_*`: 1.24 um in x/y and 1.25 um in z, as documented by scikit-image.
  The volume keeps every second plane, so its z step is 2.5 um. The time
  axis is nominal: 60 s between frames.
- `ihc_spatial`: 0.5 um, **nominal**. The source image carries no calibration.
- `multi_sample/*`: 0.65 um, **nominal**, for the same reason.

## What is synthetic

- The time-lapse is not a recording. Each frame is the same kidney volume,
  cropped at a window that moves 6 px down and 8 px right per frame, with
  8 % of the signal removed per frame to mimic photobleaching.
- The spots imitate the Visium layout (hexagonal grid, spot diameter 55 % of
  the pitch) at a much smaller pitch (14 px) than a real slide would have at
  this resolution. Spots are kept where at least half the disk is tissue.
  Clusters are k-means on each spot's mean hematoxylin, DAB and brightness
  (colour deconvolution with `skimage.color.rgb2hed`), numbered so that `C1`
  is the most DAB-positive. `gene_A` is Poisson with a mean that follows DAB,
  `gene_B` follows hematoxylin, and `gene_C` follows a left-to-right gradient
  that ignores the stain.
- Nuclei come from an Otsu threshold and a distance-transform watershed. The
  `phase` column of `multi_sample/cells.csv` calls a nucleus "mitotic" when
  it is among the brightest 15 % and not larger than the median: condensed
  chromatin, not a trained classifier.
- The `condition` and `replicate` columns of `samples.csv` are labels for the
  demo. They are not the conditions of the screen the image comes from.

## Licences

| Dataset | Licence | Credit |
| --- | --- | --- |
| `kidney` | CC0 | Genevieve Buckley, Monash Micro Imaging, 2018 (confocal, mouse kidney slide) |
| `immunohistochemistry` | No known copyright restrictions | Center for Microscopy and Molecular Imaging (CMMI), colonic glands with FHL2 (DAB) and hematoxylin |
| `human_mitosis` | CC0 | David Root; Moffat et al., Cell 124(6):1283-98, 2006, doi:10.1016/j.cell.2006.01.040 |

The derived stores and tables are released under the same terms as their
source image. `skimage.data.cells3d` was deliberately not used: it comes from
the Allen Institute for Cell Science under the Allen Institute terms of use,
which are not a CC0 or CC-BY grant.

## Regenerating

From the repository root (the dependencies are fetched for this one run, they
are not Depictio dependencies):

```bash
uv run --no-project --python 3.12 \
    --with scikit-image --with "zarr<3" --with "ome-zarr<0.11" --with pooch \
    python dev/bioimage/make_examples.py \
    --out depictio/projects/init/bioimage_examples/data
```

`pooch` downloads `kidney` and `human_mitosis` into the scikit-image cache on
first use. The output is byte-identical across runs for the same `--seed` and
library versions (generated with scikit-image 0.26.0, zarr 2.18.7,
numcodecs 0.15.1, ome-zarr 0.10.3). `--help` lists the size, crop, drift,
spot and codec options.
