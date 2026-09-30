# nf-core/sopa 1.0.1: Depictio dashboards

This template turns the output of [nf-core/sopa](https://nf-co.re/sopa) 1.0.1 into a four-tab
Depictio dashboard: a paper companion that puts the tissue image next to its segmented cells,
their yield, their clusters and their segmentation quality, for any technology sopa reads
(Xenium, MERSCOPE, CosMx, Visium HD, PhenoCycler, MACSima, H&E). It is not an image-analysis
workbench: sopa's own Xenium Explorer files (`<sample>.explorer/`) remain the place for
transcript-level inspection.

> **Authored offline.** The AWS megatest of 1.0.1 cannot be read (the per-sample `.zarr` is a
> dangling symlink, the explorer TIFF is JPEG 2000). The layout comes from the pipeline's
> `docs/output.md`, its local modules and the nf-test snapshots of the `test` profile, and the
> recipes were run on a synthetic sopa 2.2 run of the toy dataset. The reference runs are the
> `test` and `test_full` profiles on the EMBL cluster; see `megatest.yaml`.

## What the pipeline writes, and what the template reads

sopa converts each sample into one [SpatialData](https://spatialdata.scverse.org) store,
`<sample>.zarr`, segments it patch by patch, aggregates transcripts and channel intensities per
cell and, optionally, annotates and clusters the cells. Everything lands in the store:

| Element | Content | Read by |
| --- | --- | --- |
| `images/<name>` | morphology image (multiscale), plus an H&E image on some technologies | `sp-img-morphology` (viewer) |
| `shapes/<method>_boundaries` | cell polygons of the segmentation method | not read (see Limits) |
| `points/transcripts` | one row per transcript | not read |
| `tables/table` | one row per cell: `obs` (cell_id, region, slide, area, and the options' columns), `obsm/spatial`, `X` | `sopa_cells_raw`, `sopa_cell_genes_raw` |

The two table collections use the `format: spatialdata` reader: one row per cell with the `obs`
columns, `x` / `y` converted from `obsm/spatial` into the level-0 pixels of the morphology
image (so the points land on the image without any scale setting), and, for the gene
collection, one column per requested gene read out of `X`.

### Template variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATA_ROOT` | required | results directory (the `<sample>.zarr` stores sit at its top level) |
| `IMAGE_ELEMENT` | `image` | image element the viewer shows and the coordinates refer to: `image` on the toy dataset, `morphology_focus` on Xenium, `<dataset_id>_full_image` on Visium HD, `<region>_z3` on MERSCOPE. The store's root attribute `cell_segmentation_image` names it. |
| `GENES` | unset | genes (as in the table's var names) for the Clusters and genes tab. Unset, the three gene collections and their tiles are left out. |
| `METADATA_FILE`, `METADATA_ID_COL`, `GROUP_COL` | unset | design table (TSV, one row per sample); `GROUP_COL` becomes the hub's `condition` |

**How genes are chosen.** A spatial panel has hundreds of genes (a Visium HD run, the whole
transcriptome) and no gene is a sensible default across tissues and technologies, so the
template carries no gene panel. The run names its genes through `GENES`, typically the lineage
markers of the tissue or the genes of the paper's figures; the same list drives the gene
columns read from `X` and the long per-cell table. Values are log-normalised when the run used
`--use_scanpy_preprocessing` and raw counts otherwise.

### One schema over run options

What `obs` carries depends on the run: `leiden` only with `--use_scanpy_preprocessing`,
`cell_type` only with `--use_fluorescence_annotation`, and each segmentation method adds its own
columns (Proseg: `volume`, `surface_area`, `scale`, `component`; Baysor: `n_transcripts`,
`density`, `elongation`, confidences, its own `cluster`). The `sopa/cells` recipe folds this onto
one schema: `cluster` is Leiden when it ran, else the method's own clustering, else empty;
`cell_type` is empty when the run did not annotate; `method` is the boundaries element without
its `_boundaries` suffix. sopa numbers the cells of every store from the same start, so the
recipe adds `cell_uid` (`sample:cell_id`), the run-wide key the lasso and the table select by.

`area` is in the units of the boundaries element: image pixels for Cellpose and StarDist,
microns for the transcript-based methods (Proseg, Baysor, ComSeg).

## Tabs

1. **Overview.** Cells per sample (from the sample hub), cell area and transcripts per cell per
   sample. Transcripts per cell is filled only when the cell table carries a per-cell count
   (Baysor writes `n_transcripts`); on a Proseg or Cellpose run it stays empty (see Limits).
2. **Tissue and cells.** The bioimage viewer shows the morphology image of the first selected
   sample, with every cell as a point at its centroid coloured by cluster. A lasso on the points
   narrows the cell table below (and, through `cell_uid`, the gene and Proseg tiles); a row
   picked in the table fills the cell record at the end of the tab. Tab filters: cluster, cell
   type, cell area.
3. **Clusters and genes.** Cluster and cell-type composition per sample (percent of the
   sample's cells, the twelve most abundant labels of the run kept, the rest pooled as Other,
   `unassigned` when the run computed neither), then, with `GENES`, the marker dot plot (mean
   expression and share of expressing cells per cluster over the run) and per-cell expression
   by cluster.
4. **Segmentation.** Cell area per cluster (a cluster of tiny or huge cells is more often an
   artefact than a cell type), then Proseg's own readings: volume, surface area, their ratio
   (high for thin or fragmented cells), the expression scale, and the per-cell table.

Every tab carries the pinned `Run at a glance` strip (samples by condition, cells segmented,
cell area, clusters), the collapsed `Sample sheet` and the `Sample filters` (sample, condition);
each tab adds its own filters.

## Limits (platform, not the pipeline)

- **Cells as points, not outlines.** sopa writes the segmentation as shapes, and the viewer's
  labels overlay reads TIFF or OME-Zarr label images only; SpatialData `labels` and `shapes`
  elements are not rendered yet, so cells are drawn at their centroids.
- **No UMAP.** `obsm/X_umap` (with `--use_scanpy_preprocessing`) and `obsm/intensities` (the
  per-cell channel means of `--aggregate_channels`) are not read by the table reader, which
  takes `obsm/spatial` only.
- **Transcripts per cell** needs a per-cell count in `obs`; Proseg, Cellpose and StarDist runs
  have none, and the reader cannot sum `X` yet.
- **Baysor runs.** Baysor's table carries `x` / `y` columns in `obs`, which collide with the
  reader's coordinate columns; the catalog's `baysor/cell_metadata` is ready, the raw read is not.
- The explorer's `analysis_summary.html` (sopa's QC report) is not ingested; open it from the
  run directory.
