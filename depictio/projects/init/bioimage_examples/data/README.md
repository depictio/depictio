# Bioimage example data

Small images and the tables derived from them, for the `bioimage_examples`
project: NGFF 0.4 OME-Zarr stores, one pyramidal OME-TIFF, one SpatialData
store and one NGFF 0.5 OME-Zarr store with sharded arrays. Every image comes
from a scikit-image sample dataset under a permissive licence; every table is
computed from those pixels by `dev/bioimage/make_examples.py` (and
`dev/bioimage/make_spatialdata_example.py` and
`dev/bioimage/make_ngff05_example.py`, which it runs). Nothing here is an
experimental result.

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
| `lily_stem.ome.tif` | 2-channel fluorescence, 480 x 480, uint8, pyramidal OME-TIFF | `skimage.data.lily`, channels 1 and 2, cropped |
| `lily_stem_cells.csv` | One row per plant cell: centroid, lumen area, mean intensity per channel, wall type | derived |
| `skin_spatialdata.zarr` | SpatialData store: H&E image (640 x 896, uint8 RGB), spot circles, nucleus points, an AnnData table | `skimage.data.skin`, cropped |
| `lily_sharded.zarr` | 3-channel fluorescence, 512 x 512, uint16 (12-bit), `c,y,x`, NGFF 0.5 with sharded arrays | `skimage.data.lily`, channels 1, 2 and 4, lower left crop |
| `lily_sharded_cells.csv` | One row per plant cell: centroid, lumen area, mean intensity per channel, wall type | derived |
| `manifest.json` | Generator arguments and store sizes | derived |

All `x` / `y` columns are level-0 pixel coordinates of the matching image
(column, row), so a viewer overlays them with `points_scale: 1`.

## OME-Zarr stores (NGFF 0.4)

`kidney_2d`, `ihc_spatial`, `kidney_3d_timelapse` and `multi_sample/*`:

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
- `lily_stem` and `lily_sharded`: 1.24 um, as documented by scikit-image.
- `skin_spatialdata`: none. SpatialData keeps the image in its pixel frame
  (identity transform to the `global` coordinate system) and the source
  image carries no calibration.

## OME-TIFF

`lily_stem.ome.tif` is one file the viewer reads with HTTP Range requests:

- OME-XML (in the first IFD) names and colours both channels and sets
  `PhysicalSizeX` / `PhysicalSizeY` to 1.24 um.
- One uint8 plane per top-level IFD (`CYX`, not interleaved), tiled 256 x 256,
  zlib (deflate) compressed.
- Three levels: the two reduced ones are SubIFDs of each plane, each a 2x
  mean downsampling, so level n is exactly level 0 shifted right by n
  (480, 240, 120).
- 12-bit to 8-bit per channel on the crop's 0.5 / 99.8 percentiles, two of
  the four channels and a 480 px crop: a single file cannot be split into
  chunk files like a zarr store, and the repository's
  `check-added-large-files` hook caps one file at 500 kB.
- lily's channels carry no documented stain, so they are named by what they
  show: Ch1 (cell walls, magenta) and Ch2 (thick walls, green). Ch3 is a
  dimmer copy of Ch2 and Ch4 looks much like Ch1.

## SpatialData store

`skin_spatialdata.zarr` is written by the `spatialdata` library (the version
is recorded in the root `zarr.json` and in `manifest.json`) and read back with it:

| Element | What it is |
| --- | --- |
| `images/he` | The H&E crop, `c,y,x`, 3 levels (`s0`, `s1`, `s2`), chunks of 1 x 256 x 256 (not sharded), zstd |
| `shapes/spots` | Visium-like circles (hex grid, 32 px pitch, radius 9 px) where at least half the disk is tissue |
| `points/nuclei` | Nucleus centres: local maxima of the smoothed hematoxylin channel |
| `tables/table` | AnnData annotating `spots` (`region_key: region`, `instance_key: spot_id`): four synthetic gene counts in `X`, `cluster` and `n_nuclei` in `obs`, centres in `obsm["spatial"]` |

It is written in spatialdata 0.8's default on-disk formats: zarr v3 (a
`zarr.json` per node, chunk keys under `c/`) with an NGFF 0.5 image, whose
metadata sits under `attributes.ome` in `images/he/zarr.json`. spatialdata
records that image's version as `0.5-dev-spatialdata` rather than `0.5`: its
coordinate systems go beyond the 0.5 specification. spatialdata records
channel labels only; the generator adds the NGFF `omero` colours and windows
to `images/he` (red, green, blue, 0 to 255) and then consolidates the metadata
(into the root `zarr.json`), so the image renders as RGB.

