# nf-core/cellpainting 1.0.0dev: Depictio dashboards

> **Unreleased pipeline.** nf-core/cellpainting has no release yet. This template targets the
> `dev` branch at commit `40423f0d1da0dde52bd5f1fd812ee6a1549cdfb3` (2026-04-29) and was
> validated on the AWS megatest of that commit. Output paths may change before 1.0.0; the
> layout notes below say which ones the template depends on.

This template turns the output of [nf-core/cellpainting](https://github.com/nf-core/cellpainting)
into a five-tab Depictio dashboard: a paper-companion view of one Cell Painting screen, easy to
deploy, with the segmentation images next to the per-cell tables, the QC and the filters.
The pipeline runs [CellProfiler](https://cellprofiler.org) three times (illumination correction
per plate and channel, assay development on one site per well, full analysis on every site) and
collates the per-object measurement tables of every site with
[CytoTable](https://github.com/cytomining/CytoTable) into one Parquet file per site.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `cp-cells` | `cytotable/<batch>_<plate>_<well>_<site>.parquet` | cell |
| `cp-sites` | derived from `cp-cells` | site |
| `samples` | the plate map (`METADATA_FILE`, default `input/platemap.csv`), restricted to the imaged wells | well |
| `cp-wells` | derived from `cp-cells` and `samples` | well |
| `cp-plate-layout` | derived from `cp-wells` | plate row |
| `cp-cell-profiles`, `cp-cell-embedding` | derived from `cp-cells` and `samples` | cell |
| `cp-image-qc` (optional) | `cellprofiler/analysis/**/Image.csv` | site and channel |
| `cp-illumination` (optional) | `cellprofiler/illumination_correction/**/<plate>_Illum<channel>.npy` | plate, channel, ring |
| `cp-overlays` (optional, `Image` type) | `cellprofiler/**/*_ObjectOverlay.png`, `*--{cell,nuclei}_outlines.png` | image file |

Every collection is keyed on `well_id` = `<plate>_<well>` (plus `site_id` and `cell_id` below
it). The plate, well and site come from the CytoTable file names: the site is the last
underscore-separated token, the well the one before, the plate the one before that, and the batch
whatever precedes it. Wells are normalised to a row letter plus a two-digit column (`A3` -> `A03`)
on both the file side and the plate-map side.

### The curated feature set

CytoTable writes close to 6000 measurements per cell. `cytotable/single_cell.py` projects a
curated subset at read time (so a full plate never loads the full width): the CytoTable
identifier columns (`Metadata_ImageNumber`, `Metadata_ObjectNumber`, the cytoplasm's parent cell
and nucleus), the nucleus centre, and one to three features per family and compartment: size and
shape (cell, nucleus and cytoplasm area, eccentricity, form factor, solidity), DNA content
(integrated and mean nuclear DNA), mean intensity of each stain in the cell, texture (nuclear DNA
contrast, mitochondrial entropy), granularity (mitochondria, ER), colocalisation (ER with
mitochondria, DNA with RNA), perinuclear mitochondria (innermost radial ring) and crowding
(touching cells). The mapping from CellProfiler column to tidy name is the `FEATURES` dict of
the recipe. A run with a custom `--cellprofiler_analysis_cppipe` that does not measure one of
them fails with a column-not-found error naming it; edit `FEATURES`.

### Aggregation and statistics

- **Per site / per well**: counts and medians over the cells (robust to mis-segmented objects),
  the pycytominer `aggregate` convention.
- **Well z-scores** (`z_<feature>`): `(median - median over wells) / (1.4826 x MAD over wells)`,
  standardised against every well of the run, not against negative controls; the per-group
  comparison is on the Perturbations tab.
- **PCA**: every curated feature standardised (median-imputed, constant features dropped),
  eigen-decomposition of the feature covariance, first three components, sign fixed so the map is
  stable between ingests. The variance explained per component is in `pc_<k>_variance`.
- **Group comparison**: the `group_compare` renderer runs a Wilcoxon test per curated feature
  between the cells of two groups (plate-map groups or saved selections), Benjamini-Hochberg
  corrected. Cells of one well are not independent observations, so it ranks features to look
  at; it does not test the perturbation.
- **Illumination**: each correction function (scaled so its minimum is 1) is reduced to the mean
  factor in 50 rings from the field centre to the corners, plus its max over min.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/platemap.csv` | plate map read by `samples` (CSV or TSV) |
| `METADATA_ID_COL` | `well_id` | recorded only: the hub joins on `well_id`, built from the plate and well columns |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `pert_type`, `Perturbation type` | grouping column of the plate map: pinned filter, glance donut, heatmap strip, box plots, group comparison |
| `IMAGES_S3_BASE` | `s3://depictio-bucket/nf-core-cellpainting/` | S3 prefix the segmentation PNGs were pushed to |

The plate map needs a plate and a well column (`plate`/`well` or the JUMP / pycytominer
`Metadata_Plate`/`Metadata_Well`); every other column is kept. The default `GROUP_COL` follows
the JUMP Cell Painting convention (`pert_type`: `trt`, `negcon`, `poscon`); pass
`--var GROUP_COL=<column>` for a plate map organised by compound, gene or dose. A well imaged but
absent from the plate map is kept, in group `Not in plate map`.

The segmentation PNGs are not copied by the ingest; push them once, then run the template:

```bash
depictio-cli images push <DATA_ROOT> s3://depictio-bucket/nf-core-cellpainting/ --extensions .png
depictio-cli run --template nf-core/cellpainting/1.0.0dev --data-root <DATA_ROOT>
```

## Tabs

1. **Overview** (main tab). The plate layout of cells segmented per well (complex heatmap, plate
   rows down, plate columns across, wells not imaged left empty), cells per well coloured by
   group, and the per-well profile table with a well record beside it.
2. **Plate QC**. Four site-level cards, cells per site by well, cell count against nucleus size
   per site (lasso selection), focus (power log-log slope) and saturation per channel, the
   illumination correction profiles and ranges, the nucleus against cell area scatter of every
   cell, and the site table with a site record.
3. **Images**. The segmentation images as a gallery: the assay-development object overlay of each
   well and, where published, the per-site outlines, filtered by the pinned well and group filters
   and by image kind.
4. **Profiles**. Feature distributions (DNA content histogram, cell area per well), the well x
   feature heatmap of robust z-scores annotated by group, the single-cell PCA, and the cell
   table (collapsed).
5. **Perturbations**. Wells and cells per group, well medians of cell area and DNA content by
   group, and the two-group feature comparison (volcano).

Every tab carries the pinned glance strip (wells by group, cells segmented, sites imaged, cells
per site), the pinned Well filters (well and `GROUP_COL`) and an open tab-local filter section.

## Layout notes (dev commit 40423f0)

- `docs/output.md` documents one analysis directory per site
  (`cellprofiler/analysis/<batch>_<plate>_<well>_<site>/`), but the megatest publishes the
  analysis step flat (`cellprofiler/analysis/analysis/`), so its `Image.csv`, object CSVs and
  outline PNGs hold only the last site written. The per-cell data of every site is intact in
  `cytotable/`, which is what the profiles use; the image-quality panels and the outline images
  show that one site until the pipeline publishes per-site directories. Both are optional
  collections and work unchanged with the documented layout.
- The assay-development overlays sit in `cellprofiler/assay_development/assaydevelopment/`,
  one per well, named `<batch>_<plate>_<well>_ObjectOverlay.png`; their site is the
  `--cellprofiler_assaydevelopment_site` parameter, which the file name does not carry.
- The MultiQC report carries run metadata only (no module ran), so there is no MultiQC tab.

## Out of scope

- **Bioimage viewer.** The raw TIFF stacks are pipeline inputs (read from the Cell Painting
  gallery bucket), not outputs, and the run publishes no pyramidal image. A viewer tab with the
  segmentation masks as labels and the cells as points can be added once the images are
  converted to OME-Zarr (or OME-TIFF) and the masks exported, using the `bioimage` collection
  type and the `bioimage_viewer` tile.
- **Normalised profiles and feature selection.** pycytominer `normalize` / `feature_select` and
  replicate-based metrics (mAP) are not part of the pipeline at this commit.

## Screenshots

To be added after the first ingest.