Depictio shows the `images/he` element (the DC's `image_path`) and uploads only
that subtree. The spot table it filters on is read from the same store: a
`format: spatialdata` table DC takes the `obs` columns of `tables/table`, the
spot centres from `obsm["spatial"]` converted to `images/he` pixels, and the
four genes from `X`. Nothing is exported by hand, and re-running the CLI after
the AnnData changes re-extracts the table.

## NGFF 0.5 store (sharded)

`lily_sharded.zarr` is an OME-Zarr store in the NGFF 0.5 layout, written with
zarr-python 3 (the version is in `manifest.json`):

- zarr v3: a `zarr.json` per group and array, `dimension_names` on every
  array, chunk keys under `c/`. The OME metadata is under `attributes.ome` of
  the root `zarr.json`: `version: "0.5"`, a `multiscales` block (three levels,
  2x mean downsampling of y and x, physical `scale` transforms) and an
  `omero` block with channel names, colours and contrast windows.
- Every array is sharded (`sharding_indexed` codec): chunks of 1 x 128 x 128,
  zstd-compressed, packed into shards of 1 x 256 x 256, so a shard file holds
  up to 2 x 2 chunks of one channel (level 2, 128 x 128, fills one of the four
  slots of its shard). The shard index, with a crc32c checksum, is at the end of
  each shard file. A reader fetches it with a suffix Range request, then each
  chunk it needs by byte range.
- 18 shard files in all, none over 110 kB: the repository's
  `check-added-large-files` hook caps one file at 500 kB, and a shard is one
  file.
- zstd, not gzip: gzip stamps the write time into every chunk, and the store
  would change on every run.
- 12-bit data kept as uint16 (the OME-TIFF example is converted to 8 bits).
  The three channels are lily's Ch1 (cell walls, magenta), Ch2 (thick walls,
  green) and Ch4 (cell walls, cyan); Ch3, a dimmer copy of Ch2, is left out.
- The crop (rows 410 to 921, columns 0 to 511) holds vascular bundles and the
  stem's outer ring, where the OME-TIFF shows the middle of the section.

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
- Lily cells are the dark lumens between the bright walls, split with a
  distance-transform watershed. `wall_type` is "thick-walled" when a cell's
  Ch2 intensity (lumen plus a 2 px wall ring) is above the Otsu cut over all
  cells: in practice the sheaths around the vascular bundles and the stem's
  outer ring. A heuristic, not a classifier. `lily_sharded_cells.csv` applies
  the same recipe to the three channels of that store, at 12 bits.
- The SpatialData spots follow the same layout rule as `ihc_spatial`, with a
  32 px pitch. Nuclei are local hematoxylin maxima, so the cornified top layer
  yields a few false ones. Clusters are k-means on each spot's mean
  hematoxylin, eosin and the nuclei within one pitch, numbered so that `C1` is
  the most hematoxylin-rich. `gene_A` follows hematoxylin, `gene_B` eosin,
  `gene_C` nuclear density and `gene_D` a top-to-bottom gradient (Poisson).

## Licences

| Dataset | Licence | Credit |
| --- | --- | --- |
| `kidney` | CC0 | Genevieve Buckley, Monash Micro Imaging, 2018 (confocal, mouse kidney slide) |
| `immunohistochemistry` | No known copyright restrictions | Center for Microscopy and Molecular Imaging (CMMI), colonic glands with FHL2 (DAB) and hematoxylin |
| `human_mitosis` | CC0 | David Root; Moffat et al., Cell 124(6):1283-98, 2006, doi:10.1016/j.cell.2006.01.040 |
| `lily` | CC0 | Genevieve Buckley, Monash Micro Imaging, 2018 (confocal, lily of the valley stem slide) |
| `skin` | Public domain | Wikipedia user Kilbad, [Normal Epidermis and Dermis with Intradermal Nevus 10x](https://en.wikipedia.org/wiki/File:Normal_Epidermis_and_Dermis_with_Intradermal_Nevus_10x.JPG) |

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

`pooch` downloads `kidney`, `human_mitosis`, `lily` and `skin` into the
scikit-image cache on first use. The OME-TIFF is written with `tifffile`, a
scikit-image dependency. The SpatialData and NGFF 0.5 stores need zarr 3, so
the script runs `make_spatialdata_example.py` and `make_ngff05_example.py` in
throwaway environments of their own, `uv run --with spatialdata==0.8.0` and
`uv run --with zarr==3.4.0` (so `uv` must be on `PATH`; pass
`--no-spatialdata` or `--no-ngff05` to skip one and keep the store already
there).

The output is byte-identical across runs for the same `--seed` and library
versions (generated with scikit-image 0.26.0, zarr 2.18.7, numcodecs 0.15.1,
ome-zarr 0.10.3, tifffile 2026.9.20; the SpatialData store with spatialdata
0.8.0, zarr 3.4.0; the NGFF 0.5 store with zarr 3.4.0, read back with ome-zarr
0.19.2). `--help` lists the size, crop, drift, spot and codec options.
